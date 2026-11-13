import json
import os
import tempfile
import unittest

from skinmon import settings_file
from skinmon.db import DB

SKIN = "★ Skeleton Knife | Slaughter"


def write(tmp, data):
    path = os.path.join(tmp, "config.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))
    return path


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_minimal_config_gets_defaults(self):
        cfg = settings_file.load(write(self.tmp.name, {"alertas": [{"skin": SKIN, "teto": 1700}]}))
        alert = cfg["alertas"][0]
        self.assertEqual(alert["name"], SKIN)
        self.assertEqual(alert["max_price"], 1700.0)
        self.assertEqual(alert["basis"], "total")
        self.assertEqual(alert["stattrak"], "any")
        self.assertEqual(alert["wears"], ())
        self.assertTrue(alert["include_incomplete"])
        self.assertTrue(alert["active"])

    def test_portuguese_options_are_understood(self):
        cfg = settings_file.load(write(self.tmp.name, {"alertas": [{
            "skin": SKIN + " (Minimal Wear)", "teto": "1.650,00", "comparar": "anunciado", "stattrak": "sem",
            "desgastes": ["fn", "MW"], "aceitar_total_incompleto": False, "ativo": False}]}))
        alert = cfg["alertas"][0]
        self.assertEqual(alert["name"], SKIN)
        self.assertEqual(alert["max_price"], 1650.0)
        self.assertEqual(alert["basis"], "listed")
        self.assertEqual(alert["stattrak"], "exclude")
        self.assertEqual(alert["wears"], ("FN", "MW"))
        self.assertFalse(alert["include_incomplete"])
        self.assertFalse(alert["active"])

    def test_broken_json_gives_a_clear_message(self):
        with self.assertRaises(ValueError) as ctx:
            settings_file.load(write(self.tmp.name, '{"alertas": [ {"skin": "x", "teto": 1700,} ]}'))
        self.assertIn("config.json", str(ctx.exception))
        self.assertIn("linha 1", str(ctx.exception))

    def test_invalid_ceiling_names_the_alert(self):
        with self.assertRaises(ValueError) as ctx:
            settings_file.load(write(self.tmp.name, {"alertas": [{"skin": SKIN, "teto": "barato"}]}))
        self.assertIn("teto", str(ctx.exception))
        self.assertIn("Skeleton Knife", str(ctx.exception))

    def test_store_and_cost_settings_are_read(self):
        cfg = settings_file.load(write(self.tmp.name, {
            "alertas": [],
            "lojas": {"csfloat": {"ativa": True, "taxa_percentual": 2.8, "taxa_fixa": 0.3},
                      "waxpeer": {"ativa": False}, "lisskins": {"taxa_percentual": None}},
            "custos": {"iof": 3.5, "spread": 1.1},
            "avisar_loja_fora_do_ar": False,
        }))
        self.assertEqual(cfg["lojas"]["csfloat"], {"enabled": True, "fee_pct": 2.8, "fee_fixed": 0.3})
        self.assertFalse(cfg["lojas"]["waxpeer"]["enabled"])
        self.assertIsNone(cfg["lojas"]["lisskins"]["fee_pct"])
        self.assertEqual(cfg["custos"], {"iof_pct": 3.5, "spread_pct": 1.1})
        self.assertFalse(cfg["avisar_loja_fora_do_ar"])


class StoreCostKeysTests(unittest.TestCase):
    def test_spread_and_iof_per_store_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = settings_file.load(write(tmp, {"alertas": [], "lojas": {
                "buffmarket": {"taxa_percentual": 5, "spread": -2.18, "iof": 0},
                "csmoney": {"taxa_percentual": 1, "spread": 0, "iof": 0},
                "csfloat": {"spread": None}}}))
        self.assertEqual(cfg["lojas"]["buffmarket"], {"fee_pct": 5.0, "spread_pct": -2.18, "iof_pct": 0.0})
        self.assertEqual(cfg["lojas"]["csmoney"], {"fee_pct": 1.0, "spread_pct": 0.0, "iof_pct": 0.0})
        self.assertIsNone(cfg["lojas"]["csfloat"]["spread_pct"])

    def test_sync_stores_the_overrides(self):
        db = DB(":memory:", seed=False)
        try:
            settings_file.sync(db, {"alertas": [], "custos": None, "avisar_loja_fora_do_ar": True,
                                    "lojas": {"buffmarket": {"fee_pct": 5.0, "spread_pct": -2.18, "iof_pct": 0.0}}})
            row = db.market_overrides()["buffmarket"]
            self.assertEqual((row["fee_pct"], row["spread_pct"], row["iof_pct"]), (5.0, -2.18, 0.0))
        finally:
            db.close()


class OldDatabaseTests(unittest.TestCase):
    def test_database_from_before_the_new_columns_is_upgraded(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "monitor.db")
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE markets (id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, fee_pct REAL, fee_fixed REAL NOT NULL DEFAULT 0)")
            con.execute("INSERT INTO markets VALUES ('waxpeer', 0, NULL, 0)")
            con.commit()
            con.close()
            db = DB(path, seed=False)
            try:
                row = db.market_overrides()["waxpeer"]
                self.assertIsNone(row["spread_pct"])
                self.assertIsNone(row["iof_pct"])
                self.assertEqual(row["enabled"], 0)
            finally:
                db.close()


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.db = DB(":memory:", seed=False)

    def tearDown(self):
        self.db.close()

    def cfg(self, alerts, **extra):
        base = {"alertas": alerts, "lojas": {}, "custos": None, "avisar_loja_fora_do_ar": True}
        base.update(extra)
        return base

    def alert(self, **kw):
        a = {"name": SKIN, "max_price": 1700.0, "basis": "total", "include_incomplete": True, "wears": (), "stattrak": "any", "active": True}
        a.update(kw)
        return a

    def test_first_sync_creates_the_alert(self):
        settings_file.sync(self.db, self.cfg([self.alert()]))
        alerts = self.db.alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].max_price, 1700.0)

    def test_ceiling_change_keeps_the_same_alert_and_its_history(self):
        settings_file.sync(self.db, self.cfg([self.alert()]))
        first_id = self.db.alerts()[0].id
        settings_file.sync(self.db, self.cfg([self.alert(max_price=1600.0)]))
        alerts = self.db.alerts()
        self.assertEqual([a.id for a in alerts], [first_id])
        self.assertEqual(alerts[0].max_price, 1600.0)

    def test_alert_removed_from_the_file_is_removed(self):
        settings_file.sync(self.db, self.cfg([self.alert(), self.alert(name="AK-47 | Redline", max_price=100.0)]))
        settings_file.sync(self.db, self.cfg([self.alert()]))
        self.assertEqual([a.name for a in self.db.alerts()], [SKIN])

    def test_store_settings_and_costs_are_applied(self):
        settings_file.sync(self.db, self.cfg([], lojas={"waxpeer": {"enabled": False, "fee_pct": None, "fee_fixed": 0.0}},
                                             custos={"iof_pct": 3.5, "spread_pct": 1.1}, avisar_loja_fora_do_ar=False))
        self.assertEqual(self.db.market_overrides()["waxpeer"]["enabled"], 0)
        self.assertEqual(self.db.get_float("spread_pct", 0), 1.1)
        self.assertEqual(self.db.get("aviso_falha"), "0")

    def test_store_missing_from_the_file_goes_back_to_its_default(self):
        settings_file.sync(self.db, self.cfg([], lojas={"waxpeer": {"enabled": False, "fee_pct": None, "fee_fixed": 0.0}}))
        settings_file.sync(self.db, self.cfg([], lojas={}))
        self.assertNotIn("waxpeer", self.db.market_overrides())


class ExampleFileTests(unittest.TestCase):
    def test_the_config_file_in_the_project_is_valid(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = settings_file.load(os.path.join(root, "config.json"))
        self.assertEqual(cfg["alertas"][0]["name"], SKIN)
        # O teto muda com o mercado: o teste só garante que há um teto válido, não um valor fixo.
        self.assertGreater(cfg["alertas"][0]["max_price"], 0)


if __name__ == "__main__":
    unittest.main()
