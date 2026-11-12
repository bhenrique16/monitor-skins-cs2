"""Waxpeer: endpoint público de preços, menor preço por item em dólar (sem anúncio individual)."""
from __future__ import annotations

from .. import names, net
from ..models import Offer
from .base import Source

API = "https://api.waxpeer.com/v1/prices"


def search_url(name: str) -> str:
    return "https://waxpeer.com/?" + net.query({"game": "csgo", "sort": "ASC", "order": "price", "search": name})


def parse(payload: dict) -> list:
    offers = []
    for row in (payload or {}).get("items") or []:
        name, thousandths, count = row.get("name"), row.get("min"), row.get("count") or 0
        if not name or not isinstance(thousandths, (int, float)) or thousandths <= 0 or count <= 0:
            continue
        offers.append(Offer(
            source="waxpeer", offer_id="min:" + name, name=name, price=round(thousandths / 1000.0, 2), currency="USD",
            url=search_url(name), link_kind="search", aggregated=True, quantity=int(count),
        ))
    return offers


class Waxpeer(Source):
    id = "waxpeer"
    label = "Waxpeer"
    currency = "USD"
    pay_note = "cartão internacional ou cripto"
    link_kind = "search"
    interval = 120
    default_fee_pct = None
    data_note = "Endpoint público de preços (menor preço por item, sem cache)."

    def search(self, alert, ctx):
        params = {"game": "csgo", "minified": 0, "search": names.plain_base(alert.name)}
        payload = self.fetch(API + "?" + net.query(params), timeout=self.timeout).json()
        if payload.get("success") is False:
            raise net.HttpError(200, API, str(payload.get("msg") or "consulta recusada"))
        return parse(payload)
