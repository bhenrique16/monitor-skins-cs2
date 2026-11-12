import os
import tempfile
import unittest
from dataclasses import replace

from skinmon.db import DB
from skinmon.engine import Engine, Seen, decide, is_eligible, matches_filters
from skinmon.models import Alert, MarketInfo, Offer
from skinmon.pricing import CostSettings, MarketFees, estimate

SKIN = "★ Skeleton Knife | Slaughter"
ALERT = Alert(id=1, name=SKIN, max_price=1700.0)
SETTINGS = CostSettings(iof_pct=3.5, spread_pct=4.0)
MARKET = MarketInfo(id="dashskins_br", label="DashSkins.com.br", currency="BRL", pay_kind="dinheiro", pay_note="PIX")
PIX = MarketFees(fee_pct=0.0)
T0 = 1_794_416_400.0  # 2026-11-11 17:00:00 UTC


def offer(oid, price, name=SKIN + " (Minimal Wear)", **kw):
    return Offer(source="dashskins_br", offer_id=oid, name=name, price=price, currency="BRL",
                 url="https://dashskins.com.br/item/x/" + oid, **kw)


class DecideTests(unittest.TestCase):
    def test_first_sighting_under_ceiling_notifies_as_new(self):
        d = decide(None, 1650.0, True)
        self.assertTrue(d.notify)
        self.assertEqual(d.reason, "novo")
        self.assertEqual(d.notified_price, 1650.0)

    def test_first_sighting_above_ceiling_stays_silent(self):
        d = decide(None, 1800.0, False)
        self.assertFalse(d.notify)
        self.assertIsNone(d.notified_price)

    def test_existing_listing_dropping_below_ceiling_notifies_with_old_price(self):
        d = decide(Seen(last_price=1800.0, notified_price=None), 1650.0, True)
        self.assertTrue(d.notify)
        self.assertEqual(d.reason, "baixou")
        self.assertEqual(d.previous_price, 1800.0)

    def test_listing_already_notified_at_same_price_is_not_repeated(self):
        d = decide(Seen(last_price=1650.0, notified_price=1650.0), 1650.0, True)
        self.assertFalse(d.notify)
        self.assertEqual(d.notified_price, 1650.0)

    def test_further_drop_of_one_percent_or_more_notifies_again(self):
        d = decide(Seen(last_price=1650.0, notified_price=1650.0), 1600.0, True)
        self.assertTrue(d.notify)
        self.assertEqual(d.reason, "baixou")
        self.assertEqual(d.previous_price, 1650.0)
        self.assertEqual(d.notified_price, 1600.0)

    def test_drop_smaller_than_one_percent_is_ignored(self):
        d = decide(Seen(last_price=1650.0, notified_price=1650.0), 1649.0, True)
        self.assertFalse(d.notify)
        self.assertEqual(d.notified_price, 1650.0)

    def test_price_raised_out_of_the_filter_rearms_the_alert(self):
        raised = decide(Seen(last_price=1650.0, notified_price=1650.0), 1800.0, False)
        self.assertFalse(raised.notify)
        self.assertIsNone(raised.notified_price)
        back = decide(Seen(last_price=1800.0, notified_price=raised.notified_price), 1650.0, True)
        self.assertTrue(back.notify)

    def test_unchanged_price_becoming_eligible_is_reported_as_entering_the_filter(self):
        d = decide(Seen(last_price=1800.0, notified_price=None), 1800.0, True)
        self.assertTrue(d.notify)
        self.assertEqual(d.reason, "entrou")

    def test_exchange_rate_wobble_does_not_repeat_the_notification(self):
        out = decide(Seen(last_price=300.0, notified_price=300.0), 300.0, False)
        self.assertFalse(out.notify)
        again = decide(Seen(last_price=300.0, notified_price=out.notified_price), 300.0, True)
        self.assertFalse(again.notify)

    def test_raise_while_still_eligible_moves_the_reference_up_silently(self):
        d = decide(Seen(last_price=1650.0, notified_price=1650.0), 1690.0, True)
        self.assertFalse(d.notify)
        self.assertEqual(d.notified_price, 1690.0)


