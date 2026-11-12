"""Leitores de cada loja, testados contra respostas reais gravadas em tests/fixtures (exceto CSFloat com chave)."""
import json
import os
import unittest

from skinmon.sources import bleik, brskins, buffmarket, csfloat, dashskins_br, dashskins_gg, lisskins, marketcsgo, neshastore, pricempire, steam, tradeit, waxpeer

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
SKIN = "★ Skeleton Knife | Slaughter"


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def by_id(offers):
    return {o.offer_id: o for o in offers}


class DashskinsBrTests(unittest.TestCase):
    def setUp(self):
        self.offers = by_id(dashskins_br.parse(load("dashskins_br.json")))

    def test_every_listing_becomes_an_individual_offer(self):
        self.assertEqual(len(self.offers), 3)
        o = self.offers["6ac1c38f073bcfe5392f15b4"]
        self.assertEqual(o.name, SKIN + " (Minimal Wear)")
        self.assertEqual(o.price, 1949.5)
        self.assertEqual(o.currency, "BRL")
        self.assertAlmostEqual(o.float_value, 0.12051532417535782)
        self.assertEqual(o.link_kind, "offer")
        self.assertFalse(o.aggregated)

    def test_link_opens_the_individual_listing(self):
        self.assertEqual(
            self.offers["6ac1c38f073bcfe5392f15b4"].url,
            "https://dashskins.com.br/item/skeleton-knife-slaughter-minimal-wear/6ac1c38f073bcfe5392f15b4",
        )


class DashskinsGgTests(unittest.TestCase):
    def setUp(self):
        self.offers = by_id(dashskins_gg.parse(load("dashskins_gg.json")))

    def test_listings_carry_price_float_and_link(self):
        self.assertEqual(len(self.offers), 8)
        o = self.offers["ZiOmsWrcD-SImd"]
        self.assertEqual(o.price, 2100)
        self.assertEqual(o.currency, "BRL")
        self.assertAlmostEqual(o.float_value, 0.11736074090003967)
        self.assertEqual(o.url, "https://dashskins.gg/item/ZiOmsWrcD-SImd")
        self.assertEqual(o.link_kind, "offer")

    def test_stattrak_listing_keeps_its_full_name(self):
        self.assertEqual(self.offers["SWHtCUeaxaKWFS"].name, "★ StatTrak™ Skeleton Knife | Slaughter (Minimal Wear)")


class BrskinsTests(unittest.TestCase):
    def setUp(self):
        self.offers = by_id(brskins.parse(load("brskins.json")))

    def test_offer_uses_english_market_name_price_and_float(self):
        self.assertEqual(len(self.offers), 6)
        o = self.offers["3b725169-6e99-4b51-a02b-23293e6c789b"]
        self.assertEqual(o.name, SKIN + " (Minimal Wear)")
        self.assertEqual(o.price, 2207.43)
        self.assertEqual(o.currency, "BRL")
        self.assertAlmostEqual(o.float_value, 0.11169103533029556)
        self.assertEqual(o.url, "https://brskins.gg/market/item/3b725169-6e99-4b51-a02b-23293e6c789b")

    def test_manual_delivery_is_noted(self):
        self.assertIn("manual", self.offers["8ae0a68c-2a2b-4626-934d-1f249264aad5"].note.lower())
        self.assertEqual(self.offers["3b725169-6e99-4b51-a02b-23293e6c789b"].note, "")

    def test_stattrak_offer_is_named_as_stattrak(self):
        self.assertEqual(self.offers["0cbed1ed-0528-4e3e-955a-1c3b7407cd96"].name, "★ StatTrak™ Skeleton Knife | Slaughter (Minimal Wear)")


