import base64
import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

from skinmon import config
from skinmon.db import DB
from skinmon.panel import Panel, parse_price
from skinmon.sources.base import Source

SKIN = "★ Skeleton Knife | Slaughter"


class LojaA(Source):
    id = "loja_a"
    label = "Loja A"
    pay_note = "PIX"
    data_note = "API de teste."


class LojaB(Source):
    id = "loja_b"
    label = "Loja B"
    currency = "USD"
    default_fee_pct = None
    link_kind = "search"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class PanelCase(unittest.TestCase):
    password = ""

    def setUp(self):
        self.db = DB(":memory:", seed=False)
        self.alert_id = self.db.add_alert(SKIN, 1700.0)
        self.tests_sent = []
        self.panel = Panel(self.db, [LojaA(env={}), LojaB(env={})], send_test=self.send_test, mail_info="SMTP de teste",
                           fx_state=lambda: {"rates": {"USD": 5.5645}, "at": 1_794_416_400.0, "source": "AwesomeAPI"},
                           password=self.password, now=lambda: 1_794_416_460.0)
        self.server = self.panel.serve("127.0.0.1", 0)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.opener = urllib.request.build_opener(NoRedirect)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.db.close()

    def send_test(self):
        self.tests_sent.append(1)
        return "destino@exemplo.com"

    def request(self, path, form=None, auth=None):
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        req = urllib.request.Request(self.base + path, data=data)
        if auth:
            req.add_header("Authorization", "Basic " + base64.b64encode(("admin:" + auth).encode()).decode())
        try:
            resp = self.opener.open(req, timeout=10)
            return resp.status, dict(resp.headers), resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, dict(exc.headers), exc.read().decode("utf-8")

    def token(self):
        _, _, body = self.request("/", auth=self.password or None)
        return re.search(r'name="csrf" value="([^"]+)"', body).group(1)

    def post(self, path, form):
        form = dict(form, csrf=self.token())
        return self.request(path, form, auth=self.password or None)


class PageTests(PanelCase):
    def test_page_lists_alerts_and_stores(self):
        status, _, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("★ Skeleton Knife | Slaughter", body)
        self.assertIn("Loja A", body)
        self.assertIn("Loja B", body)

    def test_page_shows_when_each_store_was_last_checked(self):
        self.db.set_status("loja_a", state="ok", last_poll=1_794_416_400.0, last_ok=1_794_416_400.0, matched=3, best_brl=1949.5, error="", note="")
        _, _, body = self.request("/")
        self.assertIn("14:00:00", body)
        self.assertIn("há 1 min", body)
        self.assertIn("R$ 1.949,50", body)

    def test_store_never_checked_says_so(self):
        _, _, body = self.request("/")
        self.assertIn("ainda não consultada", body)

    def test_store_error_is_visible(self):
        self.db.set_status("loja_b", state="erro", last_poll=1_794_416_400.0, error="HTTP 500 de loja.exemplo", fails=2)
        _, _, body = self.request("/")
        self.assertIn("HTTP 500 de loja.exemplo", body)

    def test_status_section_shows_the_last_successful_check(self):
        self.db.set_status("loja_a", state="erro", last_poll=1_794_416_400.0, last_ok=1_794_412_800.0, error="HTTP 502", fails=1)
        _, _, body = self.request("/")
        self.assertIn("Última consulta OK", body)
        self.assertIn("13:00:00", body)
        self.assertIn("há 1 h", body)

    def test_test_mode_is_announced_on_the_page(self):
        from skinmon import testmode
        testmode.start(self.db, 2000.0)
        _, _, body = self.request("/")
        self.assertIn("Modo de teste ativo", body)
        self.assertIn("R$ 2.000,00", body)

    def test_test_mode_can_be_ended_from_the_page(self):
        from skinmon import testmode
        testmode.start(self.db, 2000.0)
        status, headers, _ = self.post("/teste/encerrar", {})
        self.assertEqual(status, 303)
        self.assertIn("1.700,00", urllib.parse.unquote(headers["Location"]))
        self.assertEqual(self.db.get_alert(self.alert_id).max_price, 1700.0)
        self.assertFalse(testmode.state(self.db)["active"])

    def test_status_json_reports_each_store(self):
        self.db.set_status("loja_a", state="ok", last_poll=1_794_416_400.0)
        status, headers, body = self.request("/status.json")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["lojas"]["loja_a"]["state"], "ok")
        self.assertEqual(data["lojas"]["loja_a"]["last_poll"], 1_794_416_400.0)
        self.assertIn("loja_b", data["lojas"])


