import unittest

from skinmon import net
from skinmon.db import DB
from skinmon.models import Offer
from skinmon.runner import Runner
from skinmon.sources.base import Source

SKIN = "★ Skeleton Knife | Slaughter"
T0 = 1_794_416_400.0


class FakeSource(Source):
    id = "fake"
    label = "Loja Falsa"
    currency = "BRL"
    interval = 60
    pause = 0

    def __init__(self, offers=None, error=None, fail_for=()):
        super().__init__(env={}, sleep=lambda s: None)
        self.offers = offers if offers is not None else []
        self.error = error
        self.fail_for = fail_for
        self.calls = 0

    def search(self, alert, ctx):
        self.calls += 1
        if self.error:
            raise self.error
        if alert.name in self.fail_for:
            raise net.HttpError(500, "https://loja.exemplo/api", "erro interno")
        return list(self.offers)


def offer(oid, price, name=SKIN + " (Minimal Wear)"):
    return Offer(source="fake", offer_id=oid, name=name, price=price, currency="BRL", url="https://loja.exemplo/" + oid)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.db = DB(":memory:", seed=False)
        self.alert_id = self.db.add_alert(SKIN, 1700.0)
        self.clock = [T0]
        self.sent = []

    def tearDown(self):
        self.db.close()

    def send(self, subject, text, html):
        self.sent.append(subject)
        return "teste"

    def runner(self, *sources):
        return Runner(self.db, self.send, list(sources), fx_rates=lambda: {"USD": 5.5}, now=lambda: self.clock[0], log=lambda m: None)

    def test_successful_poll_records_when_the_store_was_checked(self):
        source = FakeSource([offer("a", 1949.5)])
        outcome = self.runner(source).poll_once(source)
        status = self.db.get_status("fake")
        self.assertEqual(outcome.state, "ok")
        self.assertEqual(status["last_poll"], T0)
        self.assertEqual(status["last_ok"], T0)
        self.assertEqual(status["matched"], 1)
        self.assertEqual(status["best_brl"], 1949.5)
        self.assertEqual(status["error"], "")

    def test_eligible_offer_from_a_poll_sends_an_email(self):
        source = FakeSource([offer("a", 1650.0)])
        self.runner(source).poll_once(source)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Loja Falsa", self.sent[0])

    def test_failing_store_is_recorded_and_does_not_raise(self):
        source = FakeSource(error=RuntimeError("explodiu"))
        outcome = self.runner(source).poll_once(source)
        status = self.db.get_status("fake")
        self.assertEqual(outcome.state, "erro")
        self.assertIn("explodiu", status["error"])
        self.assertEqual(status["fails"], 1)
        self.assertNotIn("last_ok", status)

    def test_failure_in_one_store_leaves_the_other_working(self):
        broken, healthy = FakeSource(error=RuntimeError("fora do ar")), FakeSource([offer("a", 1650.0)])
        healthy.id, healthy.label = "ok", "Loja Boa"
        results = self.runner(broken, healthy).run_once()
        self.assertEqual([o.state for _, o in results], ["erro", "ok"])
        self.assertEqual(len(self.sent), 1)

    def test_failure_for_one_alert_still_processes_the_others(self):
        other = self.db.add_alert("AK-47 | Redline", 100.0)
        source = FakeSource([offer("a", 1650.0)], fail_for=("AK-47 | Redline",))
        outcome = self.runner(source).poll_once(source)
        self.assertEqual(outcome.state, "erro")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("AK-47", self.db.get_status("fake")["error"])
        self.assertIsNotNone(other)

    def test_disabled_store_is_not_consulted(self):
        source = FakeSource([offer("a", 1650.0)])
        self.db.set_market("fake", enabled=False, fee_pct=0.0, fee_fixed=0.0)
        outcome = self.runner(source).poll_once(source)
        self.assertEqual(outcome.state, "desativada")
        self.assertEqual(source.calls, 0)
        self.assertEqual(self.sent, [])

    def test_no_active_alert_means_no_request(self):
        self.db.update_alert(self.alert_id, active=False)
        source = FakeSource([offer("a", 1650.0)])
        outcome = self.runner(source).poll_once(source)
        self.assertEqual(outcome.state, "sem alertas")
        self.assertEqual(source.calls, 0)

    def test_store_fee_set_by_the_user_is_applied(self):
        source = FakeSource([offer("a", 1670.0)])
        self.db.set_market("fake", enabled=True, fee_pct=0.0, fee_fixed=60.0)
        self.runner(source).poll_once(source)
        self.assertEqual(self.sent, [])

    def test_rate_limit_backs_off_for_at_least_ten_minutes(self):
        source = FakeSource(error=net.RateLimited("https://loja.exemplo/api"))
        outcome = self.runner(source).poll_once(source)
        self.assertEqual(outcome.state, "limite")
        self.assertGreaterEqual(outcome.wait, 600)

    def test_repeated_failures_wait_longer_up_to_fifteen_minutes(self):
        source = FakeSource(error=RuntimeError("fora do ar"))
        runner = self.runner(source)
        waits = [runner.poll_once(source).wait for _ in range(6)]
        self.assertEqual(waits[0], 120)
        self.assertEqual(waits[1], 240)
        self.assertEqual(waits[-1], 900)

    def test_success_after_failures_returns_to_the_normal_interval(self):
        source = FakeSource(error=RuntimeError("fora do ar"))
        runner = self.runner(source)
        runner.poll_once(source)
        source.error = None
        outcome = runner.poll_once(source)
        self.assertEqual(outcome.wait, 60)
        self.assertEqual(self.db.get_status("fake")["fails"], 0)

    def test_store_down_for_an_hour_sends_one_warning(self):
        source = FakeSource(error=RuntimeError("fora do ar"))
        runner = self.runner(source)
        runner.poll_once(source)
        self.assertEqual(self.sent, [])
        self.clock[0] += 3700
        runner.poll_once(source)
        self.clock[0] += 3700
        runner.poll_once(source)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Loja Falsa", self.sent[0])

    def test_warning_is_rearmed_after_the_store_recovers(self):
        source = FakeSource(error=RuntimeError("fora do ar"))
        runner = self.runner(source)
        runner.poll_once(source)
        self.clock[0] += 3700
        runner.poll_once(source)
        source.error = None
        runner.poll_once(source)
        source.error = RuntimeError("caiu de novo")
        runner.poll_once(source)
        self.clock[0] += 3700
        runner.poll_once(source)
        self.assertEqual(len(self.sent), 2)

    def test_foreign_store_without_exchange_rate_is_flagged(self):
        source = FakeSource([Offer(source="fake", offer_id="a", name=SKIN + " (Minimal Wear)", price=280.0, currency="USD", url="https://x")])
        source.currency = "USD"
        runner = Runner(self.db, self.send, [source], fx_rates=lambda: {}, now=lambda: self.clock[0], log=lambda m: None)
        runner.poll_once(source)
        self.assertIn("câmbio", self.db.get_status("fake")["note"])
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
