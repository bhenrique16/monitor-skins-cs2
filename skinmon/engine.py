"""Regra de alerta: filtra as ofertas, calcula o custo, decide se avisa e evita repetição."""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import names
from .mailer import AlertItem, render_alert
from .pricing import estimate

# Uma queda só gera novo aviso se for de pelo menos 1% sobre o último preço avisado.
RENOTIFY_FACTOR = 0.99
REFRESH_SEEN_AFTER = 3600  # segundos até regravar um anúncio que não mudou


@dataclass(frozen=True)
class Seen:
    last_price: float
    notified_price: float | None


@dataclass(frozen=True)
class Decision:
    notify: bool
    reason: str = ""  # "novo", "baixou" ou "entrou"
    previous_price: float | None = None
    notified_price: float | None = None  # valor a guardar como "último preço avisado"


@dataclass
class Result:
    matched: int = 0
    eligible: int = 0
    notified: int = 0
    emails: int = 0
    held: int = 0  # avisos segurados pelo limite de e-mails por hora
    best_brl: float | None = None
    best_name: str | None = None
    error: str | None = None


def matches_filters(alert, offer) -> bool:
    if not names.same_skin(alert.name, offer.name):
        return False
    parsed = names.parse(offer.name)
    if alert.stattrak == "only" and not parsed.stattrak:
        return False
    if alert.stattrak == "exclude" and parsed.stattrak:
        return False
    if alert.wears:
        wear = parsed.wear
        if wear is None and offer.float_value is not None:
            wear = names.wear_from_float(offer.float_value)
        if wear not in alert.wears:
            return False
    return True


def basis_value(alert, cost):
    return cost.listed_brl if alert.basis == "listed" else cost.total_brl


def is_eligible(alert, cost) -> bool:
    value = basis_value(alert, cost)
    if value is None:
        return False
    if alert.basis != "listed" and not cost.complete and not alert.include_incomplete:
        return False
    return value <= alert.max_price + 1e-9


def decide(prev: Seen | None, price: float, eligible: bool) -> Decision:
    """Decide o aviso comparando o preço atual (na moeda da loja) com o que já foi visto e avisado."""
    if prev is None:
        return Decision(True, "novo", None, price) if eligible else Decision(False)
    notified = prev.notified_price
    if not eligible:
        # O vendedor subiu o preço para fora do filtro: rearma. Oscilação de câmbio não rearma.
        if notified is not None and price > notified:
            notified = None
        return Decision(False, notified_price=notified)
    if notified is None:
        if price < prev.last_price:
            return Decision(True, "baixou", prev.last_price, price)
        return Decision(True, "entrou", None, price)
    if price <= notified * RENOTIFY_FACTOR:
        return Decision(True, "baixou", notified, price)
    if price > notified:
        return Decision(False, notified_price=price)
    return Decision(False, notified_price=notified)


class Engine:
    def __init__(self, db, send, now=time.time, max_per_hour=30):
        self.db = db
        self.send = send
        self.now = now
        self.max_per_hour = max_per_hour

    def process(self, market, alert, offers, fees, settings, fx) -> Result:
        now = self.now()
        res = Result()
        pending = []
        for offer in offers:
            if not matches_filters(alert, offer):
                continue
            res.matched += 1
            cost = estimate(offer.price, offer.currency, fees, settings, fx)
            value = basis_value(alert, cost)
            if value is not None and (res.best_brl is None or value < res.best_brl):
                res.best_brl, res.best_name = value, offer.name
            eligible = is_eligible(alert, cost)
            res.eligible += eligible
            row = self.db.get_seen(alert.id, market.id, offer.offer_id)
            prev = Seen(row["last_price"], row["notified_price"]) if row else None
            decision = decide(prev, offer.price, eligible)
            if decision.notify:
                # O estado só é gravado depois do envio: se o e-mail falhar, a próxima consulta tenta de novo.
                pending.append((value, offer, cost, decision))
            elif (row is None or row["last_price"] != offer.price or row["notified_price"] != decision.notified_price
                  or now - row["last_seen"] >= REFRESH_SEEN_AFTER):
                # Sem mudança, nada é regravado a cada consulta; só um refresco por hora para a limpeza de antigos.
                self.db.save_seen(alert.id, market.id, offer, now, decision.notified_price)

        if not pending:
            return res
        if self.db.count_sent_since(now - 3600) >= self.max_per_hour:
            res.held = len(pending)
            res.error = f"limite de {self.max_per_hour} e-mails por hora atingido; {len(pending)} aviso(s) aguardando"
            return res

        pending.sort(key=lambda p: (p[0] is None, p[0] or 0.0))
        items = [AlertItem(offer=o, cost=c, reason=d.reason, previous_price=d.previous_price) for _, o, c, d in pending]
        subject, text, html = render_alert(alert, market, items, now)
        if self.db.get("assunto_teste") == "1":
            subject = "[TESTE] " + subject
        try:
            dest = self.send(subject, text, html)
        except Exception as exc:  # a loja segue sendo consultada; o aviso fica pendente
            res.error = f"falha ao enviar e-mail: {exc}"
            return res
        for _, offer, _, decision in pending:
            self.db.save_seen(alert.id, market.id, offer, now, decision.notified_price, notified_at=now)
        self.db.log_sent(now, alert.id, market.id, subject, len(items), dest)
        res.emails = 1
        res.notified = len(items)
        return res
