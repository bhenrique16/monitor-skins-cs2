"""Painel web: gerenciar alertas e lojas e conferir quando cada loja foi consultada."""
from __future__ import annotations

import base64
import hmac
import json
import re
import secrets
import threading
import time
import urllib.parse
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import names, testmode
from .mailer import PAY_LABELS, SYMBOLS, brasilia_time, delivery_text, format_brl
from .sources import NOT_INTEGRATED

MAX_BODY = 64 * 1024
LOCKOUT_AFTER = 10  # senhas erradas do mesmo IP...
LOCKOUT_WINDOW = 600  # ...dentro deste intervalo (s) bloqueiam o painel para esse IP
STATE_TEXT = {"ok": "Funcionando", "erro": "Com erro", "limite": "Em pausa (limite da loja)", "desativada": "Desativada",
              "sem alertas": "Sem alertas ativos"}
STATE_CLASS = {"ok": "ok", "erro": "bad", "limite": "warn", "desativada": "off", "sem alertas": "off"}

CSS = """
:root{--navy:#1B2838;--ink:#22303F;--muted:#5B6B7B;--rule:#DDE3E9;--page:#EEF1F4;--card:#FFFFFF;--green:#5C7E10;
--ok:#2E7D32;--warn:#B45309;--bad:#B3261E;--off:#8A97A5;
--head:Bahnschrift,'DIN Alternate','Roboto Condensed','Segoe UI',Arial,sans-serif;--body:'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 var(--body)}
header{background:var(--navy);color:#C7D5E0;padding:22px 0 20px}
header>div,main{max-width:1320px;margin:0 auto;padding-left:16px;padding-right:16px}
header h1{margin:0;color:#fff;font:600 28px/1.2 var(--head)}
header p{margin:6px 0 0;max-width:80ch}
main{padding-top:8px;padding-bottom:48px}
td.when{white-space:nowrap}
section{background:var(--card);margin-top:16px;padding:18px 20px 20px;border-radius:6px}
h2{margin:0 0 4px;font:600 21px/1.3 var(--head);color:var(--navy)}
.hint{margin:0 0 14px;color:var(--muted);max-width:80ch}
.flash{margin-top:16px;padding:12px 16px;border-radius:6px;background:#E8F3E8;color:var(--ok);font-weight:600}
.flash.erro{background:#FBEAE8;color:var(--bad)}
section.banner{background:#FFF4E5;color:#8A4B08}section.banner h2{color:#8A4B08}section.banner p{margin:0 0 12px}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{text-align:left;font:600 13px var(--body);color:var(--muted);padding:6px 10px 6px 0;border-bottom:1px solid var(--rule);white-space:nowrap}
td{padding:10px 10px 10px 0;border-bottom:1px solid var(--rule);vertical-align:top}
td small,.small{display:block;font-size:13px;color:var(--muted)}
tr.ok td:first-child{box-shadow:inset 3px 0 var(--ok)} tr.bad td:first-child{box-shadow:inset 3px 0 var(--bad)}
tr.warn td:first-child{box-shadow:inset 3px 0 var(--warn)} tr.off td:first-child{box-shadow:inset 3px 0 var(--off)}
tr.ok td:first-child,tr.bad td:first-child,tr.warn td:first-child,tr.off td:first-child{padding-left:12px}
.state{font-weight:600}.state.ok{color:var(--ok)}.state.bad{color:var(--bad)}.state.warn{color:var(--warn)}.state.off{color:var(--off)}
.err{color:var(--bad);font-size:13px;display:block;max-width:44ch;overflow-wrap:anywhere}
input[type=text]{font:inherit;color:inherit;padding:6px 8px;border:1px solid #B6C1CC;border-radius:4px;background:#fff;width:100%}
input.num{width:7.5em;text-align:right} select{font:inherit;padding:6px 8px;border:1px solid #B6C1CC;border-radius:4px;background:#fff}
label{font-size:13px;color:var(--muted);display:block}
label.check{display:inline-flex;gap:6px;align-items:center;color:var(--ink);font-size:14px;margin-right:12px;white-space:nowrap}
button{font:600 15px var(--head);padding:8px 16px;border-radius:4px;border:1px solid var(--green);background:var(--green);color:#fff;cursor:pointer}
button.plain{background:#fff;color:var(--bad);border-color:#D9B4B0}
:focus-visible{outline:3px solid #66C0F4;outline-offset:2px}
.alert{display:grid;grid-template-columns:minmax(220px,2fr) 9em minmax(190px,1.3fr) 10em;gap:12px 16px;align-items:end;
padding:14px 0;border-bottom:1px solid var(--rule)}
.alert .wide{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:6px 4px;align-items:center}
.alert .actions{grid-column:1/-1;display:flex;gap:10px}
.inline{display:flex;flex-wrap:wrap;gap:12px 16px;align-items:end}
details{margin-top:14px}summary{cursor:pointer;color:var(--navy);font-weight:600}
@media (max-width:760px){.alert{grid-template-columns:1fr 1fr}.alert>div:first-child{grid-column:1/-1}}
"""