class EligibilityTests(unittest.TestCase):
    def test_total_under_the_ceiling_is_eligible(self):
        self.assertTrue(is_eligible(ALERT, estimate(1650.0, "BRL", PIX, SETTINGS, {})))

    def test_total_equal_to_the_ceiling_is_eligible(self):
        self.assertTrue(is_eligible(ALERT, estimate(1700.0, "BRL", PIX, SETTINGS, {})))

    def test_listing_of_1670_that_costs_1730_is_out_of_a_1700_alert(self):
        cost = estimate(1670.0, "BRL", MarketFees(fee_pct=0.0, fee_fixed=60.0), SETTINGS, {})
        self.assertFalse(is_eligible(ALERT, cost))

    def test_same_listing_is_eligible_when_the_alert_uses_the_listed_price(self):
        cost = estimate(1670.0, "BRL", MarketFees(fee_pct=0.0, fee_fixed=60.0), SETTINGS, {})
        self.assertTrue(is_eligible(replace(ALERT, basis="listed"), cost))

    def test_incomplete_total_is_eligible_only_if_the_alert_accepts_it(self):
        cost = estimate(280.0, "USD", MarketFees(fee_pct=None), SETTINGS, {"USD": 5.5})
        self.assertLess(cost.total_brl, 1700.0)
        self.assertTrue(is_eligible(replace(ALERT, include_incomplete=True), cost))
        self.assertFalse(is_eligible(replace(ALERT, include_incomplete=False), cost))

    def test_listed_basis_ignores_missing_fee_data(self):
        cost = estimate(280.0, "USD", MarketFees(fee_pct=None), SETTINGS, {"USD": 5.5})
        self.assertTrue(is_eligible(replace(ALERT, basis="listed", include_incomplete=False), cost))

    def test_offer_without_exchange_rate_is_never_eligible(self):
        cost = estimate(100.0, "USD", PIX, SETTINGS, {})
        self.assertFalse(is_eligible(ALERT, cost))
        self.assertFalse(is_eligible(replace(ALERT, basis="listed"), cost))


class FilterTests(unittest.TestCase):
    def test_other_skin_is_rejected(self):
        self.assertFalse(matches_filters(ALERT, offer("a", 1.0, name="★ Skeleton Knife | Fade (Factory New)")))

    def test_any_wear_and_stattrak_match_by_default(self):
        self.assertTrue(matches_filters(ALERT, offer("a", 1.0, name="★ StatTrak™ Skeleton Knife | Slaughter (Field-Tested)")))

    def test_wear_filter_keeps_only_selected_wears(self):
        alert = replace(ALERT, wears=("FN", "MW"))
        self.assertTrue(matches_filters(alert, offer("a", 1.0)))
        self.assertFalse(matches_filters(alert, offer("b", 1.0, name=SKIN + " (Field-Tested)")))

    def test_wear_filter_rejects_offers_whose_wear_is_unknown(self):
        alert = replace(ALERT, wears=("FN",))
        self.assertFalse(matches_filters(alert, offer("a", 1.0, name=SKIN)))

    def test_wear_filter_uses_float_when_the_name_has_no_wear(self):
        alert = replace(ALERT, wears=("FN",))
        self.assertTrue(matches_filters(alert, offer("a", 1.0, name=SKIN, float_value=0.03)))

    def test_stattrak_filters(self):
        st = offer("a", 1.0, name="★ StatTrak™ Skeleton Knife | Slaughter (Minimal Wear)")
        plain = offer("b", 1.0)
        self.assertFalse(matches_filters(replace(ALERT, stattrak="exclude"), st))
        self.assertTrue(matches_filters(replace(ALERT, stattrak="exclude"), plain))
        self.assertTrue(matches_filters(replace(ALERT, stattrak="only"), st))
        self.assertFalse(matches_filters(replace(ALERT, stattrak="only"), plain))


