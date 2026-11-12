"""CSFloat.

Sem chave: só a lista pública de menor preço por item (referência, renovada cerca de 1 vez por hora).
Com chave (CSFLOAT_API_KEY): anúncios individuais de compra imediata, consultados a cada minuto.
O caminho com chave segue a documentação pública e NÃO foi testado com dados reais (exige a sua chave)."""
from __future__ import annotations

import time

from .. import names, net
from ..models import Offer
from .base import PollResult, Source

PRICE_LIST = "https://csfloat.com/api/v1/listings/price-list"
LISTINGS = "https://csfloat.com/api/v1/listings"
PRICE_LIST_TTL = 600


def search_url(name: str) -> str:
    return "https://csfloat.com/search?" + net.query({"market_hash_name": name, "sort_by": "lowest_price", "type": "buy_now"})


def parse_price_list(payload, alert_names, data_time=None) -> list:
    keys = {names.key(n) for n in alert_names}
    offers = []
    for row in payload or []:
        name, cents = row.get("market_hash_name"), row.get("min_price")
        if not name or not isinstance(cents, (int, float)) or cents <= 0 or names.key(name) not in keys:
            continue
        offers.append(Offer(
            source="csfloat", offer_id="min:" + name, name=name, price=round(cents / 100.0, 2), currency="USD",
            url=search_url(name), link_kind="search", aggregated=True, quantity=row.get("quantity"),
            note="Preço de referência da lista pública da CSFloat, renovada cerca de 1 vez por hora. A busca exige login na CSFloat.",
            data_time=data_time,
        ))
    return offers


def parse_listings(payload) -> list:
    rows = payload.get("data") if isinstance(payload, dict) else payload
    offers = []
    for row in rows or []:
        item = row.get("item") or {}
        name, listing_id, cents = item.get("market_hash_name"), row.get("id"), row.get("price")
        if row.get("type", "buy_now") != "buy_now" or row.get("state", "listed") != "listed":
            continue
        if not name or not listing_id or not isinstance(cents, (int, float)):
            continue
        float_value = item.get("float_value")
        offers.append(Offer(
            source="csfloat", offer_id=str(listing_id), name=name, price=round(cents / 100.0, 2), currency="USD",
            url=f"https://csfloat.com/item/{listing_id}",
            float_value=float(float_value) if isinstance(float_value, (int, float)) else None,
        ))
    return offers


class Csfloat(Source):
    id = "csfloat"
    label = "CSFloat"
    currency = "USD"
    pay_note = "cartão internacional"
    key_env = "CSFLOAT_API_KEY"
    default_fee_pct = 2.8  # depósito por cartão, conforme divulgado pela CSFloat; confira em csfloat.com
    default_fee_fixed = 0.30
    pause = 1.0
    validated = "lista pública com dados reais; anúncios com chave não testados"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._refs = None  # ofertas de referência só das skins monitoradas
        self._refs_keys = None
        self._refs_at = 0.0

    @property
    def interval(self):
        return 60 if self.key() else 600

    @property
    def link_kind(self):
        return "offer" if self.key() else "search"

    @property
    def data_note(self):
        if self.key():
            return "API oficial com a sua chave (anúncios individuais de compra imediata)."
        return "Sem chave: lista pública de menor preço por item, renovada cerca de 1 vez por hora (referência)."

    def _references(self, alerts) -> list:
        """Menor preço por item das skins monitoradas. A lista completa (28 mil itens) não fica em memória."""
        keys = frozenset(names.key(a.name) for a in alerts)
        if self._refs is None or keys != self._refs_keys or time.time() - self._refs_at > PRICE_LIST_TTL:
            resp = self.fetch(PRICE_LIST, timeout=60)
            # A lista é servida de cache: a idade real vem do Last-Modified, não da hora da consulta.
            self._refs = parse_price_list(resp.json(), [a.name for a in alerts], net.parse_http_date(resp.header("last-modified")))
            self._refs_keys, self._refs_at = keys, time.time()
        return self._refs

    def poll(self, alerts, ctx) -> PollResult:
        result = PollResult()
        references = self._references(alerts)
        key = self.key()
        usd = ctx.fx.get("USD")
        for alert in alerts:
            reference = [o for o in references if names.same_skin(alert.name, o.name)]
            if not key:
                result.offers[alert.id] = reference
                continue
            found = []
            for ref in reference:
                self.sleep(self.pause)
                try:
                    params = {"market_hash_name": ref.name, "sort_by": "lowest_price", "type": "buy_now", "limit": 20}
                    if usd:
                        # O total com taxas nunca é menor que o preço anunciado: o teto em dólar limita a resposta.
                        params["max_price"] = int(alert.max_price / usd * 100)
                    resp = self.fetch(LISTINGS + "?" + net.query(params), headers={"Authorization": key}, timeout=self.timeout)
                    found += parse_listings(resp.json())
                    remaining = resp.header("x-ratelimit-remaining")
                    if remaining is not None and remaining.isdigit() and int(remaining) < 50:
                        result.rate_limited = 900.0
                        result.errors.append("cota da API quase no fim; pausando")
                except net.RateLimited as exc:
                    result.rate_limited = exc.retry_after or 900.0
                    result.errors.append(str(exc))
                except net.HttpError as exc:
                    hint = " (chave recusada?)" if exc.status in (401, 403) else ""
                    result.errors.append(f"{ref.name}: {exc}{hint}")
                if result.rate_limited:
                    break
            result.offers[alert.id] = found
            if result.rate_limited:
                break
        return result