def parse_price(text):
    """Aceita "1.700,00", "1700", "1700.50", "R$ 2.000". Devolve None se não for um valor positivo."""
    raw = re.sub(r"[^0-9,.\-]", "", str(text or ""))
    if not raw or raw.startswith("-"):
        return None
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1 or (raw.count(".") == 1 and len(raw.rsplit(".", 1)[1]) == 3):
        raw = raw.replace(".", "")  # ponto como separador de milhar
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def parse_pct(text):
    """Percentual ou taxa: vazio = desconhecido (None); aceita vírgula decimal; nunca negativo."""
    raw = str(text or "").strip().replace("%", "").replace(",", ".")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"há {seconds} s"
    if seconds < 3600:
        return f"há {seconds // 60} min"
    if seconds < 86400:
        return f"há {seconds // 3600} h"
    return f"há {seconds // 86400} d"


def _num(value) -> str:
    return "" if value is None else f"{value:g}".replace(".", ",")


class Panel:
    def __init__(self, db, sources, send_test, mail_info="", fx_state=lambda: {}, password="", now=time.time):
        self.db, self.sources, self.send_test, self.mail_info = db, list(sources), send_test, mail_info
        self.fx_state, self.password, self.now = fx_state, password or "", now
        self.csrf = secrets.token_urlsafe(24)
        self._failures = {}  # IP -> horários das senhas erradas recentes
        self._failures_lock = threading.Lock()

    # ---- bloqueio de tentativas de senha ----------------------------------
    def _recent_failures(self, client):
        cutoff = time.time() - LOCKOUT_WINDOW
        recent = [t for t in self._failures.get(client, ()) if t > cutoff]
        if recent:
            self._failures[client] = recent
        else:
            self._failures.pop(client, None)
        return recent

    def blocked(self, client) -> bool:
        with self._failures_lock:
            return len(self._recent_failures(client)) >= LOCKOUT_AFTER

    def record_failure(self, client) -> None:
        with self._failures_lock:
            self._failures[client] = self._recent_failures(client) + [time.time()]

    # ---- dados -----------------------------------------------------------
    def market_config(self, source) -> dict:
        row = self.db.market_overrides().get(source.id)
        if row is None:
            return {"enabled": source.default_enabled, "fee_pct": source.default_fee_pct, "fee_fixed": source.default_fee_fixed}
        return {"enabled": bool(row["enabled"]), "fee_pct": row["fee_pct"], "fee_fixed": row["fee_fixed"]}

    def status_json(self) -> dict:
        return {
            "agora": self.now(),
            "alertas_ativos": len(self.db.alerts(active_only=True)),
            "lojas": {s.id: dict(self.db.get_status(s.id), label=s.label, enabled=self.market_config(s)["enabled"]) for s in self.sources},
        }

    # ---- página ------------------------------------------------------------
    def _alert_form(self, alert) -> str:
        e = escape
        wears = "".join(
            f'<label class="check"><input type="checkbox" name="wear_{code}"{" checked" if code in alert.wears else ""}> {code}</label>'
            for code in names.WEAR_NAMES
        )

        def opt(value, label, current):
            return f'<option value="{value}"{" selected" if value == current else ""}>{label}</option>'

        return f"""
<form class="alert" method="post" action="/alertas/{alert.id}">
<input type="hidden" name="csrf" value="{self.csrf}">
<div><label for="n{alert.id}">Skin (nome em inglês, sem desgaste)</label><input type="text" id="n{alert.id}" name="name" value="{e(alert.name, quote=True)}" required></div>
<div><label for="p{alert.id}">Teto em reais</label><input type="text" class="num" id="p{alert.id}" name="max_price" value="{_num(round(alert.max_price, 2))}" inputmode="decimal" required></div>
<div><label for="b{alert.id}">Comparar o teto com</label><select id="b{alert.id}" name="basis">
{opt("total", "Total estimado com taxas", alert.basis)}{opt("listed", "Preço anunciado", alert.basis)}</select></div>
<div><label for="s{alert.id}">StatTrak</label><select id="s{alert.id}" name="stattrak">
{opt("any", "Com ou sem", alert.stattrak)}{opt("only", "Somente StatTrak", alert.stattrak)}{opt("exclude", "Sem StatTrak", alert.stattrak)}</select></div>
<div class="wide"><span class="small" style="margin-right:8px">Desgastes (nenhum marcado = qualquer):</span>{wears}</div>
<div class="wide">
<label class="check"><input type="checkbox" name="include_incomplete"{" checked" if alert.include_incomplete else ""}> Receber ofertas com total incompleto (taxa da loja desconhecida)</label>
<label class="check"><input type="checkbox" name="active"{" checked" if alert.active else ""}> Alerta ativo</label>
</div>
<div class="actions"><button type="submit">Salvar alerta</button>
<button type="submit" class="plain" formaction="/alertas/{alert.id}/excluir" formnovalidate>Excluir</button></div>
</form>"""

    def _store_row(self, source, now) -> str:
        e = escape
        cfg, st = self.market_config(source), self.db.get_status(source.id)
        state = st.get("state") if cfg["enabled"] else "desativada"
        cls = STATE_CLASS.get(state, "off")
        every = f"<small>consulta a cada {int(source.interval)} s</small>"
        if st.get("last_poll"):
            date, clock = brasilia_time(st["last_poll"]).split(" ")
            checked = f'<strong>{clock}</strong><small>{date}, {ago(now - st["last_poll"])}</small>{every}'
        else:
            checked = f"ainda não consultada{every}"
        state_html = f'<span class="state {cls}">{e(STATE_TEXT.get(state, "Aguardando primeira consulta"))}</span>'
        if st.get("error") and cfg["enabled"]:
            state_html += f'<span class="err">{e(st["error"])}</span>'
        if st.get("note") and cfg["enabled"]:
            state_html += f'<small>{e(st["note"])}</small>'
        if st.get("last_ok") and state in ("erro", "limite"):
            state_html += f'<small>última resposta boa {ago(now - st["last_ok"])}</small>'
        if st.get("best_brl") is not None and cfg["enabled"]:
            found = f'{e(format_brl(st["best_brl"]))}<small>{e(names.short(st.get("best_name") or ""))}</small>'
            found += f'<small>{int(st.get("matched") or 0)} oferta(s), {int(st.get("eligible") or 0)} dentro do teto</small>'
        elif st.get("last_ok") and cfg["enabled"]:
            found = "nenhuma oferta da skin"
        else:
            found = ""
        pay = e(PAY_LABELS.get(source.pay_kind, source.pay_kind))
        link = "link do anúncio" if source.link_kind == "offer" else "link da busca na loja"
        pay += f"<small>{e(source.pay_note)}</small><small>{e(source.currency)}, {link}</small>"
        key = ""
        if source.key_env:
            key = f'<small>Chave {e(source.key_env)}: {"definida" if source.key() else "não definida"}</small>'
        symbol = SYMBOLS.get(source.currency, source.currency)
        return f"""<tr class="{cls}">
<td><strong>{e(source.label)}</strong><small>{e(source.data_note)}</small>{key}</td>
<td>{state_html}</td><td class="when">{checked}</td><td>{found}</td><td>{pay}</td>
<td><input type="text" class="num" name="fee_pct_{source.id}" value="{_num(cfg['fee_pct'])}" placeholder="desconhecida" aria-label="Taxa percentual de {e(source.label, quote=True)}" inputmode="decimal"></td>
<td><input type="text" class="num" name="fee_fixed_{source.id}" value="{_num(cfg['fee_fixed'] or 0)}" aria-label="Taxa fixa de {e(source.label, quote=True)} em {symbol}" inputmode="decimal"><small>{symbol}</small></td>
<td><label class="check"><input type="checkbox" name="enabled_{source.id}"{" checked" if cfg["enabled"] else ""}> Consultar</label></td>
</tr>"""

    def _status_row(self, source, now) -> str:
        """Linha curta da situação de uma loja, pensada para a tela do celular."""
        e = escape
        cfg, st = self.market_config(source), self.db.get_status(source.id)
        state = st.get("state") if cfg["enabled"] else "desativada"
        cls = STATE_CLASS.get(state, "off")
        kind = "anúncio individual" if source.link_kind == "offer" else "preço de referência"
        state_html = f'<span class="state {cls}">{e(STATE_TEXT.get(state, "Aguardando primeira consulta"))}</span>'
        if st.get("error") and cfg["enabled"] and state in ("erro", "limite"):
            state_html += f'<span class="err">{e(st["error"][:160])}</span>'
        if st.get("last_ok"):
            clock = brasilia_time(st["last_ok"])
            ok = f'<strong>{clock[11:]}</strong><small>{clock[:10]}, {ago(now - st["last_ok"])}</small>'
        else:
            ok = "nenhuma ainda"
        best = e(format_brl(st["best_brl"])) if st.get("best_brl") is not None and cfg["enabled"] else ""
        return (f'<tr class="{cls}"><td><strong>{e(source.label)}</strong><small>{kind}, a cada {int(source.interval)} s</small></td>'
                f'<td>{state_html}</td><td class="when">{ok}</td><td>{best}</td></tr>')

    def _test_banner(self) -> str:
        current = testmode.state(self.db)
        if not current["active"]:
            return ""
        ceiling = format_brl(current["ceiling"] or 0)
        originals = ", ".join(format_brl(v) for v in current["original"].values())
        return f"""<section class="banner" role="status"><h2>Modo de teste ativo</h2>
<p>Teto temporário de {escape(ceiling)}; os e-mails saem com [TESTE] no assunto. Teto original: {escape(originals)}.</p>
<form method="post" action="/teste/encerrar"><input type="hidden" name="csrf" value="{self.csrf}">
<button type="submit">Encerrar teste e restaurar o teto</button></form></section>"""

    def page(self, query: dict) -> str:
        e = escape
        now = self.now()
        alerts = self.db.alerts()
        fx = self.fx_state() or {}
        rates = fx.get("rates") or {}
        if rates.get("USD"):
            rate = f'{rates["USD"]:.4f}'.replace(".", ",")
            fx_text = f"Câmbio: US$ 1 = R$ {rate} ({e(str(fx.get('source', '')))}, {ago(now - fx.get('at', now))})."
        else:
            fx_text = "Câmbio ainda não obtido: ofertas em dólar ficam sem avaliação até a primeira cotação."
        active_stores = sum(1 for s in self.sources if self.market_config(s)["enabled"])
        flash = ""
        if query.get("ok"):
            flash = f'<div class="flash" role="status">{e(query["ok"][0])}</div>'
        elif query.get("erro"):
            flash = f'<div class="flash erro" role="alert">{e(query["erro"][0])}</div>'
        alert_forms = "".join(self._alert_form(a) for a in alerts) or '<p class="hint">Nenhum alerta. Adicione uma skin abaixo.</p>'
        store_rows = "".join(self._store_row(s, now) for s in self.sources)
        status_rows = "".join(self._status_row(s, now) for s in self.sources)
        sent_rows = "".join(
            f"<tr><td>{e(brasilia_time(r['at']))}</td><td>{e(r['subject'])}</td><td>{e(str(r['dest'] or ''))}</td></tr>"
            for r in self.db.recent_sent(15)
        ) or '<tr><td colspan="3">Nenhum e-mail enviado ainda.</td></tr>'
        missing = "".join(f"<tr><td><strong>{e(n)}</strong></td><td>{e(why)}</td></tr>" for n, why in NOT_INTEGRATED)
        iof, spread = self.db.get_float("iof_pct", 3.5), self.db.get_float("spread_pct", 4.0)
        warn_checked = " checked" if self.db.get("aviso_falha", "1") == "1" else ""
        return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor de skins</title><style>{CSS}</style></head><body>
