"""Linha de comando: python -m skinmon [comando]."""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time

from . import config, names, settings_file, sources, statuspage, testmode
from .db import DB
from .fx import Fx
from .mailer import Mailer, brasilia_time, delivery_text, format_brl, render_sample
from .panel import Panel, ago, parse_price
from .runner import Runner


def log(message: str) -> None:
    print(f"[{brasilia_time(time.time())}] {message}", flush=True)


class App:
    def __init__(self, env=None):
        self.env = os.environ if env is None else env
        config.load_env(".env", self.env)
        self.data = config.data_dir(self.env)
        self.db = DB(os.path.join(self.data, "monitor.db"))
        self.mailer = Mailer.from_env(self.env, self.data)
        self.fx = Fx(self.db)
        self.sources = sources.build(self.env)
        self.runner = Runner(self.db, self.mailer.send, self.sources, self.fx.rates, log=log,
                             max_per_hour=config.int_setting(self.env, "MAX_EMAILS_PER_HOUR", 30))

    def send_test(self) -> str:
        return self.mailer.send(*render_sample(time.time()))


def cmd_run(app: App, args) -> int:
    stop = threading.Event()

    def on_signal(*_):
        stop.set()

    signal.signal(signal.SIGINT, on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, on_signal)

    log(f"Monitor iniciado. {len(app.db.alerts(active_only=True))} alerta(s) ativo(s). E-mail: {app.mailer.describe()}.")
    host = app.env.get("PANEL_HOST", "127.0.0.1")
    port = config.int_setting(app.env, "PANEL_PORT", 8787)
    password = app.env.get("PANEL_PASSWORD", "")
    server = None
    if host not in config.LOOPBACK and not password:
        log("Painel desligado: defina PANEL_PASSWORD para abrir o painel fora de 127.0.0.1.")
    else:
        panel = Panel(app.db, app.sources, send_test=app.send_test, mail_info="Envio: " + app.mailer.describe() + ".",
                      fx_state=app.fx.state, password=password)
        try:
            server = panel.serve(host, port)
        except OSError as exc:
            log(f"Painel não iniciado na porta {port}: {exc}")
        else:
            threading.Thread(target=server.serve_forever, name="painel", daemon=True).start()
            log(f"Painel em http://{'localhost' if host in config.LOOPBACK else host}:{port}" + (" (com senha)" if password else ""))

    app.runner.start(stop)
    while not stop.is_set():
        stop.wait(1)
    log("Encerrando.")
    if server:
        server.shutdown()
    return 0


def cmd_check(app: App, args) -> int:
    started = time.time()
    print("Consultando as lojas uma vez (pode levar até 1 minuto)...", flush=True)
    app.fx.rates()
    results = app.runner.run_once()
    for source, outcome in results:
        print("- " + app.runner.describe(source))
    sent = [row for row in app.db.recent_sent(50) if row["at"] >= started]
    print(f"\n{len(sent)} e-mail(s) de alerta nesta rodada. Envio: {app.mailer.describe()}.")
    for row in sent:
        print(f"  {row['subject']} -> {row['dest']}")
    return 0


ROUND_TIMEOUT = 25  # segundos por requisição no modo rodada, para a execução no GitHub ser curta