class BleikTests(unittest.TestCase):
    URL = "https://bleikstore.com/en/item/knives/skeleton-knife/skeleton-knife-slaughter"

    def test_product_page_gives_lowest_price_for_the_whole_skin(self):
        with open(os.path.join(FIX, "bleik_product.html"), encoding="utf-8") as f:
            o = bleik.parse_product(f.read(), self.URL)
        self.assertEqual(o.name, SKIN)
        self.assertEqual(o.price, 2238.55)
        self.assertEqual(o.currency, "BRL")
        self.assertEqual(o.quantity, 326)
        self.assertTrue(o.aggregated)
        self.assertEqual(o.link_kind, "search")
        self.assertEqual(o.url, self.URL)

    def test_page_without_product_data_gives_nothing(self):
        self.assertIsNone(bleik.parse_product("<html><body>manutenção</body></html>", self.URL))

    def test_sitemap_lookup_finds_the_product_by_slug(self):
        xml = ("<urlset><url><loc>https://bleikstore.com/en/item/knives/skeleton-knife/skeleton-knife-slaughter-x</loc></url>"
               "<url><loc>" + self.URL + "</loc></url></urlset>")
        self.assertEqual(bleik.find_product_url(xml, "skeleton-knife-slaughter"), self.URL)
        self.assertIsNone(bleik.find_product_url(xml, "ak-47-redline"))


class SteamTests(unittest.TestCase):
    def test_search_lists_every_variant_with_usd_price(self):
        rows = steam.parse_search(load("steam_search.json"))
        self.assertEqual(len(rows), 6)
        names = {r[0]: r for r in rows}
        self.assertEqual(names["★ StatTrak™ Skeleton Knife | Slaughter (Minimal Wear)"][1], 591.22)
        self.assertEqual(names["★ StatTrak™ Skeleton Knife | Slaughter (Minimal Wear)"][2], 4)

    def test_brl_price_text_is_parsed(self):
        self.assertEqual(steam.parse_brl("R$ 2.417,70"), 2417.70)
        self.assertEqual(steam.parse_brl("R$ 0,15"), 0.15)
        self.assertIsNone(steam.parse_brl(None))

    def test_overview_becomes_aggregated_offer_paid_with_steam_balance(self):
        o = steam.offer_from_overview(SKIN + " (Field-Tested)", {"success": True, "lowest_price": "R$ 2.417,70", "volume": "3"})
        self.assertEqual(o.price, 2417.70)
        self.assertEqual(o.currency, "BRL")
        self.assertTrue(o.aggregated)
        self.assertEqual(o.link_kind, "search")
        self.assertEqual(o.url, "https://steamcommunity.com/market/listings/730/%E2%98%85%20Skeleton%20Knife%20%7C%20Slaughter%20%28Field-Tested%29")

    def test_overview_without_price_gives_nothing(self):
        self.assertIsNone(steam.offer_from_overview(SKIN + " (Field-Tested)", {"success": True}))


class CsfloatTests(unittest.TestCase):
    def test_public_price_list_gives_reference_minimum_per_name(self):
        offers = {o.name: o for o in csfloat.parse_price_list(load("csfloat_price_list.json"), [SKIN])}
        self.assertEqual(len(offers), 6)
        o = offers[SKIN + " (Minimal Wear)"]
        self.assertEqual(o.price, 301.60)
        self.assertEqual(o.currency, "USD")
        self.assertEqual(o.quantity, 74)
        self.assertTrue(o.aggregated)
        self.assertEqual(o.link_kind, "search")

    def test_price_list_offer_warns_that_the_price_is_a_delayed_reference(self):
        o = csfloat.parse_price_list(load("csfloat_price_list.json"), [SKIN])[0]
        self.assertIn("referência", o.note)
        self.assertIn("1 vez por hora", o.note)

    def test_listings_with_key_become_individual_buy_now_offers(self):
        offers = csfloat.parse_listings(load("csfloat_listings_doc_shape.json"))
        self.assertEqual(len(offers), 1)  # leilão fica de fora
        o = offers[0]
        self.assertEqual(o.offer_id, "810000000000000001")
        self.assertEqual(o.price, 299.00)
        self.assertEqual(o.currency, "USD")
        self.assertEqual(o.float_value, 0.1123)
        self.assertEqual(o.url, "https://csfloat.com/item/810000000000000001")
        self.assertEqual(o.link_kind, "offer")

    def test_listings_also_accept_a_bare_array(self):
        data = load("csfloat_listings_doc_shape.json")["data"]
        self.assertEqual(len(csfloat.parse_listings(data)), 1)


class WaxpeerTests(unittest.TestCase):
    def test_minimum_is_converted_from_thousandths_of_dollar(self):
        offers = {o.name: o for o in waxpeer.parse(load("waxpeer.json"))}
        o = offers[SKIN + " (Factory New)"]  # na captura: min 394034, count 21
        self.assertEqual(o.price, 394.03)
        self.assertEqual(o.currency, "USD")
        self.assertEqual(o.quantity, 21)
        self.assertTrue(o.aggregated)
        self.assertEqual(o.link_kind, "search")


