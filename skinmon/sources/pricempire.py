"""CS.MONEY Market através da Pricempire (agregador com API oficial).

A API do próprio CS.MONEY recusa clientes automáticos (HTTP 403, código 4030). A Pricempire acompanha a
loja e vende o dado por API; o plano Trader é gratuito, com 1.000 chamadas por mês e "acesso limitado"
à API de preços. Cada chamada traz o menor preço de todos os itens, então uma chamada a cada 45 min
cabe na cota. Formato segundo a documentação pública (pricempire.com/docs); sem a sua chave não foi
possível validar com dados reais, nem confirmar se o plano gratuito inclui a fonte csmoney."""
from __future__ import annotations

from datetime import datetime

from .. import names, net
from ..models import Offer
from .base import PollResult, Source

API = "https://api.pricempire.com/v4/paid/items/prices"
PROVIDER = "csmoney"


def search_url(name: str) -> str:
    return "https://cs.money/market/buy/?" + net.query({"search": names.parse(name).base, "sort": "price", "order": "asc"})


def _timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def parse(payload, alert_names) -> list:
    keys = {names.key(n) for n in alert_names}
    offers = []
    for row in payload or []:
        name = row.get("market_hash_name")
        if not name or names.key(name) not in keys:
            continue
        for price in row.get("prices") or []:
            cents = price.get("price")
            if price.get("provider_key") != PROVIDER or not isinstance(cents, (int, float)) or cents <= 0:
                continue
            offers.append(Offer(
                source="csmoney", offer_id="min:" + name, name=name, price=round(cents / 100.0, 2), currency="USD",
                url=search_url(name), link_kind="search", aggregated=True, quantity=price.get("count"),
                data_time=_timestamp(price.get("updated_at")),
                note="Menor preço do CS.MONEY segundo a Pricempire. A página do CS.MONEY mostra o preço em reais.",
            ))
    return offers


class PricempireCsmoney(Source):
    id = "csmoney"
    label = "CS.MONEY (via Pricempire)"
    currency = "USD"
    pay_note = "o site cobra em reais; total estimado pelo câmbio"
    link_kind = "search"
    interval = 2700  # 45 min: ~960 chamadas por mês, dentro das 1.000 do plano gratuito
    timeout = 60
    key_env = "PRICEMPIRE_API_KEY"
    default_fee_pct = None
    validated = "não validado: exige a sua chave da Pricempire"
    data_note = "Menor preço por item via API da Pricempire (precisa de PRICEMPIRE_API_KEY). Consulta a cada 45 min."

    def poll(self, alerts, ctx) -> PollResult:
        key = self.key()
        if not key:
            ctx.notes.append("sem chave: cadastre o segredo PRICEMPIRE_API_KEY para acompanhar o CS.MONEY")
            return PollResult(offers={a.id: [] for a in alerts})
        params = {"app_id": 730, "sources": PROVIDER}
        payload = self.fetch(API + "?" + net.query(params), headers={"Authorization": "Bearer " + key}, timeout=self.timeout).json()
        if isinstance(payload, dict):  # erro da API (chave inválida, plano sem acesso etc.)
            raise net.HttpError(200, API, str(payload.get("message") or payload.get("error") or payload)[:160])
        offers = parse(payload, [a.name for a in alerts])
        return PollResult(offers={a.id: offers for a in alerts})
