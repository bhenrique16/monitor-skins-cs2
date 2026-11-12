import unittest
from dataclasses import replace

from skinmon.mailer import AlertItem, brasilia_time, delivery_text, format_brl, format_money, mask_address, render_alert
from skinmon.models import Alert, MarketInfo, Offer
from skinmon.pricing import CostSettings, MarketFees, estimate

SKIN = "★ Skeleton Knife | Slaughter"
ALERT = Alert(id=1, name=SKIN, max_price=1700.0)
SETTINGS = CostSettings(iof_pct=3.5, spread_pct=4.0)
DASH = MarketInfo(id="dashskins_br", label="DashSkins.com.br", currency="BRL", pay_kind="dinheiro", pay_note="PIX")
NOW = 1_794_416_400.0  # 2026-11-11 17:00:00 UTC = 14:00:00 em Brasília
URL = "https://dashskins.com.br/item/skeleton-knife-slaughter-minimal-wear/6ac1c38f073bcfe5392f15b4"


def item(price=1650.0, currency="BRL", fees=MarketFees(fee_pct=0.0), fx=None, reason="novo", previous=None, **offer_kw):
    kw = dict(source="dashskins_br", offer_id="6ac1", name=SKIN + " (Minimal Wear)", price=price, currency=currency,
              url=URL, float_value=0.12051532417535782)
    kw.update(offer_kw)
    off = Offer(**kw)
    return AlertItem(offer=off, cost=estimate(price, currency, fees, SETTINGS, fx or {}), reason=reason, previous_price=previous)


class FormatTests(unittest.TestCase):
    def test_brl_uses_brazilian_separators(self):
        self.assertEqual(format_brl(1700), "R$ 1.700,00")
        self.assertEqual(format_brl(1949.5), "R$ 1.949,50")
        self.assertEqual(format_brl(0.5), "R$ 0,50")
        self.assertEqual(format_brl(1234567.891), "R$ 1.234.567,89")

    def test_foreign_currencies_get_their_symbol(self):
        self.assertEqual(format_money(300, "USD"), "US$ 300,00")
        self.assertEqual(format_money(300, "EUR"), "€ 300,00")
        self.assertEqual(format_money(300, "BRL"), "R$ 300,00")

    def test_timestamp_is_shown_in_brasilia_time(self):
        self.assertEqual(brasilia_time(NOW), "11/11/2026 14:00:00")


class ReferencePriceTests(unittest.TestCase):
    def test_subject_marks_reference_prices(self):
        subject, _, _ = render_alert(ALERT, DASH, [item(link_kind="search", aggregated=True)], NOW)
        self.assertTrue(subject.endswith("DashSkins.com.br (preço de referência)"))

    def test_reason_line_says_reference_instead_of_new_listing(self):
        _, text, html = render_alert(ALERT, DASH, [item(link_kind="search", aggregated=True)], NOW)
        for part in (text, html):
            self.assertIn("Preço de referência na DashSkins.com.br", part)
            self.assertNotIn("Novo anúncio", part)

    def test_old_store_data_shows_its_age(self):
        _, text, html = render_alert(ALERT, DASH, [item(link_kind="search", aggregated=True, data_time=NOW - 75 * 60)], NOW)
        for part in (text, html):
            self.assertIn("11/11/2026 12:45", part)
            self.assertIn("há 75 min", part)

    def test_fresh_store_data_does_not_show_its_age(self):
        _, text, _ = render_alert(ALERT, DASH, [item(data_time=NOW - 60)], NOW)
        self.assertNotIn("Dados da loja de", text)


class MaskAddressTests(unittest.TestCase):
    """O destino gravado no banco não pode expor o e-mail (o banco fica no GitHub)."""

    def test_local_part_is_hidden(self):
        self.assertEqual(mask_address("fulano.silva@gmail.com"), "f***@gmail.com")

    def test_several_recipients_are_all_masked(self):
        self.assertEqual(mask_address("a@x.com, bob@y.com"), "a***@x.com, b***@y.com")

    def test_text_without_address_is_kept(self):
        self.assertEqual(mask_address("arquivo data/outbox/x.html"), "arquivo data/outbox/x.html")


class DeliveryTextTests(unittest.TestCase):
    def test_real_delivery_names_the_recipient(self):
        self.assertEqual(delivery_text("eu@exemplo.com"), "enviado para eu@exemplo.com")

    def test_file_delivery_says_that_nothing_was_sent(self):
        text = delivery_text("arquivo data/outbox/x.html")
        self.assertIn("gravado em data/outbox/x.html", text)
        self.assertIn("SMTP não configurado", text)
        self.assertNotIn("enviado", text)


