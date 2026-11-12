"""Modo rodada única (GitHub Actions): cada execução é um processo novo que consulta só as lojas na vez."""
import unittest

from skinmon import statuspage, testmode
from skinmon.db import DB
from skinmon.models import Offer
from skinmon.runner import Runner
from skinmon.sources.base import Source

SKIN = "★ Skeleton Knife | Slaughter"
T0 = 1_794_416_400.0  # 11/11/2026 14:00 em Brasília


class FakeSource(Source):
    def __init__(self, sid, interval, offers=(), error=None):
        super().__init__(env={}, sleep=lambda s: None)
        self.id, self.label, self.interval = sid, "Loja " + sid, interval
        self.offers, self.error, self.calls = list(offers), error, 0

    def search(self, alert, ctx):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.offers)


def offer(oid, price):
    return Offer(source="x", offer_id=oid, name=SKIN + " (Minimal Wear)", price=price, currency="BRL", url="https://loja/" + oid)


class DueTests(unittest.TestCase):
    def setUp(self):
        self.db = DB(":memory:", seed=False)
        self.db.add_alert(SKIN, 1700.0)
        self.clock = [T0]
        self.sent = []

    def tearDown(self):
        self.db.close()

    def runner(self, *sources):
        return Runner(self.db, lambda s, t, h: self.sent.append(s) or "teste", list(sources),
                      fx_rates=lambda: {"USD": 5.5}, now=lambda: self.clock[0], log=lambda m: None)

    def test_never_checked_store_is_due(self):
        fast = FakeSource("rapida", 60)
        self.runner(fast).run_due()
        self.assertEqual(fast.calls, 1)

    def test_store_is_skipped_until_its_interval_has_passed(self):
        slow = FakeSource("lenta", 600)
        runner = self.runner(slow)
        runner.run_due()
        self.clock[0] += 300
        runner.run_due()
        self.assertEqual(slow.calls, 1)
        self.clock[0] += 300
        runner.run_due()
        self.assertEqual(slow.calls, 2)

    def test_small_schedule_delay_does_not_skip_a_run(self):
        mid = FakeSource("media", 300)
        runner = self.runner(mid)
        runner.run_due()
        self.clock[0] += 250  # agenda do GitHub chegou um pouco antes
        runner.run_due()
        self.assertEqual(mid.calls, 2)

    def test_failing_store_waits_for_its_backoff(self):
        broken = FakeSource("quebrada", 60, error=RuntimeError("fora do ar"))
        runner = self.runner(broken)
        runner.run_due()
        self.clock[0] += 60
        runner.run_due()
        self.assertEqual(broken.calls, 1)  # espera 120 s depois da primeira falha
        self.clock[0] += 120
        runner.run_due()
        self.assertEqual(broken.calls, 2)

    def test_forced_round_checks_every_store(self):
        slow = FakeSource("lenta", 600)
        runner = self.runner(slow)
        runner.run_due()
        self.clock[0] += 60
        runner.run_due(force=True)
        self.assertEqual(slow.calls, 2)

    def test_new_process_with_the_same_database_does_not_resend(self):
        source = FakeSource("loja", 60, offers=[offer("a", 1650.0)])
        self.runner(source).run_due()
        self.clock[0] += 300
        self.runner(source).run_due()  # outra execução do GitHub = outro processo, mesmo banco
        self.assertEqual(len(self.sent), 1)

    def test_test_round_marks_the_subject_and_a_repeat_sends_nothing(self):
        source = FakeSource("loja", 60, offers=[offer("a", 1949.5)])
        for _ in range(2):
            testmode.start(self.db, 2000.0)
            self.runner(source).run_due(force=True)
            testmode.finish(self.db)
            self.clock[0] += 300
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0].startswith("[TESTE] "))
        self.assertEqual(self.db.alerts()[0].max_price, 1700.0)


class StatusPageTests(unittest.TestCase):
    def setUp(self):
        self.db = DB(":memory:", seed=False)
        self.db.add_alert(SKIN, 1700.0)
        self.sources = [FakeSource("ok", 60), FakeSource("ruim", 300), FakeSource("nova", 60)]
        self.sources[0].link_kind, self.sources[1].link_kind = "offer", "search"
        self.db.set_status("ok", state="ok", last_poll=T0 - 30, last_ok=T0 - 30, best_brl=1949.5, matched=3, eligible=0)
        self.db.set_status("ruim", state="erro", last_poll=T0 - 60, last_ok=T0 - 7200, error="HTTP 502 de loja.exemplo")
        self.db.log_sent(T0 - 600, 1, "ok", "★ Skeleton Knife | Slaughter (MW) — R$ 1.650,00 total — Loja ok", 1, "eu@exemplo.com")

    def tearDown(self):
        self.db.close()

    def render(self):
        return statuspage.render(self.db, self.sources, T0, {"USD": 5.5645}, lambda s: {"enabled": True})

    def test_page_shows_when_it_was_updated_in_brasilia_time(self):
        self.assertIn("11/11/2026 14:00:00", self.render())

    def test_page_lists_the_alert_and_ceiling(self):
        page = self.render()
        self.assertIn("★ Skeleton Knife \\| Slaughter", page)
        self.assertIn("R$ 1.700,00", page)

    def test_each_store_shows_its_last_successful_check(self):
        page = self.render()
        self.assertIn("13:59:30", page)
        self.assertIn("12:00:00", page)
        self.assertIn("HTTP 502 de loja.exemplo", page)
        self.assertIn("nenhuma ainda", page)

    def test_link_kind_is_explained_per_store(self):
        page = self.render()
        self.assertIn("faca específica", page)
        self.assertIn("busca", page)

    def test_recent_emails_are_listed_without_the_address(self):
        page = self.render()
        self.assertIn("R$ 1.650,00 total", page)
        self.assertNotIn("eu@exemplo.com", page)


if __name__ == "__main__":
    unittest.main()
