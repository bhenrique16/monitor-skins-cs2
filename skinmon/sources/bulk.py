"""Lojas que publicam um arquivo único com o menor preço de todos os itens.

Um download serve todos os alertas. O arquivo tem alguns MB, então a consulta é espaçada e usa
ETag quando a loja oferece (sem mudança, nada é baixado de novo)."""
from __future__ import annotations

from .. import names, net
from ..models import Offer
from .base import PollResult, Source


class BulkSource(Source):
    url = ""
    link_kind = "search"
    interval = 300
    timeout = 90
    default_fee_pct = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._etag = None
        self._keys = None  # skins a que a lista guardada se refere
        self._kept = None  # só as ofertas das skins monitoradas ficam em memória

    def parse(self, payload, alert_names) -> list:
        raise NotImplementedError

    def poll(self, alerts, ctx) -> PollResult:
        keys = frozenset(names.key(a.name) for a in alerts)
        reusable = self._kept is not None and keys == self._keys
        resp = self.fetch(self.url, timeout=self.timeout, etag=self._etag if reusable else None)
        if resp.status != 304:
            self._kept = self.parse(resp.json(), [a.name for a in alerts])
            self._etag, self._keys = resp.header("etag"), keys
        # O motor filtra por alerta; todos recebem a mesma lista já reduzida às skins monitoradas.
        return PollResult(offers={a.id: self._kept for a in alerts})


def lis_parse(payload, alert_names) -> list:
    keys = {names.key(n) for n in alert_names}
    rows = payload if isinstance(payload, list) else (payload or {}).get("items") or []
    offers = []
    for row in rows:
        name, price = row.get("name"), row.get("price")
        if not name or not isinstance(price, (int, float)) or price <= 0 or names.key(name) not in keys:
            continue
        offers.append(Offer(
            source="lisskins", offer_id="min:" + name, name=name, price=round(float(price), 2), currency="USD",
            url=row.get("url") or "https://lis-skins.com/market/csgo/", link_kind="search", aggregated=True,
            quantity=row.get("count"),
        ))
    return offers


def tm_parse(payload, alert_names) -> list:
    keys = {names.key(n) for n in alert_names}
    currency = (payload or {}).get("currency") or "USD"
    data_time = (payload or {}).get("time")
    data_time = float(data_time) if isinstance(data_time, (int, float)) else None
    offers = []
    for row in (payload or {}).get("items") or []:
        name = row.get("market_hash_name")
        if not name or names.key(name) not in keys:
            continue
        try:
            price = float(row.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        volume = row.get("volume")
        offers.append(Offer(
            source="marketcsgo", offer_id="min:" + name, name=name, price=round(price, 2), currency=currency,
            url="https://market.csgo.com/en/?" + net.query({"search": name}), link_kind="search", aggregated=True,
            quantity=int(volume) if isinstance(volume, (int, float)) else None, data_time=data_time,
        ))
    return offers
