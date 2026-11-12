"""BUFF.market (versão internacional da BUFF): dados públicos por item, sem login.

A busca por nome exige conta, mas duas consultas por item são abertas:
- goods/info pelo nome exato: id do item, menor preço e quantidade de anúncios;
- goods/sell_order pelo id: os 10 anúncios mais baratos, com float.
O monitor monta os nomes exatos de cada variação (desgaste e StatTrak) a partir do alerta."""
from __future__ import annotations

import urllib.parse

from .. import names, net
from ..models import Offer
from .base import Source

INFO = "https://api.buff.market/api/market/goods/info"
ORDERS = "https://api.buff.market/api/market/goods/sell_order"
PAGE = "https://buff.market/market/goods/cs2/"
NEAR_FACTOR = 1.3  # variações até 30% acima do teto têm os anúncios individuais consultados


def item_url(name: str) -> str:
    return PAGE + urllib.parse.quote(name, safe="")


def candidate_names(alert) -> list:
    base = names.parse(alert.name).base
    if base.startswith("★ "):
        stattrak_name = "★ StatTrak™ " + base[2:]
    else:
        stattrak_name = "StatTrak™ " + base
    variants = {"any": [base, stattrak_name], "only": [stattrak_name], "exclude": [base]}[alert.stattrak]
    wears = alert.wears or tuple(names.WEAR_NAMES)
    return [f"{variant} ({names.WEAR_NAMES[wear]})" for wear in wears for variant in variants]


def parse_info(payload):
    """(id do item, menor preço em US$, quantidade) ou None quando a variação não existe."""
    data = (payload or {}).get("data") if (payload or {}).get("code") == "OK" else None
    if not data or not data.get("id"):
        return None
    try:
        price = float(data.get("sell_min_price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    return int(data["id"]), price, int(data.get("sell_num") or 0)


def parse_orders(payload, name: str) -> list:
    data = (payload or {}).get("data") if (payload or {}).get("code") == "OK" else None
    offers = []
    for row in (data or {}).get("items") or []:
        try:
            price = float(row.get("price"))
        except (TypeError, ValueError):
            continue
        if not row.get("id") or price <= 0:
            continue
        try:
            float_value = float((row.get("asset_info") or {}).get("paintwear"))
        except (TypeError, ValueError):
            float_value = None
        offers.append(Offer(
            source="buffmarket", offer_id=str(row["id"]), name=name, price=price, currency="USD", url=item_url(name),
            link_kind="search", float_value=float_value,
            note="O link abre a página do item na BUFF.market, com os anúncios do mais barato para o mais caro.",
        ))
    return offers


class Buffmarket(Source):
    id = "buffmarket"
    label = "BUFF.market"
    currency = "USD"
    pay_note = "cartão internacional ou cripto"
    link_kind = "search"
    interval = 120
    pause = 1.0
    default_fee_pct = None
    data_note = "Dados públicos por item (menor preço e 10 anúncios mais baratos com float). A busca por nome exige conta."

    def _get(self, url, params):
        payload = self.fetch(url + "?" + net.query(params), timeout=self.timeout).json()
        if payload.get("code") == "Login Required":
            raise net.HttpError(200, url, "a loja passou a exigir login para esta consulta")
        return payload

    def search(self, alert, ctx):
        usd = ctx.fx.get("USD")
        offers = []
        for index, name in enumerate(candidate_names(alert)):
            if index:
                self.sleep(self.pause)
            info = parse_info(self._get(INFO, {"game": "csgo", "market_hash_name": name}))
            if info is None:
                continue  # variação que não existe (ex.: desgaste fora da faixa da skin)
            goods_id, minimum, count = info
            if count <= 0 or minimum <= 0:
                continue
            if usd and minimum * usd > alert.max_price * NEAR_FACTOR:
                offers.append(Offer(
                    source="buffmarket", offer_id="min:" + name, name=name, price=minimum, currency="USD",
                    url=item_url(name), link_kind="search", aggregated=True, quantity=count,
                ))
                continue
            self.sleep(self.pause)
            offers += parse_orders(self._get(ORDERS, {"game": "csgo", "goods_id": goods_id, "page_num": 1}), name)
        return offers
