"""LIS-SKINS: exportação pública em JSON com o menor preço por item (dólar)."""
from __future__ import annotations

from .bulk import BulkSource, lis_parse

parse = lis_parse


class Lisskins(BulkSource):
    id = "lisskins"
    label = "LIS-SKINS"
    currency = "USD"
    pay_note = "cartão internacional ou cripto"
    url = "https://lis-skins.com/market_export_json/csgo.json"
    data_note = "Exportação pública em JSON (menor preço por item). Arquivo de ~2,6 MB, consultado a cada 5 min."

    def parse(self, payload, alert_names):
        return lis_parse(payload, alert_names)
