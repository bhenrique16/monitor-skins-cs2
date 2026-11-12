import unittest

from skinmon.pricing import CostSettings, MarketFees, estimate

SETTINGS = CostSettings(iof_pct=3.5, spread_pct=4.0)


class BrlTests(unittest.TestCase):
    def test_pix_without_fee_costs_the_listed_price(self):
        cost = estimate(1949.50, "BRL", MarketFees(fee_pct=0.0), SETTINGS, {})
        self.assertEqual(cost.listed_brl, 1949.50)
        self.assertEqual(cost.total_brl, 1949.50)
        self.assertTrue(cost.complete)
        self.assertEqual(cost.missing, [])

    def test_known_fees_push_a_1670_listing_to_1730(self):
        cost = estimate(1670.0, "BRL", MarketFees(fee_pct=0.0, fee_fixed=60.0), SETTINGS, {})
        self.assertEqual(cost.listed_brl, 1670.0)
        self.assertEqual(cost.total_brl, 1730.0)
        self.assertTrue(cost.complete)

    def test_percentage_fee_is_applied_on_the_listed_price(self):
        cost = estimate(1000.0, "BRL", MarketFees(fee_pct=2.5), SETTINGS, {})
        self.assertEqual(cost.total_brl, 1025.0)

    def test_brl_purchase_never_pays_iof_or_spread(self):
        cost = estimate(1000.0, "BRL", MarketFees(fee_pct=0.0), SETTINGS, {"USD": 5.5})
        self.assertEqual(cost.total_brl, 1000.0)

    def test_steam_balance_price_already_includes_fees(self):
        cost = estimate(2417.70, "BRL", MarketFees(pay_kind="saldo_steam", fee_pct=0.0), SETTINGS, {})
        self.assertEqual(cost.total_brl, 2417.70)
        self.assertTrue(cost.complete)


class ForeignCurrencyTests(unittest.TestCase):
    def test_card_purchase_adds_store_fee_spread_and_iof(self):
        cost = estimate(300.0, "USD", MarketFees(fee_pct=2.8, fee_fixed=0.30), SETTINGS, {"USD": 5.5})
        self.assertEqual(cost.listed_brl, 1650.00)
        # (300 * 1.028 + 0.30) * 5.5 = 1697.85 -> * 1.04 = 1765.764 -> * 1.035 = 1827.57
        self.assertEqual(cost.total_brl, 1827.57)
        self.assertTrue(cost.complete)

    def test_breakdown_parts_sum_to_the_total(self):
        cost = estimate(300.0, "USD", MarketFees(fee_pct=2.8, fee_fixed=0.30), SETTINGS, {"USD": 5.5})
        self.assertAlmostEqual(sum(v for _, v in cost.parts), cost.total_brl, places=1)

    def test_unknown_store_fee_gives_partial_total_marked_incomplete(self):
        cost = estimate(300.0, "USD", MarketFees(fee_pct=None), SETTINGS, {"USD": 5.5})
        # 300 * 5.5 = 1650 -> * 1.04 = 1716 -> * 1.035 = 1776.06
        self.assertEqual(cost.total_brl, 1776.06)
        self.assertFalse(cost.complete)
        self.assertTrue(any("taxa" in m for m in cost.missing))

    def test_missing_exchange_rate_gives_no_total(self):
        cost = estimate(300.0, "USD", MarketFees(fee_pct=2.8), SETTINGS, {})
        self.assertIsNone(cost.listed_brl)
        self.assertIsNone(cost.total_brl)
        self.assertFalse(cost.complete)
        self.assertTrue(any("câmbio" in m for m in cost.missing))

    def test_trade_offer_has_no_cash_total(self):
        cost = estimate(680.60, "USD", MarketFees(pay_kind="troca", fee_pct=0.0), SETTINGS, {"USD": 5.5})
        self.assertEqual(cost.listed_brl, 3743.30)
        self.assertEqual(cost.total_brl, 3743.30)
        self.assertFalse(cost.complete)
        self.assertTrue(any("troca" in m for m in cost.missing))


if __name__ == "__main__":
    unittest.main()
