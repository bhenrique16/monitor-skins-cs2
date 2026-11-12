import gzip
import unittest

from skinmon import net


class ErrorDetailTests(unittest.TestCase):
    def test_json_error_shows_only_its_title(self):
        body = b'{"type":"https://developers.cloudflare.com/support/x","title":"Error 502: Bad gateway","status":502}'
        self.assertEqual(net.error_detail(body), "Error 502: Bad gateway")

    def test_json_validation_messages_are_joined(self):
        body = b'{"message":["property search should not exist","pageSize must be an integer number"],"error":"Bad Request"}'
        self.assertEqual(net.error_detail(body), "property search should not exist; pageSize must be an integer number")

    def test_html_error_page_is_not_dumped(self):
        self.assertEqual(net.error_detail(b"<!DOCTYPE html><html><head><title>Attention Required!</title>"), "página de erro")

    def test_plain_text_is_shortened(self):
        self.assertEqual(net.error_detail(b"x" * 500), "x" * 120)

    def test_empty_body_gives_no_detail(self):
        self.assertEqual(net.error_detail(b""), "")


class DecodingTests(unittest.TestCase):
    def test_body_compressed_twice_is_fully_decoded(self):
        self.assertEqual(net.decode_body(gzip.compress(gzip.compress(b'[{"a":1}]'))), b'[{"a":1}]')

    def test_plain_body_is_left_alone(self):
        self.assertEqual(net.decode_body(b'{"a":1}'), b'{"a":1}')


class QueryTests(unittest.TestCase):
    def test_spaces_are_encoded_as_percent_twenty(self):
        self.assertEqual(net.query({"search": "skeleton knife | slaughter", "limit": 50}), "search=skeleton%20knife%20%7C%20slaughter&limit=50")


class ErrorMessageTests(unittest.TestCase):
    def test_http_error_names_status_and_host(self):
        self.assertEqual(str(net.HttpError(502, "https://brskins.gg/api/x?name=y", "Error 502: Bad gateway")),
                         "HTTP 502 de brskins.gg: Error 502: Bad gateway")

    def test_network_failure_has_no_status(self):
        self.assertEqual(str(net.HttpError(0, "https://brskins.gg/api/x", "timed out")), "sem resposta de brskins.gg: timed out")

    def test_rate_limit_keeps_the_suggested_wait(self):
        exc = net.RateLimited("https://steamcommunity.com/market/x", 120.0)
        self.assertEqual(exc.status, 429)
        self.assertEqual(exc.retry_after, 120.0)


if __name__ == "__main__":
    unittest.main()
