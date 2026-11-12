"""Página de situação em Markdown (STATUS.md), gravada a cada rodada e visível no GitHub, inclusive no celular."""
from __future__ import annotations

from . import names
from .mailer import PAY_LABELS, brasilia_time, format_brl
from .panel import STATE_TEXT, ago

BASIS = {"total": "total estimado com taxas", "listed": "preço anunciado"}
STATTRAK = {"any": "com ou sem", "only": "somente StatTrak", "exclude": "sem StatTrak"}


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render(db, sources, now, fx_rates, market_config, round_minutes=None) -> str:
    lines = [
        "# Monitor de skins: situação",
        "",
        f"Atualizado em **{brasilia_time(now)}** (horário de Brasília). "
        + (f"Rodadas a cada {round_minutes} min pela agenda do GitHub, que pode atrasar alguns minutos."
           if round_minutes else "A próxima rodada sai pela agenda do GitHub, que pode atrasar alguns minutos."),
        "",
    ]
    usd = (fx_rates or {}).get("USD")
    if usd:
        lines += [f"Câmbio usado: US$ 1 = R$ {usd:.4f}".replace(".", ","), ""]

    lines += ["## Alertas", "", "| Skin | Teto | Compara com | Desgastes | StatTrak | Situação |", "| --- | --- | --- | --- | --- | --- |"]
    for alert in db.alerts():
        lines.append(
            f"| {_cell(alert.name)} | {format_brl(alert.max_price)} | {BASIS.get(alert.basis, alert.basis)} | "
            f"{', '.join(alert.wears) or 'qualquer'} | {STATTRAK.get(alert.stattrak, alert.stattrak)} | "
            f"{'ativo' if alert.active else 'pausado'} |"
        )
    lines += ["", "Para mudar o teto, edite o arquivo `config.json` na branch principal.", ""]

    lines += ["## Lojas", "", "| Loja | Situação | Última consulta OK | Intervalo | Menor preço | Link no e-mail | Pagamento |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for source in sources:
        st = db.get_status(source.id)
        enabled = market_config(source)["enabled"]
        state = st.get("state") if enabled else "desativada"
        situation = STATE_TEXT.get(state, "aguardando primeira consulta")
        if enabled and st.get("error") and state in ("erro", "limite"):
            situation += ": " + st["error"][:140]
        ok = f"{brasilia_time(st['last_ok'])} ({ago(now - st['last_ok'])})" if st.get("last_ok") else "nenhuma ainda"
        best = format_brl(st["best_brl"]) + " " + names.short(st.get("best_name") or "") if st.get("best_brl") is not None and enabled else "-"
        link = "faca específica" if source.link_kind == "offer" else "busca ou página do item"
        minutes = max(int(source.interval / 60) or 1, round_minutes or 0)
        lines.append(
            f"| {_cell(source.label)} | {_cell(situation)} | {ok} | {minutes} min | {_cell(best.strip())} | "
            f"{link} | {PAY_LABELS.get(source.pay_kind, source.pay_kind)} |"
        )

    lines += ["", "## Últimos e-mails", ""]
    sent = db.recent_sent(10)
    if sent:
        lines += ["| Horário de Brasília | Assunto |", "| --- | --- |"]
        lines += [f"| {brasilia_time(row['at'])} | {_cell(row['subject'])} |" for row in sent]
    else:
        lines.append("Nenhum e-mail enviado ainda.")
    return "\n".join(lines) + "\n"