class TradeitTests(unittest.TestCase):
    def test_store_mode_uses_the_cash_store_price(self):
        offers = by_id(tradeit.parse(load("tradeit.json"), "store"))
        o = offers["54343506786"]
        self.assertEqual(o.name, "★ StatTrak™ Skeleton Knife | Slaughter (Field-Tested)")
        self.assertEqual(o.price, 385.84)
        self.assertEqual(o.currency, "USD")
        self.assertAlmostEqual(o.float_value, 0.2498210072517395)
        self.assertEqual(o.link_kind, "search")

    def test_trade_mode_uses_the_trade_value(self):
        offers = by_id(tradeit.parse(load("tradeit.json"), "trade"))
        self.assertEqual(offers["54343506786"].price, 680.60)

    def test_grouped_entry_without_asset_gets_a_group_id(self):
        offers = by_id(tradeit.parse(load("tradeit.json"), "store"))
        self.assertIn("g319427", offers)
        self.assertEqual(offers["g319427"].price, 375.86)


class BulkListTests(unittest.TestCase):
    LIS = [
        {"name": "★ Skeleton Knife | Slaughter (Minimal Wear)", "price": 323.43, "unlocked_price": 323.43,
         "url": "https://lis-skins.com/market/csgo/%E2%98%85-skeleton-knife-slaughter-minimal-wear/", "count": 122},
        {"name": "AK-47 | Redline (Field-Tested)", "price": 31.2, "unlocked_price": 31.2,
         "url": "https://lis-skins.com/market/csgo/ak-47-redline-field-tested/", "count": 900},
    ]
    TM = {"success": True, "time": 1794417295, "currency": "USD", "items": [
        {"market_hash_name": "★ Skeleton Knife | Slaughter (Minimal Wear)", "volume": 32, "price": "343.470"},
        {"market_hash_name": "AK-47 | Redline (Field-Tested)", "volume": 500, "price": "30.100"},
    ]}

    def test_lisskins_keeps_only_wanted_skins(self):
        offers = lisskins.parse(self.LIS, [SKIN])
        self.assertEqual(len(offers), 1)
        o = offers[0]
        self.assertEqual(o.price, 323.43)
        self.assertEqual(o.currency, "USD")
        self.assertEqual(o.quantity, 122)
        self.assertEqual(o.url, self.LIS[0]["url"])
        self.assertTrue(o.aggregated)
        self.assertEqual(o.link_kind, "search")

    def test_marketcsgo_keeps_only_wanted_skins(self):
        offers = marketcsgo.parse(self.TM, [SKIN])
        self.assertEqual(len(offers), 1)
        o = offers[0]
        self.assertEqual(o.price, 343.47)
        self.assertEqual(o.currency, "USD")
        self.assertEqual(o.quantity, 32)
        self.assertTrue(o.aggregated)
        self.assertIn("market.csgo.com", o.url)


class NeshastoreTests(unittest.TestCase):
    NOW = 1_794_416_400.0  # 11/11/2026 14:00 em Brasília

    def setUp(self):
        self.offers = by_id(neshastore.parse(load("neshastore.json"), now=self.NOW))

    def test_listings_become_individual_offers_in_reais(self):
        self.assertEqual(len(self.offers), 4)
        o = self.offers["54489861378"]
        self.assertEqual(o.name, "★ Kukri Knife | Slaughter (Field-Tested)")
        self.assertEqual(o.price, 590.19)
        self.assertEqual(o.currency, "BRL")
        self.assertAlmostEqual(o.float_value, 0.2476738542318344)
        self.assertEqual(o.link_kind, "offer")
        self.assertFalse(o.aggregated)

    def test_link_opens_the_item_page(self):
        self.assertEqual(self.offers["54489861378"].url,
                         "https://neshastore.com/csgo/facas/faca-kukri/massacre-ft?itemId=54489861378")

    def test_stattrak_link_has_the_stattrak_prefix(self):
        self.assertEqual(self.offers["54446924840"].url,
                         "https://neshastore.com/csgo/facas/faca-esqueleto/stattrak-revestimento-enferrujado-bs?itemId=54446924840")

    def test_trade_lock_in_the_future_is_noted(self):
        self.assertIn("17/11/2026", self.offers["54489861378"].note)

    def test_expired_trade_lock_is_not_noted(self):
        later = by_id(neshastore.parse(load("neshastore.json"), now=self.NOW + 30 * 86400))
        self.assertEqual(later["54489861378"].note, "")

    def test_unknown_item_type_falls_back_to_the_store_search(self):
        payload = load("neshastore.json")
        payload["items"][0]["type"] = 999
        o = by_id(neshastore.parse(payload, now=self.NOW))["54515379259"]
        self.assertEqual(o.link_kind, "search")
        self.assertTrue(o.url.startswith("https://neshastore.com/"))