def cmd_round(app: App, args) -> int:
    """Uma rodada para agendadores (GitHub Actions): aplica o config.json, consulta as lojas na vez e grava STATUS.md."""
    started = time.time()
    in_actions = app.env.get("GITHUB_ACTIONS") == "true"
    if in_actions and not app.mailer.configured:
        print("Erro: e-mail não configurado. Cadastre os segredos SMTP_USER, SMTP_PASS e MAIL_TO no repositório.")
        return 1
    try:
        cfg = settings_file.load(app.env.get("SKINMON_CONFIG") or "config.json")
    except ValueError as exc:
        print(f"Erro: {exc}")
        return 2
    defaults = {s.id: {"enabled": s.default_enabled, "fee_pct": s.default_fee_pct, "fee_fixed": s.default_fee_fixed}
                for s in app.sources}
    if testmode.state(app.db)["active"]:
        testmode.finish(app.db)  # teste anterior interrompido no meio: volta ao teto normal antes de tudo
    settings_file.sync(app.db, cfg, defaults)
    for source in app.sources:
        source.timeout = min(source.timeout, ROUND_TIMEOUT)

    ceiling = _price_arg(args.teto_teste) if args.teto_teste else None
    if ceiling:
        testmode.start(app.db, ceiling)
        print(f"Rodada de teste: teto temporário {format_brl(ceiling)}, assunto com [TESTE], todas as lojas consultadas.")
    try:
        app.fx.rates()
        results = app.runner.run_due(force=bool(ceiling))
    finally:
        if ceiling:
            restored = testmode.finish(app.db)
            print("Teto restaurado: " + (", ".join(format_brl(v) for v in restored.values()) or "nenhum alerta"))

    checked = {source.id for source, _ in results}
    for source, _ in results:
        print("- " + app.runner.describe(source))
    waiting = [s.label for s in app.sources if s.id not in checked]
    if waiting:
        print("Aguardando a vez: " + ", ".join(waiting))
    sent = [row for row in app.db.recent_sent(50) if row["at"] >= started]
    print(f"{len(sent)} e-mail(s) enviados nesta rodada.")
    for row in sent:
        print(f"  {row['subject']}")

    app.db.prune(time.time())
    page = statuspage.render(app.db, app.sources, time.time(), app.fx.rates(), app.runner.market_config,
                             config.int_setting(app.env, "SKINMON_RODADA_MIN", 0) or None)
    with open(os.path.join(app.data, "STATUS.md"), "w", encoding="utf-8") as handle:
        handle.write(page)
    app.db.close()
    return 0


def cmd_test_email(app: App, args) -> int:
    try:
        dest = app.send_test()
    except Exception as exc:
        print(f"Falha ao enviar o e-mail de teste: {exc}")
        return 1
    print(f"E-mail de teste {delivery_text(dest)}.")
    return 0


def cmd_status(app: App, args) -> int:
    now = time.time()
    for source in app.sources:
        st = app.db.get_status(source.id)
        when = f"{brasilia_time(st['last_poll'])} ({ago(now - st['last_poll'])})" if st.get("last_poll") else "ainda não consultada"
        ok = f"{brasilia_time(st['last_ok'])} ({ago(now - st['last_ok'])})" if st.get("last_ok") else "nenhuma"
        print(f"- {app.runner.describe(source)} | última consulta: {when} | última OK: {ok}")
    return 0


def cmd_test_mode(app: App, args) -> int:
    if args.acao == "iniciar":
        if not args.teto:
            raise SystemExit("Informe o teto temporário, por exemplo: python -m skinmon teste iniciar 2000")
        ceiling = _price_arg(args.teto)
        original = testmode.start(app.db, ceiling)
        print(f"Modo de teste ativo: teto temporário {format_brl(ceiling)}; assunto dos e-mails com [TESTE].")
        print("Teto(s) original(is) guardado(s): " + ", ".join(format_brl(v) for v in original.values()))
        print("O monitor em execução aplica na próxima consulta de cada loja.")
    elif args.acao == "encerrar":
        restored = testmode.finish(app.db)
        if restored:
            print("Teste encerrado. Teto restaurado: " + ", ".join(f"alerta {k}: {format_brl(v)}" for k, v in restored.items()))
        else:
            print("Nenhum teste ativo.")
    else:
        state = testmode.state(app.db)
        print(f"Modo de teste ativo, teto {format_brl(state['ceiling'])}." if state["active"] else "Modo de teste desligado.")
    return 0


