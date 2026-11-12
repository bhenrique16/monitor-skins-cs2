"""Mercado da Comunidade Steam: menor preço por item, pago com saldo Steam.

Uma busca lista todas as variações da skin com preço em dólar. Só as variações que podem caber no
teto recebem a consulta de preço exato em reais, para ficar bem abaixo do limite de requisições."""
from __future__ import annotations

import re
import urllib.parse

from .. import names, net
from ..models import Offer
from .base import Source

SEARCH = "https://steamcommunity.com/market/search/render/"
OVERVIEW = "https://steamcommunity.com/market/priceoverview/"
LISTINGS = "https://steamcommunity.com/market/listings/730/"
NEAR_FACTOR = 1.25  # margem sobre o teto para pedir o preço exato em reais


def parse_search(payload) -> list:
    """Devolve [(nome, preço em dólar, quantidade de anúncios)]."""
    rows = []
    for row in (payload or {}).get("results") or []:
        name, cents = row.get("hash_name"), row.get("sell_price")
        if name and isinstance(cents, (int, float)):
            rows.append((name, round(cents / 100.0, 2), int(row.get("sell_listings") or 0)))
    return rows


def parse_brl(text):
    if not text:
        return None
    digits = re.sub(r"[^0-9,]", "", str(text)).replace(",", ".")
    try:
        return round(float(digits), 2)
    except ValueError:
        return None


def listing_url(name: str) -> str:
    return LISTINGS + urllib.parse.quote(name, safe="")


def offer_from_overview(name: str, payload):
    price = parse_brl((payload or {}).get("lowest_price"))
    if price is None:
        return None
    return Offer(source="steam", offer_id="min:" + name, name=name, price=price, currency="BRL",
                 url=listing_url(name), link_kind="search", aggregated=True)


class Steam(Source):
    id = "steam"
    label = "Steam"
    pay_kind = "saldo_steam"
    pay_note = "carteira Steam, taxas já inclusas"
    link_kind = "search"
    interval = 180
    pause = 4
    data_note = "Endpoints públicos do Mercado da Comunidade (menor preço por item, em reais). Limite rígido: consulta espaçada."

    def search(self, alert, ctx):
        params = {"query": names.search_text(alert.name), "appid": 730, "norender": 1, "count": 50, "start": 0}
        rows = parse_search(self.fetch(SEARCH + "?" + net.query(params), timeout=self.timeout).json())
        usd = ctx.fx.get("USD")
        offers, cheapest_far = [], None
        for name, usd_price, listings in rows:
            if listings <= 0 or not names.same_skin(alert.name, name):
                continue
            approx = usd_price * usd if usd else None
            if approx is not None and approx > alert.max_price * NEAR_FACTOR:
                cheapest_far = approx if cheapest_far is None else min(cheapest_far, approx)
                continue
            self.sleep(self.pause)
            overview = self.fetch(OVERVIEW + "?" + net.query(
                {"country": "BR", "currency": 7, "appid": 730, "market_hash_name": name}), timeout=self.timeout).json()
            offer = offer_from_overview(name, overview)
            if offer:
                offer.quantity = listings
                offers.append(offer)
        if cheapest_far is not None and not offers:
            text = f"{cheapest_far:,.0f}".replace(",", ".")
            ctx.notes.append(f"{alert.name}: menor preço ≈ R$ {text}, longe do teto (preço exato não consultado)")
        return offers
