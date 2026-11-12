"""DashSkins.com.br: API pública do próprio site, anúncios individuais em reais."""
from __future__ import annotations

from .. import names, net
from ..models import Offer
from .base import Source

API = "https://dashskins.com.br/api/listing"


def _item_url(name: str, listing_id: str) -> str:
    wear = names.parse(name).wear
    slug = names.slugify(name)
    if wear:
        slug += "-" + names.slug_text(names.WEAR_NAMES[wear])
    return f"https://dashskins.com.br/item/{slug}/{listing_id}"


def parse(payload: dict) -> list:
    offers = []
    for row in payload.get("results") or []:
        name, listing_id, price = row.get("market_hash_name"), row.get("_id"), row.get("price")
        if not name or not listing_id or not isinstance(price, (int, float)):
            continue
        float_value = (row.get("wear_data") or {}).get("floatvalue")
        offers.append(Offer(
            source="dashskins_br", offer_id=str(listing_id), name=name, price=float(price), currency="BRL",
            url=_item_url(name, str(listing_id)),
            float_value=float(float_value) if isinstance(float_value, (int, float)) else None,
        ))
    return offers


class DashskinsBr(Source):
    id = "dashskins_br"
    label = "DashSkins.com.br"
    pay_note = "PIX"
    interval = 60
    data_note = "API pública do site (anúncios individuais). Resposta fica ~30 s em cache na borda."

    def search(self, alert, ctx):
        params = {"search": names.search_text(alert.name).lower(), "limit": 50, "sort_by": "price", "sort_dir": "asc"}
        return parse(self.fetch(API + "?" + net.query(params), timeout=self.timeout).json())