class BuffmarketTests(unittest.TestCase):
    def setUp(self):
        from skinmon import net
        from skinmon.models import Alert
        from skinmon.sources.base import Ctx

        self.net, self.Ctx, self.Alert = net, Ctx, Alert
        self.fix = load("buffmarket.json")
        self.calls = []

    def fetch(self, url, **kw):
        self.calls.append(url)
        if url.startswith(buffmarket.INFO):
            payload = self.fix["info_mw"] if "Minimal%20Wear" in url and "StatTrak" not in url else self.fix["info_missing"]
        else:
            payload = self.fix["sell_order"]
        return self.net.Response(200, {}, json.dumps(payload).encode())

    def test_info_gives_item_id_minimum_and_count(self):
        self.assertEqual(buffmarket.parse_info(self.fix["info_mw"]), (1569, 309.4, 107))

    def test_unknown_variant_gives_nothing(self):
        self.assertIsNone(buffmarket.parse_info(self.fix["info_missing"]))

    def test_sell_orders_become_individual_offers_with_float(self):
        offers = buffmarket.parse_orders(self.fix["sell_order"], SKIN + " (Minimal Wear)")
        self.assertEqual(len(offers), 4)
        o = offers[0]
        self.assertEqual(o.offer_id, "1091009811-1B1B-137406502")
        self.assertEqual(o.price, 309.4)
        self.assertEqual(o.currency, "USD")
        self.assertAlmostEqual(o.float_value, 0.1364775449037552)
        self.assertFalse(o.aggregated)
        self.assertEqual(o.link_kind, "search")
        self.assertEqual(o.url, "https://buff.market/market/goods/cs2/%E2%98%85%20Skeleton%20Knife%20%7C%20Slaughter%20%28Minimal%20Wear%29")

    def test_candidate_names_follow_the_alert_filters(self):
        alert = self.Alert(id=1, name=SKIN, max_price=1700.0, wears=("FN", "MW"), stattrak="any")
        self.assertEqual(buffmarket.candidate_names(alert), [
            "★ Skeleton Knife | Slaughter (Factory New)", "★ StatTrak™ Skeleton Knife | Slaughter (Factory New)",
            "★ Skeleton Knife | Slaughter (Minimal Wear)", "★ StatTrak™ Skeleton Knife | Slaughter (Minimal Wear)",
        ])
        plain = self.Alert(id=2, name="AK-47 | Redline", max_price=100.0, wears=("FT",), stattrak="exclude")
        self.assertEqual(buffmarket.candidate_names(plain), ["AK-47 | Redline (Field-Tested)"])

    def test_variant_near_the_ceiling_gets_its_cheapest_listings(self):
        source = buffmarket.Buffmarket(env={}, fetch=self.fetch, sleep=lambda s: None)
        alert = self.Alert(id=1, name=SKIN, max_price=1700.0)
        offers = source.search(alert, self.Ctx(fx={"USD": 5.5}))  # 309,40 × 5,5 = 1.701,70: perto do teto
        self.assertEqual(sum(1 for c in self.calls if c.startswith(buffmarket.ORDERS)), 1)
        self.assertIn("goods_id=1569", [c for c in self.calls if c.startswith(buffmarket.ORDERS)][0])
        self.assertEqual(len(offers), 4)
        self.assertTrue(all(not o.aggregated for o in offers))

    def test_variant_far_from_the_ceiling_keeps_only_the_reference_minimum(self):
        source = buffmarket.Buffmarket(env={}, fetch=self.fetch, sleep=lambda s: None)
        alert = self.Alert(id=1, name=SKIN, max_price=1000.0)
        offers = source.search(alert, self.Ctx(fx={"USD": 5.5}))
        self.assertFalse(any(c.startswith(buffmarket.ORDERS) for c in self.calls))
        self.assertEqual(len(offers), 1)
        self.assertTrue(offers[0].aggregated)
        self.assertEqual(offers[0].price, 309.4)
        self.assertEqual(offers[0].quantity, 107)


