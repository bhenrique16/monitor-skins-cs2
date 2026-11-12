"""BRSKINS (brskins.gg): API pública do próprio site, anúncios individuais em reais."""
from __future__ import annotations

import math

from .. import names, net
from ..models import Offer
from .base import Source

API = "https://brskins.gg/api/marketdata/get-market-offers"


def parse(payload: dict) -> list:
    offers = []
    for row in payload.get("offers") or []:
        product = row.get("product") or {}
        name, offer_id, price = product.get("productCode"), row.get("id"), row.get("price")
        if not name or not offer_id or not isinstance(price, (int, float)):
            continue
        float_value = row.get("float")
        offers.append(Offer(
            source="brskins", offer_id=str(offer_id), name=name, price=float(price),
            currency=row.get("currencyIsoCode") or "BRL",
            url=f"https://brskins.gg/market/item/{offer_id}",
            float_value=float(float_value) if isinstance(float_value, (int, float)) else None,
            note="Entrega manual pelo vendedor." if row.get("deliveryType") == "Manual" else "",
        ))
    return offers


class Brskins(Source):
    id = "brskins"
    label = "BRSKINS"
    pay_note = "PIX"
    interval = 60
    data_note = "API pública do site (anúncios individuais, inclui estoque de parceiros). Cache de 60 s."

    def search(self, alert, ctx):
        # Sem ordenação por preço documentada: o teto de preço na consulta mantém a resposta pequena e completa.
        params = {"name": names.search_text(alert.name).lower(), "price_to": math.ceil(alert.max_price * 1.3), "language": "pt-BR"}
        payload = self.fetch(API + "?" + net.query(params), timeout=self.timeout).json()
        if payload.get("success") is False:
            raise net.HttpError(200, API, "; ".join(str(e) for e in payload.get("errors") or []) or "consulta recusada")
        if payload.get("hasMore"):
            ctx.notes.append(f"{alert.name}: há mais anúncios além da primeira página")
        return parse(payload)