class AlertFormTests(PanelCase):
    def test_new_alert_is_created_from_the_form(self):
        status, headers, _ = self.post("/alertas/novo", {"name": "AK-47 | Redline (Field-Tested)", "max_price": "150,00"})
        self.assertEqual(status, 303)
        created = [a for a in self.db.alerts() if a.id != self.alert_id][0]
        self.assertEqual(created.name, "AK-47 | Redline")
        self.assertEqual(created.max_price, 150.0)
        self.assertEqual(created.basis, "total")

    def test_ceiling_can_be_changed_without_touching_code(self):
        self.post(f"/alertas/{self.alert_id}", {"name": SKIN, "max_price": "1.650,00", "basis": "listed", "stattrak": "exclude",
                                               "wear_FN": "on", "wear_MW": "on", "active": "on"})
        alert = self.db.get_alert(self.alert_id)
        self.assertEqual(alert.max_price, 1650.0)
        self.assertEqual(alert.basis, "listed")
        self.assertEqual(alert.stattrak, "exclude")
        self.assertEqual(alert.wears, ("FN", "MW"))
        self.assertFalse(alert.include_incomplete)
        self.assertTrue(alert.active)

    def test_unchecked_active_box_pauses_the_alert(self):
        self.post(f"/alertas/{self.alert_id}", {"name": SKIN, "max_price": "1700", "basis": "total", "stattrak": "any"})
        self.assertFalse(self.db.get_alert(self.alert_id).active)

    def test_invalid_price_is_rejected_with_a_message(self):
        status, headers, _ = self.post(f"/alertas/{self.alert_id}", {"name": SKIN, "max_price": "abc", "basis": "total", "stattrak": "any"})
        self.assertEqual(status, 303)
        self.assertIn("erro", headers["Location"])
        self.assertEqual(self.db.get_alert(self.alert_id).max_price, 1700.0)

    def test_alert_can_be_deleted(self):
        self.post(f"/alertas/{self.alert_id}/excluir", {})
        self.assertEqual(self.db.alerts(), [])

    def test_post_without_csrf_token_is_refused(self):
        status, _, _ = self.request("/alertas/novo", {"name": "AK-47 | Redline", "max_price": "150"})
        self.assertEqual(status, 403)
        self.assertEqual(len(self.db.alerts()), 1)


class StoreFormTests(PanelCase):
    def test_store_can_be_disabled_and_fees_edited(self):
        self.post("/lojas", {"enabled_loja_a": "on", "fee_pct_loja_a": "1,5", "fee_fixed_loja_a": "2",
                             "fee_pct_loja_b": "", "fee_fixed_loja_b": "0"})
        rows = self.db.market_overrides()
        self.assertEqual(rows["loja_a"]["enabled"], 1)
        self.assertEqual(rows["loja_a"]["fee_pct"], 1.5)
        self.assertEqual(rows["loja_a"]["fee_fixed"], 2.0)
        self.assertEqual(rows["loja_b"]["enabled"], 0)
        self.assertIsNone(rows["loja_b"]["fee_pct"])

    def test_purchase_costs_are_saved(self):
        self.post("/custos", {"iof_pct": "3,5", "spread_pct": "1,1", "aviso_falha": "on"})
        self.assertEqual(self.db.get_float("iof_pct", 0), 3.5)
        self.assertEqual(self.db.get_float("spread_pct", 0), 1.1)
        self.assertEqual(self.db.get("aviso_falha"), "1")

    def test_test_email_button_sends_and_reports_destination(self):
        status, headers, _ = self.post("/teste-email", {})
        self.assertEqual(status, 303)
        self.assertEqual(len(self.tests_sent), 1)
        self.assertIn("destino", urllib.parse.unquote(headers["Location"]))


class AuthTests(PanelCase):
    password = "segredo"

    def test_page_requires_the_password(self):
        status, headers, _ = self.request("/")
        self.assertEqual(status, 401)
        self.assertIn("Basic", headers["WWW-Authenticate"])

    def test_wrong_password_is_refused(self):
        status, _, _ = self.request("/", auth="errada")
        self.assertEqual(status, 401)

    def test_right_password_opens_the_page(self):
        status, _, body = self.request("/", auth="segredo")
        self.assertEqual(status, 200)
        self.assertIn("Loja A", body)

    def test_repeated_wrong_passwords_are_blocked_for_a_while(self):
        for _ in range(10):
            self.request("/", auth="errada")
        status, _, _ = self.request("/", auth="segredo")
        self.assertEqual(status, 429)

    def test_health_check_needs_no_password(self):
        status, _, body = self.request("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body.strip(), "ok")


class PriceParsingTests(unittest.TestCase):
    def test_brazilian_and_plain_formats(self):
        self.assertEqual(parse_price("1.700,00"), 1700.0)
        self.assertEqual(parse_price("1700"), 1700.0)
        self.assertEqual(parse_price("1700.50"), 1700.5)
        self.assertEqual(parse_price("1700,5"), 1700.5)
        self.assertEqual(parse_price("R$ 2.000"), 2000.0)
        self.assertEqual(parse_price("1.234.567,89"), 1234567.89)

    def test_invalid_or_non_positive_values_are_rejected(self):
        self.assertIsNone(parse_price("abc"))
        self.assertIsNone(parse_price(""))
        self.assertIsNone(parse_price("0"))
        self.assertIsNone(parse_price("-5"))


class EnvFileTests(unittest.TestCase):
    def test_env_file_fills_missing_variables_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# comentário\nSMTP_HOST=smtp.gmail.com\nSMTP_PASS=\"abcd efgh\"\n\nMAIL_TO = eu@exemplo.com \nJA_DEFINIDA=arquivo\n")
            env = {"JA_DEFINIDA": "ambiente"}
            config.load_env(path, env)
        self.assertEqual(env["SMTP_HOST"], "smtp.gmail.com")
        self.assertEqual(env["SMTP_PASS"], "abcd efgh")
        self.assertEqual(env["MAIL_TO"], "eu@exemplo.com")
        self.assertEqual(env["JA_DEFINIDA"], "ambiente")

    def test_missing_env_file_is_fine(self):
        env = {}
        config.load_env(os.path.join(tempfile.gettempdir(), "nao-existe-skinmon.env"), env)
        self.assertEqual(env, {})


if __name__ == "__main__":
    unittest.main()