class RenderTests(unittest.TestCase):
    def test_subject_has_skin_price_and_store(self):
        subject, _, _ = render_alert(ALERT, DASH, [item()], NOW)
        self.assertEqual(subject, "★ Skeleton Knife | Slaughter (MW) — R$ 1.650,00 total — DashSkins.com.br")

    def test_subject_counts_the_other_offers(self):
        subject, _, _ = render_alert(ALERT, DASH, [item(), item(price=1660.0, offer_id="b")], NOW)
        self.assertTrue(subject.endswith("DashSkins.com.br (+1)"))

    def test_subject_uses_listed_price_when_the_alert_is_on_listed_basis(self):
        subject, _, _ = render_alert(replace(ALERT, basis="listed"), DASH, [item(fees=MarketFees(fee_pct=0.0, fee_fixed=40.0))], NOW)
        self.assertIn("R$ 1.650,00 anunciado", subject)

    def test_body_shows_wear_float_prices_time_and_button(self):
        _, text, html = render_alert(ALERT, DASH, [item()], NOW)
        for part in (text, html):
            self.assertIn("Pouco Usada (MW)", part)
            self.assertIn("0.1205", part)
            self.assertIn("R$ 1.650,00", part)
            self.assertIn("11/11/2026 14:00:00", part)
            self.assertIn(URL, part)
        self.assertIn(">Abrir oferta<", html)
        self.assertNotIn("Ver ofertas na loja", html)

    def test_search_link_changes_the_button_label(self):
        _, text, html = render_alert(ALERT, DASH, [item(link_kind="search", aggregated=True)], NOW)
        self.assertIn(">Ver ofertas na loja<", html)
        self.assertNotIn(">Abrir oferta<", html)
        self.assertIn("Ver ofertas na loja", text)

    def test_notes_about_the_offer_share_a_single_row(self):
        it = item(link_kind="search", aggregated=True, quantity=119, note="Entrega manual pelo vendedor.")
        _, text, html = render_alert(ALERT, DASH, [it], NOW)
        self.assertEqual(html.count(">Observação<"), 1)
        for part in (text, html):
            self.assertIn("119 anúncios", part)
            self.assertIn("Entrega manual pelo vendedor.", part)

    def test_missing_float_is_stated(self):
        _, text, html = render_alert(ALERT, DASH, [item(float_value=None)], NOW)
        self.assertIn("não informado", html)
        self.assertIn("não informado", text)

    def test_total_with_fees_is_shown_next_to_the_listed_price(self):
        _, text, html = render_alert(ALERT, DASH, [item(price=1600.0, fees=MarketFees(fee_pct=0.0, fee_fixed=60.0))], NOW)
        for part in (text, html):
            self.assertIn("R$ 1.600,00", part)
            self.assertIn("R$ 1.660,00", part)

    def test_foreign_offer_shows_native_converted_and_total_values(self):
        csfloat = MarketInfo(id="csfloat", label="CSFloat", currency="USD", pay_kind="dinheiro", pay_note="cartão internacional")
        it = item(price=280.0, currency="USD", fees=MarketFees(fee_pct=2.8, fee_fixed=0.30), fx={"USD": 5.5})
        subject, text, html = render_alert(ALERT, csfloat, [it], NOW)
        self.assertIn("US$ 280,00", html)
        self.assertIn("R$ 1.540,00", html)
        self.assertIn(format_brl(it.cost.total_brl), html)
        self.assertIn(format_brl(it.cost.total_brl) + " total", subject)
        self.assertIn("IOF", html)

    def test_incomplete_total_is_flagged(self):
        it = item(price=280.0, currency="USD", fees=MarketFees(fee_pct=None), fx={"USD": 5.5})
        _, text, html = render_alert(ALERT, DASH, [it], NOW)
        self.assertIn("Total incompleto", html)
        self.assertIn("Total incompleto", text)

    def test_price_drop_shows_the_previous_price(self):
        _, text, html = render_alert(ALERT, DASH, [item(reason="baixou", previous=1800.0)], NOW)
        self.assertIn("Baixou de preço", html)
        self.assertIn("R$ 1.800,00", html)
        self.assertIn("R$ 1.800,00", text)

    def test_payment_kind_is_labelled(self):
        steam = MarketInfo(id="steam", label="Steam", currency="BRL", pay_kind="saldo_steam", pay_note="saldo da carteira Steam")
        _, text, html = render_alert(ALERT, steam, [item(link_kind="search", aggregated=True)], NOW)
        self.assertIn("Saldo Steam", html)
        self.assertIn("Saldo Steam", text)

    def test_all_offers_of_the_poll_are_listed_with_their_links(self):
        other = "https://dashskins.com.br/item/x/b"
        _, text, html = render_alert(ALERT, DASH, [item(), item(price=1660.0, offer_id="b", url=other)], NOW)
        self.assertIn(other, html)
        self.assertIn(other, text)
        self.assertIn("R$ 1.660,00", html)

    def test_dynamic_text_is_html_escaped(self):
        _, _, html = render_alert(ALERT, DASH, [item(name='<script>alert(1)</script> | X (Minimal Wear)')], NOW)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_ceiling_and_basis_are_stated(self):
        _, text, html = render_alert(ALERT, DASH, [item()], NOW)
        self.assertIn("R$ 1.700,00", html)
        self.assertIn("R$ 1.700,00", text)


if __name__ == "__main__":
    unittest.main()
