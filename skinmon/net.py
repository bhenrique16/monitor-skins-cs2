"""Cliente HTTP mínimo (biblioteca padrão), com identificação honesta e erros curtos."""
from __future__ import annotations

import email.utils
import gzip
import json
import urllib.error
import urllib.parse
import urllib.request

# O monitor se identifica como o que é. Nenhuma loja integrada exige fingir ser navegador.
USER_AGENT = "skinmon/1.0 (monitor pessoal de precos; consulta de baixa frequencia)"
MAX_BYTES = 40_000_000


class HttpError(Exception):
    def __init__(self, status: int, url: str, detail: str = ""):
        self.status, self.url, self.detail = status, url, detail
        host = urllib.parse.urlsplit(url).netloc
        what = f"HTTP {status}" if status else "sem resposta"
        super().__init__(f"{what} de {host}" + (f": {detail}" if detail else ""))


class RateLimited(HttpError):
    def __init__(self, url: str, retry_after: float | None = None):
        super().__init__(429, url, "limite de requisições atingido")
        self.retry_after = retry_after


class Response:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status, self.headers, self.body = status, headers, body

    def header(self, name: str, default=None):
        return self.headers.get(name.lower(), default)

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self):
        try:
            return json.loads(self.body)
        except ValueError as exc:
            raise HttpError(self.status, "", "resposta não é JSON válido") from exc


def query(params: dict) -> str:
    """Query string com espaços como %20 (igual às requisições validadas em cada loja)."""
    return urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def parse_http_date(value):
    """Converte um cabeçalho de data HTTP (ex.: Last-Modified) em timestamp. None se ausente ou inválido."""
    if not value:
        return None
    try:
        return email.utils.parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, IndexError):
        return None


def decode_body(body: bytes) -> bytes:
    # Algumas respostas chegam compactadas duas vezes (arquivo já em gzip servido com gzip).
    for _ in range(2):
        if body[:2] != b"\x1f\x8b":
            break
        body = gzip.decompress(body)
    return body


def error_detail(body: bytes) -> str:
    """Resumo curto do corpo de uma resposta de erro, para o painel e o log."""
    text = " ".join(body[:4000].decode("utf-8", "replace").split())
    if not text:
        return ""
    if text[0] == "{":
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if isinstance(data, dict):
            for key in ("message", "title", "error", "msg", "detail"):
                value = data.get(key)
                if isinstance(value, list):
                    value = "; ".join(str(v) for v in value)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:160]
    if text[0] == "<":
        return "página de erro"
    return text[:120]


def _retry_after(headers: dict):
    try:
        return float(headers.get("retry-after", ""))
    except ValueError:
        return None


def fetch(url: str, *, data=None, headers=None, timeout: float = 25, etag: str | None = None) -> Response:
    """GET (ou POST com JSON). Levanta HttpError em qualquer falha; 304 é devolvido como resposta normal."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9, */*;q=0.5", "Accept-Encoding": "gzip"}
    if etag:
        hdrs["If-None-Match"] = etag
    body_out = None
    if data is not None:
        body_out = json.dumps(data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    request = urllib.request.Request(url, data=body_out, headers=hdrs)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            status = resp.status
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            body = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        resp_headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        if exc.code == 304:
            return Response(304, resp_headers, b"")
        if exc.code == 429:
            raise RateLimited(url, _retry_after(resp_headers)) from None
        if resp_headers.get("cf-mitigated"):
            detail = "bloqueado por proteção contra robôs (Cloudflare)"
        else:
            try:
                detail = error_detail(decode_body(exc.read(20000)))
            except Exception:
                detail = ""
        raise HttpError(exc.code, url, detail) from None
    except Exception as exc:  # DNS, conexão, tempo esgotado, TLS
        reason = getattr(exc, "reason", exc)
        raise HttpError(0, url, str(reason)[:140]) from None
    if len(body) > MAX_BYTES:
        raise HttpError(status, url, "resposta grande demais")
    try:
        body = decode_body(body)
    except OSError as exc:
        raise HttpError(status, url, "resposta compactada inválida") from exc
    return Response(status, resp_headers, body)