class PricempireCsmoneyTests(unittest.TestCase):
    """Formato da documentação pública da Pricempire; não é captura real (exige a sua chave)."""

    def setUp(self):
        from skinmon import net
        from skinmon.models import Alert
        from skinmon.sources.base import Ctx

        self.net, self.Ctx = net, Ctx
        self.alert = Alert(id=1, name=SKIN, max_price=1700.0)
        self.calls = []

    def fetch(self, url, **kw):
        self.calls.append((url, kw.get("headers") or {}))
        return self.net.Response(200, {}, json.dumps(load("pricempire_doc_shape.json")).encode())

    def test_csmoney_minimum_is_read_in_dollars_with_its_timestamp(self):
        offers = pricempire.parse(load("pricempire_doc_shape.json"), [SKIN])
        self.assertEqual(len(offers), 1)
        o = offers[0]
        self.assertEqual(o.source, "csmoney")
        self.assertEqual(o.name, SKIN + " (Minimal Wear)")
        self.assertEqual(o.price, 317.50)
        self.assertEqual(o.currency, "USD")
        self.assertEqual(o.quantity, 58)
        self.assertTrue(o.aggregated)
        self.assertEqual(o.link_kind, "search")
        self.assertEqual(o.data_time, 1_794_500_400.0)  # 12/11/2026 16:20 UTC
        self.assertTrue(o.url.startswith("https://cs.money/market/buy/?"))

    def test_request_uses_the_key_and_asks_only_for_csmoney(self):
        source = pricempire.PricempireCsmoney(env={"PRICEMPIRE_API_KEY": "chave"}, fetch=self.fetch, sleep=lambda s: None)
        result = source.poll([self.alert], self.Ctx(fx={"USD": 5.5}))
        url, headers = self.calls[0]
        self.assertIn("sources=csmoney", url)
        self.assertEqual(headers.get("Authorization"), "Bearer chave")
        self.assertEqual(len(result.offers[1]), 1)

    def test_without_key_nothing_is_requested(self):
        source = pricempire.PricempireCsmoney(env={}, fetch=self.fetch, sleep=lambda s: None)
        ctx = self.Ctx(fx={"USD": 5.5})
        result = source.poll([self.alert], ctx)
        self.assertEqual(self.calls, [])
        self.assertEqual(result.errors, [])
        self.assertTrue(any("PRICEMPIRE_API_KEY" in n for n in ctx.notes))

    def test_interval_fits_the_free_monthly_quota(self):
        source = pricempire.PricempireCsmoney(env={"PRICEMPIRE_API_KEY": "chave"})
        self.assertLessEqual(30 * 86400 / source.interval, 1000)


class DataAgeTests(unittest.TestCase):
    def test_csfloat_reference_carries_the_list_timestamp(self):
        offers = csfloat.parse_price_list(load("csfloat_price_list.json"), [SKIN], data_time=1_794_410_000.0)
        self.assertTrue(all(o.data_time == 1_794_410_000.0 for o in offers))

    def test_marketcsgo_reference_carries_the_file_timestamp(self):
        offers = marketcsgo.parse(BulkListTests.TM, [SKIN])
        self.assertEqual(offers[0].data_time, 1794417295)

    def test_http_date_is_parsed(self):
        from skinmon import net
        self.assertEqual(net.parse_http_date("Wed, 11 Nov 2026 16:28:15 GMT"), 1_794_414_495.0)
        self.assertIsNone(net.parse_http_date("ontem"))
        self.assertIsNone(net.parse_http_date(None))


