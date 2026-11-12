"""Bleik Store: a API de catálogo recusa clientes automáticos, então o monitor lê a página pública
do produto (liberada no robots.txt), que traz o menor preço da skin em dados estruturados (JSON-LD)."""
from __future__ import annotations

import json
import re
import time

from .. import names
from ..models import Offer
from .base import Source

SITEMAP_INDEX = "https://bleikstore.com/sitemap-index.xml"
_LD_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
URL_TTL = 7 * 86400  # endereço do produto muda raramente
MISS_TTL = 86400


def find_product_url(sitemap_xml: str, slug: str):
    for loc in _LOC_RE.findall(sitemap_xml):
        if loc.rstrip("/").rsplit("/", 1)[-1] == slug:
            return loc
    return None


def _products(node):
    if isinstance(node, list):
        for child in node:
            yield from _products(child)
    elif isinstance(node, dict):
        if node.get("@type") == "Product":
            yield node
        for child in node.get("@graph") or []:
            yield from _products(child)


def parse_product(html: str, url: str):
    for block in _LD_RE.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for product in _products(data):
            offers = product.get("offers") or {}
            price = offers.get("lowPrice", offers.get("price"))
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            name = product.get("name") or ""
            if not name or price <= 0:
                continue
            count = offers.get("offerCount")
            return Offer(
                source="bleik", offer_id="min:" + names.slugify(name), name=name, price=price,
                currency=offers.get("priceCurrency") or "BRL", url=url, link_kind="search", aggregated=True,
                quantity=int(count) if isinstance(count, (int, float)) else None,
            )
    return None


class Bleik(Source):
    id = "bleik"
    label = "Bleik Store"
    pay_note = "PIX"
    link_kind = "search"
    interval = 300
    timeout = 45
    data_note = "Página pública do produto (menor preço da skin, todos os desgastes juntos). Atualiza a cada ~5 min."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._urls = {}  # slug -> (url ou None, validade)

    def _product_url(self, slug: str):
        cached = self._urls.get(slug)
        if cached and cached[1] > time.time():
            return cached[0]
        index = self.fetch(SITEMAP_INDEX, timeout=self.timeout).text()
        found = None
        for sitemap in _LOC_RE.findall(index):
            if "/en/products" not in sitemap:
                continue
            self.sleep(self.pause)
            found = find_product_url(self.fetch(sitemap, timeout=self.timeout).text(), slug)
            if found:
                break
        self._urls[slug] = (found, time.time() + (URL_TTL if found else MISS_TTL))
        return found

    def search(self, alert, ctx):
        url = self._product_url(names.slugify(alert.name))
        if not url:
            ctx.notes.append(f"{alert.name}: skin não encontrada no catálogo da loja")
            return []
        offer = parse_product(self.fetch(url, timeout=self.timeout).text(), url)
        if offer is None:
            ctx.notes.append(f"{alert.name}: página sem preço (sem estoque?)")
            return []
        return [offer]
