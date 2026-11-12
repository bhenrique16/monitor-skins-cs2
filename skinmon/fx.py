"""Câmbio comercial para BRL, com cache, fonte reserva e último valor guardado em disco."""
from __future__ import annotations

import json
import threading
import time

from . import net

PRIMARY = "https://economia.awesomeapi.com.br/json/last/USD-BRL,EUR-BRL"
FALLBACK = "https://open.er-api.com/v6/latest/USD"
TTL = 300  # a fonte principal renova a cada 5 min
MAX_AGE = 24 * 3600  # depois disso o valor guardado deixa de ser usado


def parse_primary(payload: dict) -> dict:
    rates = {}
    for code in ("USD", "EUR"):
        row = payload.get(code + "BRL") or {}
        try:
            rates[code] = float(row.get("ask"))
        except (TypeError, ValueError):
            pass
    return rates


def parse_fallback(payload: dict) -> dict:
    table = payload.get("rates") or {}
    brl = table.get("BRL")
    rates = {}
    if isinstance(brl, (int, float)) and brl > 0:
        rates["USD"] = float(brl)
        eur = table.get("EUR")
        if isinstance(eur, (int, float)) and eur > 0:
            rates["EUR"] = float(brl) / float(eur)
    return rates


class Fx:
    def __init__(self, db, fetch=net.fetch, now=time.time):
        self.db, self.fetch, self.now = db, fetch, now
        self._lock = threading.Lock()
        self._checked = 0.0

    def _stored(self) -> dict:
        try:
            return json.loads(self.db.get("fx") or "{}")
        except ValueError:
            return {}

    def state(self) -> dict:
        """{"rates": {...}, "at": epoch, "source": "..."} do último câmbio obtido."""
        return self._stored()

    def rates(self) -> dict:
        with self._lock:
            now = self.now()
            stored = self._stored()
            # Outro processo (rodada anterior) pode ter buscado o câmbio há pouco: vale o horário guardado.
            last = max(self._checked, stored.get("at", 0) if stored.get("rates") else 0)
            if now - last >= TTL:
                self._checked = now
                for url, parser, label in ((PRIMARY, parse_primary, "AwesomeAPI"), (FALLBACK, parse_fallback, "open.er-api.com")):
                    try:
                        rates = parser(self.fetch(url, timeout=15).json())
                    except Exception:
                        continue
                    if rates.get("USD"):
                        stored = {"rates": rates, "at": now, "source": label}
                        self.db.set("fx", json.dumps(stored))
                        break
            if stored.get("rates") and now - stored.get("at", 0) <= MAX_AGE:
                return dict(stored["rates"])
            return {}