<header><div><h1>Monitor de skins de CS2</h1>
<p>{sum(1 for a in alerts if a.active)} alerta(s) ativo(s), {active_stores} de {len(self.sources)} lojas em consulta. {fx_text}
Página gerada às {e(brasilia_time(now)[11:])}, horário de Brasília. <a href="/" style="color:#66C0F4">Atualizar</a></p></div></header>
<main>{flash}{self._test_banner()}
<section><h2>Situação das lojas</h2>
<p class="hint">Horário de Brasília da última resposta válida de cada loja. Lojas com preço de referência informam só o menor preço do item, sem link da faca específica.</p>
<div class="scroll"><table>
<thead><tr><th>Loja</th><th>Situação</th><th>Última consulta OK</th><th>Menor preço</th></tr></thead>
<tbody>{status_rows}</tbody></table></div>
</section>
<section><h2>Alertas</h2>
<p class="hint">Você recebe um e-mail quando aparece uma oferta dentro do teto, ou quando um anúncio já existente baixa de preço e cruza o teto. Mudanças valem a partir da próxima consulta de cada loja.</p>
{alert_forms}
<form class="inline" method="post" action="/alertas/novo" style="padding-top:16px">
<input type="hidden" name="csrf" value="{self.csrf}">
<div style="flex:2 1 260px"><label for="novo-nome">Nova skin (nome em inglês, como na Steam)</label><input type="text" id="novo-nome" name="name" placeholder="★ Karambit | Doppler" required></div>
<div><label for="novo-teto">Teto em reais</label><input type="text" class="num" id="novo-teto" name="max_price" placeholder="1700,00" inputmode="decimal" required></div>
<button type="submit">Adicionar alerta</button></form>
</section>
<section><h2>Configurar lojas</h2>
<p class="hint">A taxa entra no total estimado. Deixe a taxa percentual em branco quando não souber: o total sai marcado como incompleto. Desmarque as lojas onde você não consegue pagar.</p>
<form method="post" action="/lojas"><input type="hidden" name="csrf" value="{self.csrf}">
<div class="scroll"><table>
<thead><tr><th>Loja</th><th>Situação</th><th>Última consulta</th><th>Menor preço da skin</th><th>Pagamento</th><th>Taxa %</th><th>Taxa fixa</th><th>Ativa</th></tr></thead>
<tbody>{store_rows}</tbody></table></div>
<p style="margin:14px 0 0"><button type="submit">Salvar lojas</button></p></form>
<details><summary>Lojas pesquisadas e não integradas</summary>
<div class="scroll"><table><thead><tr><th>Loja</th><th>Motivo</th></tr></thead><tbody>{missing}</tbody></table></div></details>
</section>
<section><h2>Custos de compra em moeda estrangeira</h2>
<p class="hint">Aplicados às lojas em dólar ou euro pagas em dinheiro: preço e taxa da loja convertidos pelo câmbio comercial, mais o spread do seu cartão, mais o IOF.</p>
<form class="inline" method="post" action="/custos"><input type="hidden" name="csrf" value="{self.csrf}">
<div><label for="iof">IOF (%)</label><input type="text" class="num" id="iof" name="iof_pct" value="{_num(iof)}" inputmode="decimal"></div>
<div><label for="spread">Spread do cartão (%)</label><input type="text" class="num" id="spread" name="spread_pct" value="{_num(spread)}" inputmode="decimal"></div>
<label class="check"><input type="checkbox" name="aviso_falha"{warn_checked}> Avisar por e-mail quando uma loja ficar 1 hora sem responder</label>
<button type="submit">Salvar custos</button></form>
</section>
<section><h2>E-mail</h2>
<p class="hint">{e(self.mail_info)}</p>
<form method="post" action="/teste-email"><input type="hidden" name="csrf" value="{self.csrf}"><button type="submit">Enviar e-mail de teste</button></form>
<h2 style="margin-top:22px">Últimos e-mails enviados</h2>
<div class="scroll"><table><thead><tr><th>Horário de Brasília</th><th>Assunto</th><th>Destino</th></tr></thead><tbody>{sent_rows}</tbody></table></div>
</section>
</main></body></html>"""

    # ---- ações -------------------------------------------------------------
    def _alert_fields(self, form) -> dict:
        def one(key, default=""):
            return (form.get(key) or [default])[0]

        name = names.parse(one("name")).base
        price = parse_price(one("max_price"))
        if not name:
            raise ValueError("informe o nome da skin")
        if price is None:
            raise ValueError("teto inválido: use um valor em reais, como 1700,00")
        basis = one("basis", "total")
        stattrak = one("stattrak", "any")
        return {
            "name": name, "max_price": price,
            "basis": basis if basis in ("total", "listed") else "total",
            "stattrak": stattrak if stattrak in ("any", "only", "exclude") else "any",
            "wears": tuple(code for code in names.WEAR_NAMES if form.get("wear_" + code)),
            "include_incomplete": bool(form.get("include_incomplete")),
            "active": bool(form.get("active")),
        }

    def act(self, path: str, form: dict) -> str:
        """Executa a ação de um POST e devolve a mensagem de sucesso. Erros de entrada levantam ValueError."""
        if path == "/alertas/novo":
            fields = self._alert_fields(dict(form, include_incomplete=["on"], active=["on"]))
            self.db.add_alert(**fields)
            return f"Alerta criado: {fields['name']} até {format_brl(fields['max_price'])}."
        match = re.fullmatch(r"/alertas/(\d+)(/excluir)?", path)
        if match:
            alert_id = int(match.group(1))
            if self.db.get_alert(alert_id) is None:
                raise ValueError("alerta não encontrado")
            if match.group(2):
                self.db.delete_alert(alert_id)
                return "Alerta excluído."
            fields = self._alert_fields(form)
            self.db.update_alert(alert_id, **fields)
            return f"Alerta salvo: {fields['name']} até {format_brl(fields['max_price'])}."
        if path == "/lojas":
            for source in self.sources:
                fee_fixed = parse_pct((form.get("fee_fixed_" + source.id) or [""])[0]) or 0.0
                self.db.set_market(source.id, bool(form.get("enabled_" + source.id)),
                                   parse_pct((form.get("fee_pct_" + source.id) or [""])[0]), fee_fixed)
            return "Lojas salvas."
        if path == "/custos":
            iof, spread = parse_pct((form.get("iof_pct") or [""])[0]), parse_pct((form.get("spread_pct") or [""])[0])
            if iof is None or spread is None:
                raise ValueError("informe IOF e spread em porcentagem")
            self.db.set("iof_pct", iof)
            self.db.set("spread_pct", spread)
            self.db.set("aviso_falha", "1" if form.get("aviso_falha") else "0")
            return "Custos salvos."
        if path == "/teste/encerrar":
            restored = testmode.finish(self.db)
            if not restored:
                return "Nenhum teste ativo."
            return "Teste encerrado. Teto restaurado: " + ", ".join(format_brl(v) for v in restored.values()) + "."
        if path == "/teste-email":
            try:
                dest = self.send_test()
            except Exception as exc:
                raise ValueError(f"o e-mail de teste falhou: {exc}") from exc
            return f"E-mail de teste {delivery_text(dest)}."
        raise LookupError(path)

    # ---- servidor ------------------------------------------------------------
    def serve(self, host: str, port: int) -> ThreadingHTTPServer:
        panel = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "skinmon"

            def log_message(self, *args):  # sem log por requisição
                pass

            def _send(self, status, body, content_type="text/html; charset=utf-8", extra=None):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy",
                                 "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def _client(self) -> str:
                # Na Fly.io o proxy informa o IP real do visitante neste cabeçalho.
                return self.headers.get("Fly-Client-IP") or self.client_address[0]

            def _authorized(self) -> bool:
                if not panel.password:
                    return True
                client = self._client()
                if panel.blocked(client):
                    return False
                header = self.headers.get("Authorization", "")
                if not header.startswith("Basic "):
                    return False
                try:
                    given = base64.b64decode(header[6:]).decode("utf-8").split(":", 1)[1]
                except Exception:
                    given = ""
                if hmac.compare_digest(given.encode(), panel.password.encode()):
                    return True
                panel.record_failure(client)
                return False

            def _deny(self):
                if panel.password and panel.blocked(self._client()):
                    return self._send(429, "Muitas senhas erradas. Tente de novo em 10 minutos.", "text/plain; charset=utf-8")
                self._send(401, "Senha necessária.", "text/plain; charset=utf-8", {"WWW-Authenticate": 'Basic realm="Monitor de skins", charset="UTF-8"'})

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                if url.path == "/healthz":
                    return self._send(200, "ok\n", "text/plain; charset=utf-8")
                if not self._authorized():
                    return self._deny()
                if url.path == "/":
                    return self._send(200, panel.page(urllib.parse.parse_qs(url.query)))
                if url.path == "/status.json":
                    return self._send(200, json.dumps(panel.status_json(), ensure_ascii=False), "application/json; charset=utf-8")
                self._send(404, "Página não encontrada.", "text/plain; charset=utf-8")

            def do_POST(self):
                if not self._authorized():
                    return self._deny()
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = 0
                if length > MAX_BODY:
                    return self._send(413, "Formulário grande demais.", "text/plain; charset=utf-8")
                form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True)
                if not hmac.compare_digest((form.get("csrf") or [""])[0], panel.csrf):
                    return self._send(403, "Formulário expirado. Recarregue a página e tente de novo.", "text/plain; charset=utf-8")
                path = urllib.parse.urlsplit(self.path).path
                try:
                    target = "/?ok=" + urllib.parse.quote(panel.act(path, form))
                except LookupError:
                    return self._send(404, "Ação não encontrada.", "text/plain; charset=utf-8")
                except ValueError as exc:
                    target = "/?erro=" + urllib.parse.quote(str(exc))
                self._send(303, "", "text/plain; charset=utf-8", {"Location": target})

        return ThreadingHTTPServer((host, port), Handler)
