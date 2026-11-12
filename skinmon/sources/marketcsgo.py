"""Market.CSGO (TM): lista pública de preços com o menor preço por item (dólar)."""
from __future__ import annotations

from .bulk import BulkSource, tm_parse

parse = tm_parse


class Marketcsgo(BulkSource):
    id = "marketcsgo"
    label = "Market.CSGO"
    currency = "USD"
    pay_note = "cartão internacional ou cripto"
    url = "https://market.csgo.com/api/v2/prices/USD.json"
    data_note = "Lista pública de preços (menor preço por item), regerada a cada minuto. Arquivo de ~2,5 MB, consultado a cada 5 min."

    def parse(self, payload, alert_names):
        return tm_parse(payload, alert_names)
