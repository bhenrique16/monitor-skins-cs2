"""Montagem e envio dos e-mails de alerta."""
from __future__ import annotations

import os
import re
import smtplib
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from html import escape

from . import names
from .models import Alert, MarketInfo, Offer
from .pricing import Cost, CostSettings, MarketFees, estimate

# O Brasil não tem horário de verão desde 2019: Brasília é UTC-3 o ano todo.
BRASILIA = timezone(timedelta(hours=-3))
SYMBOLS = {"BRL": "R$", "USD": "US$", "EUR": "€"}
PAY_LABELS = {"dinheiro": "Dinheiro", "saldo_steam": "Saldo Steam", "troca": "Troca"}
REASONS = {"novo": "Novo anúncio", "baixou": "Baixou de preço", "entrou": "Entrou no seu filtro"}
MAX_LISTED = 10  # ofertas detalhadas por e-mail
STALE_AFTER = 600  # segundos: a partir daí o e-mail mostra a idade do dado da loja

# Cores: azul-marinho e verde de compra da Steam; barra de desgaste nas cores usuais de float.
NAVY, INK, MUTED, RULE, PAGE = "#1B2838", "#22303F", "#5B6B7B", "#DDE3E9", "#E9EDF1"
BUY_GREEN, GOOD, WARN_BG, WARN_INK = "#5C7E10", "#2E7D32", "#FFF4E5", "#8A4B08"
WEAR_BAR = (("FN", 7, "#2E9E5B"), ("MW", 8, "#7DB93B"), ("FT", 23, "#E3B437"), ("WW", 7, "#E08A2C"), ("BS", 55, "#C8443C"))
HEAD_FONT = "Bahnschrift,'DIN Alternate','Roboto Condensed','Segoe UI',Arial,sans-serif"
BODY_FONT = "'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


@dataclass
class AlertItem:
    offer: Offer
    cost: Cost
    reason: str = "novo"
    previous_price: float | None = None


def _number(value: float) -> str:
    text = f"{abs(value):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return ("-" if value < 0 else "") + text


def format_money(value: float, currency: str) -> str:
    return SYMBOLS.get(currency, currency) + " " + _number(value)


def format_brl(value: float) -> str:
    return format_money(value, "BRL")


def brasilia_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, BRASILIA).strftime("%d/%m/%Y %H:%M:%S")


def _wear_text(offer: Offer) -> str:
    code = names.parse(offer.name).wear
    if code is None and offer.float_value is not None:
        code = names.wear_from_float(offer.float_value)
    if code is None and offer.aggregated:
        return "não informado (menor preço entre os desgastes)"
    return names.wear_label(code)


def _float_text(offer: Offer) -> str:
    return f"{offer.float_value:.4f}" if offer.float_value is not None else "não informado"


def _basis_value(alert: Alert, cost: Cost):
    value = cost.listed_brl if alert.basis == "listed" else cost.total_brl
    return value if value is not None else cost.listed_brl


def _listed_text(cost: Cost) -> str:
    if cost.currency == "BRL" or cost.listed_brl is None:
        return format_money(cost.listed, cost.currency)
    rate = f"{cost.fx_rate:.4f}".replace(".", ",")
    return f"{format_money(cost.listed, cost.currency)} = {format_brl(cost.listed_brl)} no câmbio de {rate}"


def _total_text(cost: Cost) -> str:
    return format_brl(cost.total_brl) if cost.total_brl is not None else "não calculado"


def _pay_text(market: MarketInfo) -> str:
    label = PAY_LABELS.get(market.pay_kind, market.pay_kind)
    return f"{label} ({market.pay_note})" if market.pay_note else label


def _button_label(offer: Offer) -> str:
    return "Ver ofertas na loja" if offer.link_kind == "search" else "Abrir oferta"


def _reason_line(item: AlertItem, market: MarketInfo) -> str:
    if item.offer.aggregated:
        line = f"Preço de referência na {market.label}"
    else:
        line = f"{REASONS.get(item.reason, 'Oferta')} na {market.label}"
    if item.reason == "baixou" and item.previous_price is not None:
        line += f", antes {format_money(item.previous_price, item.offer.currency)}"
    return line