class CsfloatKeyTests(unittest.TestCase):
    """Com a chave, cada variação da skin é consultada na API oficial de anúncios."""

    def setUp(self):
        from skinmon import net
        from skinmon.models import Alert
        from skinmon.sources.base import Ctx

        self.net, self.Ctx = net, Ctx
        self.calls = []
        self.source = csfloat.Csfloat(env={"CSFLOAT_API_KEY": "chave-de-teste"}, fetch=self.fetch, sleep=lambda s: None)
        self.alert = Alert(id=1, name=SKIN, max_price=1700.0)

    def fetch(self, url, **kw):
        self.calls.append((url, kw.get("headers") or {}))
        if url.startswith(csfloat.PRICE_LIST):
            return self.net.Response(200, {"last-modified": "Wed, 11 Nov 2026 16:28:15 GMT"},
                                     json.dumps(load("csfloat_price_list.json")).encode())
        return self.net.Response(200, {}, json.dumps(load("csfloat_listings_doc_shape.json")).encode())

    def test_listings_are_requested_with_the_key_for_each_variant(self):
        result = self.source.poll([self.alert], self.Ctx(fx={"USD": 5.5}))
        listing_calls = [c for c in self.calls if c[0].startswith(csfloat.LISTINGS + "?")]
        self.assertEqual(len(listing_calls), 6)
        self.assertTrue(all(h.get("Authorization") == "chave-de-teste" for _, h in listing_calls))
        self.assertTrue(all("type=buy_now" in u and "sort_by=lowest_price" in u for u, _ in listing_calls))
        self.assertTrue(all(o.link_kind == "offer" for o in result.offers[1]))

    def test_listing_query_is_capped_at_the_ceiling_in_dollars(self):
        self.source.poll([self.alert], self.Ctx(fx={"USD": 5.0}))
        url = [c[0] for c in self.calls if c[0].startswith(csfloat.LISTINGS + "?")][0]
        self.assertIn("max_price=34000", url)  # R$ 1.700 / 5,0 = US$ 340,00

    def test_without_exchange_rate_the_query_has_no_cap(self):
        self.source.poll([self.alert], self.Ctx(fx={}))
        url = [c[0] for c in self.calls if c[0].startswith(csfloat.LISTINGS + "?")][0]
        self.assertNotIn("max_price", url)

    def test_without_key_only_the_reference_list_is_read(self):
        source = csfloat.Csfloat(env={}, fetch=self.fetch, sleep=lambda s: None)
        result = source.poll([self.alert], self.Ctx(fx={"USD": 5.5}))
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(all(o.aggregated for o in result.offers[1]))
        self.assertTrue(all(o.data_time == 1_794_414_495.0 for o in result.offers[1]))


class BulkDownloadTests(unittest.TestCase):
    """O arquivo grande só é baixado de novo quando muda; em memória ficam só as skins monitoradas."""

    def setUp(self):
        from skinmon import net
        from skinmon.models import Alert
        from skinmon.sources.base import Ctx

        self.net, self.Ctx = net, Ctx
        self.requests = []
        self.changed = True
        self.source = lisskins.Lisskins(env={}, fetch=self.fetch, sleep=lambda s: None)
        self.knife = Alert(id=1, name=SKIN, max_price=1700.0)
        self.rifle = Alert(id=2, name="AK-47 | Redline", max_price=100.0)

    def fetch(self, url, **kw):
        self.requests.append(kw.get("etag"))
        if kw.get("etag") and not self.changed:
            return self.net.Response(304, {}, b"")
        return self.net.Response(200, {"etag": '"v1"'}, json.dumps(BulkListTests.LIS).encode())

    def test_first_poll_downloads_and_returns_the_monitored_skin(self):
        result = self.source.poll([self.knife], self.Ctx())
        self.assertEqual([o.name for o in result.offers[1]], [SKIN + " (Minimal Wear)"])
        self.assertEqual(self.requests, [None])

    def test_unchanged_file_is_not_downloaded_again(self):
        self.source.poll([self.knife], self.Ctx())
        self.changed = False
        result = self.source.poll([self.knife], self.Ctx())
        self.assertEqual(self.requests, [None, '"v1"'])
        self.assertEqual(len(result.offers[1]), 1)

    def test_new_alert_forces_a_full_download(self):
        self.source.poll([self.knife], self.Ctx())
        self.changed = False
        result = self.source.poll([self.knife, self.rifle], self.Ctx())
        self.assertEqual(self.requests, [None, None])
        self.assertEqual({o.name for o in result.offers[2]}, {SKIN + " (Minimal Wear)", "AK-47 | Redline (Field-Tested)"})

    def test_only_monitored_skins_are_kept_in_memory(self):
        self.source.poll([self.knife], self.Ctx())
        kept = [v for v in vars(self.source).values() if isinstance(v, list)]
        self.assertTrue(all(len(v) <= 1 for v in kept))


if __name__ == "__main__":
    unittest.main()
