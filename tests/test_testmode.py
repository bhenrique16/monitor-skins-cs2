import unittest

from skinmon import testmode
from skinmon.db import DB

SKIN = "★ Skeleton Knife | Slaughter"


class TestModeTests(unittest.TestCase):
    def setUp(self):
        self.db = DB(":memory:", seed=False)
        self.knife = self.db.add_alert(SKIN, 1700.0)
        self.paused = self.db.add_alert("AK-47 | Redline", 100.0, active=False)

    def tearDown(self):
        self.db.close()

    def test_start_raises_active_ceilings_and_marks_subjects(self):
        testmode.start(self.db, 2000.0)
        self.assertEqual(self.db.get_alert(self.knife).max_price, 2000.0)
        self.assertEqual(self.db.get_alert(self.paused).max_price, 100.0)
        self.assertEqual(self.db.get("assunto_teste"), "1")
        state = testmode.state(self.db)
        self.assertTrue(state["active"])
        self.assertEqual(state["ceiling"], 2000.0)
        self.assertEqual(state["original"], {str(self.knife): 1700.0})

    def test_finish_restores_the_original_ceiling(self):
        testmode.start(self.db, 2000.0)
        restored = testmode.finish(self.db)
        self.assertEqual(self.db.get_alert(self.knife).max_price, 1700.0)
        self.assertEqual(self.db.get("assunto_teste"), "0")
        self.assertFalse(testmode.state(self.db)["active"])
        self.assertEqual(restored, {self.knife: 1700.0})

    def test_starting_twice_keeps_the_first_original_ceiling(self):
        testmode.start(self.db, 2000.0)
        testmode.start(self.db, 2500.0)
        self.assertEqual(self.db.get_alert(self.knife).max_price, 2500.0)
        testmode.finish(self.db)
        self.assertEqual(self.db.get_alert(self.knife).max_price, 1700.0)

    def test_finish_without_start_changes_nothing(self):
        self.assertEqual(testmode.finish(self.db), {})
        self.assertEqual(self.db.get_alert(self.knife).max_price, 1700.0)

    def test_alert_deleted_during_the_test_is_skipped(self):
        testmode.start(self.db, 2000.0)
        self.db.delete_alert(self.knife)
        self.assertEqual(testmode.finish(self.db), {})


class SharedDatabaseTests(unittest.TestCase):
    """Comandos rodados no servidor (ex.: teste iniciar) abrem o banco enquanto o monitor está rodando."""

    def test_file_database_allows_a_second_connection_to_write(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "monitor.db")
            service, command = DB(path), DB(path)
            try:
                self.assertEqual(service._one("PRAGMA journal_mode")[0], "wal")
                testmode.start(command, 2000.0)
                self.assertEqual(service.alerts()[0].max_price, 2000.0)
            finally:
                service.close()
                command.close()


if __name__ == "__main__":
    unittest.main()
