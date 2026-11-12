import json
import unittest

from skinmon import fx, net
from skinmon.db import DB

AWESOME = {"USDBRL": {"bid": "5.5621", "ask": "5.5645"}, "EURBRL": {"bid": "6.1675", "ask": "6.1695"}}
ER_API = {"result": "success", "rates": {"BRL": 5.553906, "EUR": 0.893927}}


class FakeFetch:
    def __init__(self, primary=AWESOME, fallback=ER_API):
        self.primary, self.fallback, self.calls = primary, fallback, []

    def __call__(self, url, **kw):
        self.calls.append(url)
        payload = self.primary if url == fx.PRIMARY else self.fallback
        if payload is None:
            raise net.HttpError(0, url, "sem rede")
        return net.Response(200, {}, json.dumps(payload).encode())


class FxTests(unittest.TestCase):
    def setUp(self):
        self.db = DB(":memory:", seed=False)
        self.clock = [1_794_416_400.0]

    def tearDown(self):
        self.db.close()

    def make(self, fetch):
        return fx.Fx(self.db, fetch=fetch, now=lambda: self.clock[0])

    def test_primary_source_gives_the_selling_rate(self):
        rates = self.make(FakeFetch()).rates()
        self.assertEqual(rates, {"USD": 5.5645, "EUR": 6.1695})

    def test_fallback_is_used_when_the_primary_fails(self):
        rates = self.make(FakeFetch(primary=None)).rates()
        self.assertAlmostEqual(rates["USD"], 5.553906)
        self.assertAlmostEqual(rates["EUR"], 5.553906 / 0.893927)

    def test_rates_are_reused_inside_the_cache_window(self):
        fetch = FakeFetch()
        service = self.make(fetch)
        service.rates()
        self.clock[0] += 120
        service.rates()
        self.assertEqual(len(fetch.calls), 1)

    def test_rates_are_refreshed_after_the_cache_window(self):
        fetch = FakeFetch()
        service = self.make(fetch)
        service.rates()
        self.clock[0] += fx.TTL + 1
        service.rates()
        self.assertEqual(len(fetch.calls), 2)

    def test_last_known_rate_survives_a_restart_and_an_outage(self):
        self.make(FakeFetch()).rates()
        self.clock[0] += 3600
        rates = self.make(FakeFetch(primary=None, fallback=None)).rates()
        self.assertEqual(rates["USD"], 5.5645)

    def test_new_process_reuses_a_recent_rate_without_fetching(self):
        self.make(FakeFetch()).rates()
        self.clock[0] += 120
        fetch = FakeFetch()
        self.assertEqual(self.make(fetch).rates()["USD"], 5.5645)
        self.assertEqual(fetch.calls, [])

    def test_rate_older_than_a_day_is_not_used(self):
        self.make(FakeFetch()).rates()
        self.clock[0] += fx.MAX_AGE + 60
        self.assertEqual(self.make(FakeFetch(primary=None, fallback=None)).rates(), {})

    def test_no_source_and_nothing_stored_gives_no_rates(self):
        self.assertEqual(self.make(FakeFetch(primary=None, fallback=None)).rates(), {})


if __name__ == "__main__":
    unittest.main()