def _age_text(data_time, now):
    """Idade do dado da loja, só quando passa de STALE_AFTER (listas de preço atualizadas em lote)."""
    if not data_time or now - data_time <= STALE_AFTER:
        return ""
    minutes = int((now - data_time) // 60)
    age = f"há {minutes} min" if minutes < 120 else f"há {minutes // 60} h"
    return f"Dados da loja de {brasilia_time(data_time)[:16]} ({age}). A oferta pode já ter mudado."


def _delta_text(alert: Alert, value) -> str:
    if value is None:
        return ""
    diff = alert.max_price - value
    if diff >= 0.005:
        return f"{format_brl(diff)} abaixo do seu teto"
    return "no limite do seu teto"


def _float_bar(value: float) -> str:
    pos = max(0.0, min(97.0, value * 100.0))
    cells = "".join(
        f'<td width="{width}%" bgcolor="{color}" style="background:{color};height:8px;font-size:0;line-height:0">&nbsp;</td>'
        for _, width, color in WEAR_BAR
    )
    labels = "".join(
        f'<td width="{width}%" style="padding-top:3px;font:11px {BODY_FONT};color:{MUTED}">{code}</td>' for code, width, _ in WEAR_BAR
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">'
        f'<tr><td colspan="5" style="padding:0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td width="{pos:.1f}%" style="font-size:0;line-height:0">&nbsp;</td>'
        f'<td style="font:11px/11px {BODY_FONT};color:{NAVY}">&#9660;</td><td style="font-size:0;line-height:0">&nbsp;</td>'
        f"</tr></table></td></tr><tr>{cells}</tr><tr>{labels}</tr></table>"
    )


def _row(label: str, value_html: str) -> str:
    return (
        f'<tr><td style="padding:7px 12px 7px 0;border-top:1px solid {RULE};font:14px {BODY_FONT};color:{MUTED};'
        f'vertical-align:top;white-space:nowrap">{escape(label)}</td>'
        f'<td style="padding:7px 0;border-top:1px solid {RULE};font:14px {BODY_FONT};color:{INK}">{value_html}</td></tr>'
    )


def _total_html(cost: Cost) -> str:
    out = f"<strong>{escape(_total_text(cost))}</strong>"
    if len(cost.parts) > 1:
        lines = "".join(f"<br>{escape(label)}: {escape(format_brl(value))}" for label, value in cost.parts)
        out += f'<span style="font-size:12px;color:{MUTED}">{lines}</span>'
    return out


def render_alert(alert: Alert, market: MarketInfo, items: list, now: float):
    """Devolve (assunto, texto, html) para as ofertas de uma consulta. A primeira oferta é o destaque."""
    head = items[0]
    offer, cost = head.offer, head.cost
    value = _basis_value(alert, cost)
    basis_word = "anunciado" if alert.basis == "listed" else "total"
    basis_long = "preço anunciado" if alert.basis == "listed" else "total estimado com taxas"
    title = names.short(offer.name)
    value_text = format_brl(value) if value is not None else format_money(cost.listed, cost.currency)
    subject = f"{title} — {value_text} {basis_word} — {market.label}"
    if offer.aggregated:
        subject += " (preço de referência)"
    if len(items) > 1:
        subject += f" (+{len(items) - 1})"

    when = brasilia_time(now)
    ceiling = f"{format_brl(alert.max_price)} sobre o {basis_long}"
    reason = _reason_line(head, market)
    delta = _delta_text(alert, value)
    button = _button_label(offer)
    warning = ""
    if not cost.complete and cost.missing:
        warning = "Total incompleto: " + "; ".join(cost.missing) + "."
    notes = []
    age = _age_text(offer.data_time, now)
    if age:
        notes.append(age)
    if offer.aggregated:
        notes.append("A loja informa só o menor preço deste item. O link abre a lista de ofertas.")
    if offer.quantity:
        notes.append(f"{offer.quantity} anúncios deste item na loja.")
    if offer.note:
        notes.append(offer.note)
    others = items[1:MAX_LISTED]
    hidden = len(items) - 1 - len(others)

    # ---- texto ---------------------------------------------------------
    lines = [reason, title, "", f"{basis_long.capitalize()}: {value_text}" + (f" ({delta})" if delta else "")]
    lines += [
        f"Preço anunciado: {_listed_text(cost)}",
        f"Total estimado com taxas: {_total_text(cost)}",
    ]
    if len(cost.parts) > 1:
        lines += [f"  {label}: {format_brl(v)}" for label, v in cost.parts]
    lines += [
        f"Desgaste: {_wear_text(offer)}",
        f"Float: {_float_text(offer)}",
        f"Pagamento: {_pay_text(market)}",
        f"Horário de Brasília: {when}",
        f"Seu teto: {ceiling}",
    ]
    if warning:
        lines.append(warning)
    lines += notes
    lines += ["", f"{button}: {offer.url}"]
    if others:
        lines += ["", "Outras ofertas desta consulta:"]
        for it in others:
            v = _basis_value(alert, it.cost)
            lines.append(
                f"- {names.short(it.offer.name)}, float {_float_text(it.offer)}, "
                f"{format_brl(v) if v is not None else format_money(it.cost.listed, it.cost.currency)} {basis_word}: {it.offer.url}"
            )
    if hidden > 0:
        lines.append(f"Mais {hidden} oferta(s) na loja.")
    text = "\n".join(lines) + "\n"

    # ---- html ----------------------------------------------------------
    rows = [
        _row("Desgaste", escape(_wear_text(offer))),
        _row("Float", escape(_float_text(offer))),
        _row("Preço anunciado", escape(_listed_text(cost))),
        _row("Total estimado com taxas", _total_html(cost)),
        _row("Pagamento", escape(_pay_text(market))),
        _row("Horário de Brasília", escape(when)),
        _row("Seu teto", escape(ceiling)),
    ]
    if notes:
        rows.append(_row("Observação", "<br>".join(escape(note) for note in notes)))
    bar = ""
    if offer.float_value is not None:
        bar = f'<tr><td style="padding:14px 24px 0">{_float_bar(offer.float_value)}</td></tr>'
    warn_html = ""
    if warning:
        warn_html = (
            f'<tr><td style="padding:0 24px 16px"><div style="background:{WARN_BG};color:{WARN_INK};padding:10px 12px;'
            f'font:14px {BODY_FONT};border-radius:4px">{escape(warning)}</div></td></tr>'
        )
    others_html = ""
    if others:
        body = ""
        for it in others:
            v = _basis_value(alert, it.cost)
            price = format_brl(v) if v is not None else format_money(it.cost.listed, it.cost.currency)
            link = "ver na loja" if it.offer.link_kind == "search" else "abrir"
            body += (
                f'<tr><td style="padding:7px 8px 7px 0;border-top:1px solid {RULE};font:14px {BODY_FONT};color:{INK}">'
                f"{escape(names.short(it.offer.name))}<br>"
                f'<span style="font-size:12px;color:{MUTED}">float {escape(_float_text(it.offer))}</span></td>'
                f'<td style="padding:7px 8px;border-top:1px solid {RULE};font:14px {BODY_FONT};color:{INK};white-space:nowrap" align="right">'
                f"{escape(price)}</td>"
                f'<td style="padding:7px 0;border-top:1px solid {RULE};font:14px {BODY_FONT}" align="right">'
                f'<a href="{escape(it.offer.url, quote=True)}" style="color:{NAVY}">{link}</a></td></tr>'
            )
        more = f'<p style="margin:10px 0 0;font:13px {BODY_FONT};color:{MUTED}">Mais {hidden} oferta(s) na loja.</p>' if hidden > 0 else ""
        others_html = (
            f'<tr><td style="padding:0 24px 20px"><p style="margin:0 0 6px;font:600 15px {HEAD_FONT};color:{NAVY}">'
            f"Outras ofertas desta consulta ({basis_word})</p>"
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">{body}</table>{more}</td></tr>'
        )
    delta_html = f' <span style="color:{GOOD}">{escape(delta)}</span>' if delta else ""
    preheader = f"{value_text} {basis_word}, {_wear_text(offer)}, float {_float_text(offer)}, {market.label}"
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:{PAGE}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{PAGE}" style="background:{PAGE}"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="width:100%;max-width:560px;background:#FFFFFF;border-radius:6px;overflow:hidden">
<tr><td bgcolor="{NAVY}" style="background:{NAVY};padding:18px 24px 20px">
<div style="font:14px {BODY_FONT};color:#C7D5E0">{escape(reason)}</div>
<div style="font:600 24px/1.25 {HEAD_FONT};color:#FFFFFF;margin-top:6px">{escape(title)}</div>
</td></tr>
<tr><td style="padding:22px 24px 0">
<div style="font:700 36px/1.1 {HEAD_FONT};color:{NAVY}">{escape(value_text)}</div>
<div style="font:14px {BODY_FONT};color:{MUTED};margin-top:6px">{escape(basis_long.capitalize())}.{delta_html}</div>
</td></tr>
{bar}
<tr><td style="padding:20px 24px 22px">
<a href="{escape(offer.url, quote=True)}" style="display:inline-block;background:{BUY_GREEN};color:#FFFFFF;text-decoration:none;font:600 16px {HEAD_FONT};padding:12px 26px;border-radius:4px">{button}</a>
</td></tr>
{warn_html}
<tr><td style="padding:0 24px 20px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-bottom:1px solid {RULE}">{"".join(rows)}</table>
</td></tr>
{others_html}
<tr><td style="padding:14px 24px 18px;background:#F6F8FA;font:12px {BODY_FONT};color:{MUTED}">
Monitor de skins de CS2. Loja consultada em {escape(when)}, horário de Brasília. Preço e disponibilidade podem mudar antes de você abrir o link.
</td></tr>
</table>
</td></tr></table>
</body></html>
"""
    return subject, text, html


def mask_address(text: str) -> str:
    """Esconde a parte local dos e-mails ("f***@gmail.com"): o destino vai para o banco, que fica no GitHub."""
    return re.sub(r"([A-Za-z0-9])[A-Za-z0-9._%+-]*@", lambda m: m.group(1) + "***@", text)


def delivery_text(dest: str) -> str:
    """Descreve o destino devolvido por Mailer.send, sem dizer "enviado" quando só houve gravação em arquivo."""
    if dest.startswith("arquivo "):
        return "gravado em " + dest[len("arquivo "):] + " (SMTP não configurado)"
    return "enviado para " + dest


def render_notice(title: str, paragraphs: list):
    """E-mail simples de aviso (falha de loja, por exemplo)."""
    text = title + "\n\n" + "\n\n".join(paragraphs) + "\n"
    body = "".join(f'<p style="margin:0 0 12px;font:15px/1.5 {BODY_FONT};color:{INK}">{escape(p)}</p>' for p in paragraphs)
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>{escape(title)}</title></head>
<body style="margin:0;padding:24px 12px;background:{PAGE}">
<table role="presentation" width="560" align="center" cellpadding="0" cellspacing="0" style="width:100%;max-width:560px;background:#FFFFFF;border-radius:6px;overflow:hidden">
<tr><td bgcolor="{NAVY}" style="background:{NAVY};padding:16px 24px;font:600 20px {HEAD_FONT};color:#FFFFFF">{escape(title)}</td></tr>
<tr><td style="padding:20px 24px 10px">{body}</td></tr>
</table></body></html>
"""
    return title, text, html


def render_sample(now: float):
    """E-mail de teste com o mesmo formato de um alerta real, usando valores de exemplo."""
    alert = Alert(id=0, name="★ Skeleton Knife | Slaughter", max_price=1700.0)
    market = MarketInfo(id="dashskins_br", label="DashSkins.com.br", currency="BRL", pay_kind="dinheiro", pay_note="PIX")
    offer = Offer(
        source="dashskins_br", offer_id="exemplo", name="★ Skeleton Knife | Slaughter (Minimal Wear)", price=1650.0, currency="BRL",
        url="https://dashskins.com.br/?search=skeleton%20knife%20slaughter", float_value=0.1205,
        note="Este é um e-mail de teste com valores de exemplo. O botão abre a busca da loja.",
    )
    cost = estimate(offer.price, offer.currency, MarketFees(fee_pct=0.0), CostSettings(), {})
    subject, text, html = render_alert(alert, market, [AlertItem(offer=offer, cost=cost)], now)
    return "[Teste] " + subject, text, html


class Mailer:
    """Envia por SMTP. Sem SMTP configurado, grava o e-mail em arquivo para conferência."""

    def __init__(self, host="", port=587, user="", password="", sender="", to="", outbox="data/outbox"):
        self.host, self.port, self.user, self.password = host, int(port or 587), user, password
        self.sender = sender or user
        self.to = to or user
        self.outbox = outbox
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, env, data_dir):
        return cls(
            host=env.get("SMTP_HOST", ""), port=env.get("SMTP_PORT", "587"), user=env.get("SMTP_USER", ""),
            password=env.get("SMTP_PASS", ""), sender=env.get("MAIL_FROM", ""), to=env.get("MAIL_TO", ""),
            outbox=os.path.join(data_dir, "outbox"),
        )

    @property
    def configured(self) -> bool:
        return bool(self.host and self.to)

    def describe(self) -> str:
        if self.configured:
            return f"SMTP {self.host}:{self.port} para {self.to}"
        return f"sem SMTP configurado: e-mails gravados em {self.outbox}"

    def send(self, subject: str, text: str, html: str) -> str:
        with self._lock:
            if not self.configured:
                return self._write(subject, html)
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self.sender
            msg["To"] = self.to
            msg["Date"] = formatdate(localtime=True)
            msg["Message-ID"] = make_msgid(domain="skinmon.local")
            msg.set_content(text)
            msg.add_alternative(html, subtype="html")
            context = ssl.create_default_context()
            if self.port == 465:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=30, context=context)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=30)
            try:
                if self.port != 465:
                    server.starttls(context=context)
                if self.user:
                    server.login(self.user, self.password)
                server.send_message(msg)
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
            return mask_address(self.to)

    def _write(self, subject: str, html: str) -> str:
        os.makedirs(self.outbox, exist_ok=True)
        stamp = datetime.fromtimestamp(time.time(), BRASILIA).strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", names.slug_text(subject))[:60].strip("-") or "email"
        path = os.path.join(self.outbox, f"{stamp}-{slug}.html")
        n = 1
        while os.path.exists(path):
            n += 1
            path = os.path.join(self.outbox, f"{stamp}-{slug}-{n}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return "arquivo " + path
