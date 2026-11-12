"""DashSkins.gg (P2P): API pública do próprio site, anúncios individuais em reais."""
from __future__ import annotations

import math

from .. import names, net
from ..models import Offer
from .base import Source

API = "https://api.dashskins.gg/v1/item"
PAGE_SIZE = 50


def parse(payload: dict) -> list:
    offers = []
    for row in payload.get("page") or []:
        name, listing_id, price = row.get("marketHashName"), row.get("id"), row.get("priceBRL")
        if not name or not listing_id or not isinstance(price, (int, float)):
            continue
        float_value = row.get("float")
        offers.append(Offer(
            source="dashskins_gg", offer_id=str(listing_id), name=name, price=float(price), currency="BRL",
            url=f"https://dashskins.gg/item/{listing_id}",
            float_value=float(float_value) if isinstance(float_value, (int, float)) else None,
        ))
    return offers


class DashskinsGg(Source):
    id = "dashskins_gg"
    label = "DashSkins.gg"
    pay_note = "PIX"
    interval = 60
    data_note = "API pública do site (anúncios individuais, P2P). Sem cache; limite de 10/50/200 requisições por janela."

    def _page(self, alert, max_price: float) -> dict:
        params = {"pageSize": PAGE_SIZE, "partialMarketHashName": names.plain_base(alert.name), "maxPriceBRL": math.ceil(max_price)}
        return self.fetch(API + "?" + net.query(params), timeout=self.timeout).json()

    def search(self, alert, ctx):
        # A API não ordena por preço. Limitar o preço máximo garante que os baratos caibam em uma página.
        payload = self._page(alert, alert.max_price * 1.3)
        total = payload.get("totalItems") or 0
        if total > len(payload.get("page") or []):
            self.sleep(self.pause)
            payload = self._page(alert, alert.max_price)
            if (payload.get("totalItems") or 0) > len(payload.get("page") or []):
                ctx.notes.append(f"{alert.name}: mais de {PAGE_SIZE} anúncios abaixo do teto; só parte foi lida")
        return parse(payload)
