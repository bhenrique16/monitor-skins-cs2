"""NeshaStore: API pública do próprio site, anúncios individuais em reais (preço no PIX)."""
from __future__ import annotations

import math
import time
from datetime import datetime

from .. import names, net
from ..models import Offer
from .base import Source

API = "https://api.neshastore.com/items"
SITE = "https://neshastore.com"
# Tipo do item na loja -> seção do endereço, copiado da tabela do próprio site (12/11/2026).
_SECTIONS = {
    "facas": (21, 23, 24, 25, 26, 27, 28, 29, 30, 31, 56, 57, 58, 60, 69, 70, 71, 72, 74, 75),
    "luvas": (32, 53, 61, 62, 63, 64, 65, 73),
    "outros": (33, 34, 35, 36, 38, 51, 52, 54, 66, 67, 68, 77, 78),
    "pesadas": (40, 41, 44, 47, 49, 50),
    "pistolas": (6, 7, 8, 9, 10, 11, 12, 13, 39, 42, 76),
    "rifles": (1, 2, 3, 4, 14, 15, 20, 43, 45, 46, 48),
    "smg": (5, 16, 17, 18, 19, 37, 55),
}
_SECTION_BY_TYPE = {t: section for section, types in _SECTIONS.items() for t in types}
_PREFIX = {3: "stattrak-", 4: "lembranca-"}  # categoria 3 = StatTrak, 4 = Souvenir


def _lock_note(expiration, now):
    if not expiration:
        return ""
    try:
        when = datetime.fromisoformat(str(expiration).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return ""
    if when <= now:
        return ""
    from ..mailer import brasilia_time  # import tardio: mailer não depende das lojas

    return f"Item com bloqueio de troca até {brasilia_time(when)[:16]} (horário de Brasília); a entrega acontece depois disso."


def parse(payload: dict, now: float) -> list:
    offers = []
    for row in (payload or {}).get("items") or []:
        name, item_id = row.get("marketHashName"), row.get("id")
        try:
            price = float(row.get("price"))
        except (TypeError, ValueError):
            continue
        if not name or not item_id or price <= 0:
            continue
        try:
            float_value = float(row.get("float"))
        except (TypeError, ValueError):
            float_value = None
        section = _SECTION_BY_TYPE.get(row.get("type"))
        slug_type, slug = row.get("slugType"), row.get("slug")
        if section and slug_type and slug:
            prefix = _PREFIX.get(row.get("category"), "")
            url, link_kind = f"{SITE}/csgo/{section}/{slug_type}/{prefix}{slug}?itemId={item_id}", "offer"
        else:
            url, link_kind = f"{SITE}/", "search"
        offers.append(Offer(
            source="neshastore", offer_id=str(item_id), name=name, price=price, currency="BRL", url=url,
            link_kind=link_kind, float_value=float_value, note=_lock_note(row.get("tradelockExpiration"), now),
        ))
    return offers


class Neshastore(Source):
    id = "neshastore"
    label = "NeshaStore"
    pay_note = "PIX (cartão custa mais)"
    interval = 60
    data_note = "API pública do site (anúncios individuais, preço no PIX). Sem cache; consulta a cada 60 s."

    def search(self, alert, ctx):
        params = [
            ("orderBy[]", 1),  # menor preço primeiro
            ("tradeLocked", "true"),  # mesmo filtro padrão do site: inclui itens com bloqueio de troca
            ("limit", 48),
            ("page", 1),
            ("query", names.search_text(alert.name)),
            ("priceTo", math.ceil(alert.max_price * 1.3)),
        ]
        payload = self.fetch(API + "?" + net.query(params), timeout=self.timeout).json()
        if (payload.get("meta") or {}).get("hasNext"):
            ctx.notes.append(f"{alert.name}: mais de 48 anúncios abaixo do teto; só a primeira página foi lida")
        return parse(payload, now=time.time())
