"""Armazenamento em um único arquivo SQLite: alertas, ajustes, estado dos anúncios e histórico."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time

from .models import Alert

DEFAULT_ALERT = ("★ Skeleton Knife | Slaughter", 1700.0)

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    max_price REAL NOT NULL,
    basis TEXT NOT NULL DEFAULT 'total',
    include_incomplete INTEGER NOT NULL DEFAULT 1,
    wears TEXT NOT NULL DEFAULT '',
    stattrak TEXT NOT NULL DEFAULT 'any',
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS markets (
    id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL,
    fee_pct REAL,
    fee_fixed REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS offers (
    alert_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    offer_id TEXT NOT NULL,
    name TEXT NOT NULL,
    last_price REAL NOT NULL,
    currency TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    notified_price REAL,
    notified_at REAL,
    PRIMARY KEY (alert_id, source, offer_id)
);
CREATE TABLE IF NOT EXISTS source_status (source TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    alert_id INTEGER,
    source TEXT,
    subject TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    dest TEXT
);
CREATE INDEX IF NOT EXISTS sent_at ON sent (at);
"""

_ALERT_FIELDS = ("name", "max_price", "basis", "include_incomplete", "wears", "stattrak", "active")


def _to_alert(row) -> Alert:
    return Alert(
        id=row["id"],
        name=row["name"],
        max_price=row["max_price"],
        basis=row["basis"],
        include_incomplete=bool(row["include_incomplete"]),
        wears=tuple(w for w in row["wears"].split(",") if w),
        stattrak=row["stattrak"],
        active=bool(row["active"]),
    )


class DB:
    def __init__(self, path: str, seed: bool = True):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
        self._con.row_factory = sqlite3.Row
        if path != ":memory:":
            # WAL: um comando rodado no servidor pode gravar enquanto o monitor lê e grava.
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA busy_timeout=30000")
        self._con.executescript(SCHEMA)
        if seed and self.get("seeded") is None:
            self.add_alert(*DEFAULT_ALERT)
            self.set("seeded", "1")

    def close(self):
        with self._lock:
            self._con.close()

    def _all(self, sql, args=()):
        with self._lock:
            return self._con.execute(sql, args).fetchall()

    def _one(self, sql, args=()):
        with self._lock:
            return self._con.execute(sql, args).fetchone()

    def _run(self, sql, args=()):
        with self._lock:
            return self._con.execute(sql, args)

    # ---- ajustes ---------------------------------------------------------
    def get(self, key, default=None):
        row = self._one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set(self, key, value):
        self._run("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                  (key, str(value)))

    def get_float(self, key, default):
        try:
            return float(self.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    # ---- alertas ---------------------------------------------------------
    def alerts(self, active_only=False):
        sql = "SELECT * FROM alerts" + (" WHERE active = 1" if active_only else "") + " ORDER BY id"
        return [_to_alert(r) for r in self._all(sql)]

    def get_alert(self, alert_id):
        row = self._one("SELECT * FROM alerts WHERE id = ?", (alert_id,))
        return _to_alert(row) if row else None

    def add_alert(self, name, max_price, basis="total", include_incomplete=True, wears=(), stattrak="any", active=True):
        cur = self._run(
            "INSERT INTO alerts (name, max_price, basis, include_incomplete, wears, stattrak, active, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, float(max_price), basis, int(include_incomplete), ",".join(wears), stattrak, int(active), time.time()),
        )
        return cur.lastrowid

    def update_alert(self, alert_id, **fields):
        sets, args = [], []
        for key, value in fields.items():
            if key not in _ALERT_FIELDS:
                raise KeyError(key)
            if key == "wears":
                value = ",".join(value)
            elif key in ("include_incomplete", "active"):
                value = int(bool(value))
            sets.append(key + " = ?")
            args.append(value)
        if sets:
            self._run("UPDATE alerts SET " + ", ".join(sets) + " WHERE id = ?", (*args, alert_id))

    def delete_alert(self, alert_id):
        self._run("DELETE FROM alerts WHERE id = ?", (alert_id,))
        self._run("DELETE FROM offers WHERE alert_id = ?", (alert_id,))

    # ---- lojas -----------------------------------------------------------
    def market_overrides(self):
        return {r["id"]: r for r in self._all("SELECT * FROM markets")}

    def set_market(self, market_id, enabled, fee_pct, fee_fixed):
        self._run(
            "INSERT INTO markets (id, enabled, fee_pct, fee_fixed) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled, fee_pct = excluded.fee_pct, fee_fixed = excluded.fee_fixed",
            (market_id, int(bool(enabled)), fee_pct, float(fee_fixed or 0)),
        )

    def delete_market(self, market_id):
        self._run("DELETE FROM markets WHERE id = ?", (market_id,))

    # ---- estado dos anúncios ----------------------------------------------
    def get_seen(self, alert_id, source, offer_id):
        return self._one("SELECT * FROM offers WHERE alert_id = ? AND source = ? AND offer_id = ?",
                         (alert_id, source, offer_id))

    def save_seen(self, alert_id, source_id, offer, now, notified_price, notified_at=None):
        self._run(
            "INSERT INTO offers (alert_id, source, offer_id, name, last_price, currency, first_seen, last_seen, notified_price, notified_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(alert_id, source, offer_id) DO UPDATE SET name = excluded.name, last_price = excluded.last_price,"
            " currency = excluded.currency, last_seen = excluded.last_seen, notified_price = excluded.notified_price,"
            " notified_at = COALESCE(excluded.notified_at, offers.notified_at)",
            (alert_id, source_id, offer.offer_id, offer.name, offer.price, offer.currency, now, now, notified_price, notified_at),
        )

    def prune(self, now, offers_days=30, sent_days=90):
        self._run("DELETE FROM offers WHERE last_seen < ?", (now - offers_days * 86400,))
        self._run("DELETE FROM sent WHERE at < ?", (now - sent_days * 86400,))

    # ---- situação das lojas ------------------------------------------------
    def get_status(self, source):
        row = self._one("SELECT data FROM source_status WHERE source = ?", (source,))
        return json.loads(row["data"]) if row else {}

    def set_status(self, source, **fields):
        with self._lock:
            data = self.get_status(source)
            data.update(fields)
            self._run("INSERT INTO source_status (source, data) VALUES (?, ?) ON CONFLICT(source) DO UPDATE SET data = excluded.data",
                      (source, json.dumps(data, ensure_ascii=False)))
            return data

    # ---- e-mails enviados --------------------------------------------------
    def log_sent(self, at, alert_id, source, subject, count, dest):
        self._run("INSERT INTO sent (at, alert_id, source, subject, count, dest) VALUES (?, ?, ?, ?, ?, ?)",
                  (at, alert_id, source, subject, count, dest))

    def count_sent_since(self, since):
        return self._one("SELECT COUNT(*) AS n FROM sent WHERE at >= ?", (since,))["n"]

    def recent_sent(self, limit=20):
        return [dict(r) for r in self._all("SELECT * FROM sent ORDER BY id DESC LIMIT ?", (limit,))]
