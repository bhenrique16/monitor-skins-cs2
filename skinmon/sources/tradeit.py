"""Tradeit.gg: inventário público do site. Dois modos sobre os mesmos itens:
loja (preço em dinheiro) e troca (valor de troca, pago com itens)."""
from __future__ import annotations

from .. import names, net
from ..models import Offer
from .base import Source

API = "https://tradeit.gg/api/v2/inventory/data"


def parse(payload: dict, mode: str) -> list:
    source = "tradeit" if mode == "store" else "tradeit_troca"
    page = "store" if mode == "store" else "trade"
    offers = []
    for row in (payload or {}).get("items") or []:
        name = row.get("name")
        cents = row.get("storePrice") if mode == "store" else row.get("price")
        if not name or not isinstance(cents, (int, float)) or cents <= 0:
            continue
        offer_id = row.get("assetId") or (f"g{row['groupId']}" if row.get("groupId") else None)
        if not offer_id:
            continue
        float_value = row.get("floatValue")
        offers.append(Offer(
            source=source, offer_id=str(offer_id), name=name, price=round(cents / 100.0, 2), currency="USD",
            url=f"https://tradeit.gg/csgo/{page}?" + net.query({"search": name}), link_kind="search",
            float_value=float(float_value) if isinstance(float_value, (int, float)) else None,
        ))
    return offers


class Tradeit(Source):
    id = "tradeit"
    label = "Tradeit.gg (loja)"
    mode = "store"
    currency = "USD"
    pay_note = "cartão internacional ou cripto"
    link_kind = "search"
    interval = 120
    timeout = 60  # a origem costuma demorar quando o cache expira
    default_fee_pct = None
    data_note = "Inventário público do site (itens dos bots, preço de loja). Cache de 60 s."

    def search(self, alert, ctx):
        params = {"gameId": 730, "offset": 0, "limit": 60, "sortType": "Price - low",
                  "searchValue": names.search_text(alert.name), "fresh": "true"}
        return parse(self.fetch(API + "?" + net.query(params), timeout=self.timeout).json(), self.mode)


class TradeitTroca(Tradeit):
    id = "tradeit_troca"
    label = "Tradeit.gg (troca)"
    mode = "trade"
    pay_kind = "troca"
    pay_note = "paga com itens do seu inventário"
    default_enabled = False
    default_fee_pct = 0.0
    data_note = "Mesmo inventário público, com o valor de troca. Não há valor em dinheiro: total sempre incompleto."