class FakeSend:
    def __init__(self):
        self.sent = []
        self.fail = False

    def __call__(self, subject, text, html):
        if self.fail:
            raise RuntimeError("smtp fora do ar")
        self.sent.append((subject, text, html))
        return "teste"


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "monitor.db")
        self.clock = [T0]
        self.send = FakeSend()
        self.db = DB(self.path, seed=False)
        self.alert = self.db.get_alert(self.db.add_alert(SKIN, 1700.0))
        self.engine = Engine(self.db, self.send, now=lambda: self.clock[0])

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def run_poll(self, offers, fees=PIX, engine=None, alert=None):
        return (engine or self.engine).process(MARKET, alert or self.alert, offers, fees, SETTINGS, {})

    def test_eligible_offer_sends_one_email(self):
        res = self.run_poll([offer("a", 1650.0)])
        self.assertEqual(len(self.send.sent), 1)
        self.assertEqual(res.emails, 1)
        self.assertEqual(res.eligible, 1)

    def test_same_offer_on_the_next_poll_is_not_sent_again(self):
        self.run_poll([offer("a", 1650.0)])
        self.run_poll([offer("a", 1650.0)])
        self.assertEqual(len(self.send.sent), 1)

    def test_restart_with_the_same_database_does_not_resend(self):
        self.run_poll([offer("a", 1650.0)])
        self.db.close()
        self.db = DB(self.path, seed=False)
        engine = Engine(self.db, self.send, now=lambda: self.clock[0])
        self.run_poll([offer("a", 1650.0)], engine=engine)
        self.assertEqual(len(self.send.sent), 1)

    def test_offer_above_the_ceiling_sends_nothing(self):
        res = self.run_poll([offer("a", 1949.5)])
        self.assertEqual(self.send.sent, [])
        self.assertEqual(res.matched, 1)
        self.assertEqual(res.eligible, 0)

    def test_listing_of_1670_that_costs_1730_with_fees_is_not_sent(self):
        self.run_poll([offer("a", 1670.0)], fees=MarketFees(fee_pct=0.0, fee_fixed=60.0))
        self.assertEqual(self.send.sent, [])

    def test_price_drop_across_the_ceiling_sends_email_with_the_old_price(self):
        self.run_poll([offer("a", 1800.0)])
        self.run_poll([offer("a", 1650.0)])
        self.assertEqual(len(self.send.sent), 1)
        subject, text, html = self.send.sent[0]
        self.assertIn("R$ 1.800,00", html)
        self.assertIn("R$ 1.650,00", subject)

    def test_new_offers_of_one_poll_are_grouped_and_led_by_the_cheapest(self):
        res = self.run_poll([offer("a", 1690.0), offer("b", 1640.0), offer("c", 1660.0)])
        self.assertEqual(len(self.send.sent), 1)
        self.assertEqual(res.notified, 3)
        subject, text, html = self.send.sent[0]
        self.assertIn("R$ 1.640,00", subject)
        for oid in ("a", "b", "c"):
            self.assertIn("https://dashskins.com.br/item/x/" + oid, html)

    def test_failed_send_is_retried_on_the_next_poll(self):
        self.send.fail = True
        res = self.run_poll([offer("a", 1650.0)])
        self.assertEqual(res.emails, 0)
        self.send.fail = False
        self.run_poll([offer("a", 1650.0)])
        self.assertEqual(len(self.send.sent), 1)

    def test_other_skins_returned_by_the_search_are_ignored(self):
        res = self.run_poll([offer("a", 900.0, name="★ Skeleton Knife | Fade (Factory New)")])
        self.assertEqual(self.send.sent, [])
        self.assertEqual(res.matched, 0)

    def test_hourly_cap_holds_extra_emails_until_the_window_passes(self):
        engine = Engine(self.db, self.send, now=lambda: self.clock[0], max_per_hour=1)
        self.run_poll([offer("a", 1650.0)], engine=engine)
        self.run_poll([offer("b", 1640.0)], engine=engine)
        self.assertEqual(len(self.send.sent), 1)
        self.clock[0] += 3700
        self.run_poll([offer("b", 1640.0)], engine=engine)
        self.assertEqual(len(self.send.sent), 2)

    def test_result_reports_the_cheapest_matching_offer(self):
        res = self.run_poll([offer("a", 1949.5), offer("b", 3200.0, name=SKIN + " (Factory New)")])
        self.assertEqual(res.best_brl, 1949.5)
        self.assertEqual(res.best_name, SKIN + " (Minimal Wear)")

    def test_sent_email_is_recorded_in_the_log(self):
        self.run_poll([offer("a", 1650.0)])
        log = self.db.recent_sent(5)
        self.assertEqual(len(log), 1)
        self.assertIn("DashSkins.com.br", log[0]["subject"])

    def test_test_mode_marks_the_subject(self):
        self.db.set("assunto_teste", "1")
        self.run_poll([offer("a", 1650.0)])
        self.assertTrue(self.send.sent[0][0].startswith("[TESTE] "))

    def test_normal_mode_subject_has_no_test_mark(self):
        self.run_poll([offer("a", 1650.0)])
        self.assertNotIn("TESTE", self.send.sent[0][0])

    def test_unchanged_offer_is_not_rewritten_on_every_poll(self):
        writes = []
        original = self.db.save_seen

        def counting(*args, **kwargs):
            writes.append(1)
            return original(*args, **kwargs)

        self.db.save_seen = counting
        self.run_poll([offer("a", 1949.5)])
        self.clock[0] += 60
        self.run_poll([offer("a", 1949.5)])
        self.assertEqual(len(writes), 1)

    def test_unchanged_offer_is_refreshed_hourly_so_it_is_not_pruned(self):
        self.run_poll([offer("a", 1949.5)])
        self.clock[0] += 3700
        self.run_poll([offer("a", 1949.5)])
        row = self.db.get_seen(self.alert.id, "dashskins_br", "a")
        self.assertEqual(row["last_seen"], T0 + 3700)

    def test_price_change_is_always_recorded(self):
        self.run_poll([offer("a", 1949.5)])
        self.clock[0] += 60
        self.run_poll([offer("a", 1900.0)])
        self.assertEqual(self.db.get_seen(self.alert.id, "dashskins_br", "a")["last_price"], 1900.0)

    def test_raising_the_ceiling_notifies_offers_that_now_fit(self):
        self.run_poll([offer("a", 1949.5)])
        self.db.update_alert(self.alert.id, max_price=2000.0)
        self.run_poll([offer("a", 1949.5)], alert=self.db.get_alert(self.alert.id))
        self.assertEqual(len(self.send.sent), 1)


if __name__ == "__main__":
    unittest.main()