def cmd_alerts(app: App, args) -> int:
    alerts = app.db.alerts()
    if not alerts:
        print("Nenhum alerta. Use: python -m skinmon adicionar \"NOME DA SKIN\" TETO")
    for a in alerts:
        basis = "total estimado" if a.basis == "total" else "preço anunciado"
        wears = ",".join(a.wears) or "qualquer desgaste"
        stattrak = {"any": "com ou sem StatTrak", "only": "só StatTrak", "exclude": "sem StatTrak"}[a.stattrak]
        print(f"{a.id}: {a.name} | teto {format_brl(a.max_price)} sobre o {basis} | {wears} | {stattrak} | {'ativo' if a.active else 'pausado'}")
    return 0


def _price_arg(text: str) -> float:
    value = parse_price(text)
    if value is None:
        raise SystemExit(f"Valor inválido: {text}. Use reais, por exemplo 1700 ou 1.700,00.")
    return value


def cmd_add(app: App, args) -> int:
    name = names.parse(args.nome).base
    alert_id = app.db.add_alert(name, _price_arg(args.teto))
    print(f"Alerta {alert_id} criado: {name} até {format_brl(app.db.get_alert(alert_id).max_price)}.")
    return 0


def cmd_ceiling(app: App, args) -> int:
    if app.db.get_alert(args.id) is None:
        raise SystemExit(f"Alerta {args.id} não existe. Veja a lista com: python -m skinmon alertas")
    app.db.update_alert(args.id, max_price=_price_arg(args.teto))
    alert = app.db.get_alert(args.id)
    print(f"Alerta {alert.id}: {alert.name} agora até {format_brl(alert.max_price)}.")
    return 0


def cmd_remove(app: App, args) -> int:
    if app.db.get_alert(args.id) is None:
        raise SystemExit(f"Alerta {args.id} não existe.")
    app.db.delete_alert(args.id)
    print(f"Alerta {args.id} removido.")
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # o console do Windows não imprime "★" na codificação padrão
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(prog="python -m skinmon", description="Monitor pessoal de ofertas de skins de CS2.")
    sub = parser.add_subparsers(dest="comando")
    sub.add_parser("rodar", help="inicia o monitor e o painel (padrão)").set_defaults(func=cmd_run)
    sub.add_parser("checar", help="consulta todas as lojas uma vez e mostra o resultado").set_defaults(func=cmd_check)
    round_parser = sub.add_parser("rodada", help="uma rodada para o GitHub Actions: config.json, lojas na vez, STATUS.md")
    round_parser.add_argument("--teto-teste", dest="teto_teste", help="teto temporário só nesta rodada; assunto com [TESTE]")
    round_parser.set_defaults(func=cmd_round)
    sub.add_parser("email-teste", help="envia um e-mail de teste").set_defaults(func=cmd_test_email)
    sub.add_parser("status", help="mostra a última consulta de cada loja").set_defaults(func=cmd_status)
    sub.add_parser("alertas", help="lista os alertas").set_defaults(func=cmd_alerts)
    add = sub.add_parser("adicionar", help="cria um alerta")
    add.add_argument("nome", help='nome da skin em inglês, ex.: "★ Karambit | Doppler"')
    add.add_argument("teto", help="preço máximo em reais")
    add.set_defaults(func=cmd_add)
    ceiling = sub.add_parser("teto", help="muda o teto de um alerta")
    ceiling.add_argument("id", type=int)
    ceiling.add_argument("teto")
    ceiling.set_defaults(func=cmd_ceiling)
    test = sub.add_parser("teste", help="teto temporário para testar com oferta real (assunto com [TESTE])")
    test.add_argument("acao", choices=("iniciar", "encerrar", "status"))
    test.add_argument("teto", nargs="?")
    test.set_defaults(func=cmd_test_mode)
    remove = sub.add_parser("remover", help="remove um alerta")
    remove.add_argument("id", type=int)
    remove.set_defaults(func=cmd_remove)
    args = parser.parse_args(argv)
    app = App()
    return (getattr(args, "func", None) or cmd_run)(app, args)


if __name__ == "__main__":
    sys.exit(main())
