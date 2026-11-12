"""Tipos compartilhados entre as lojas, o motor de alertas e o e-mail."""
from __future__ import annotations

from dataclasses import dataclass

# Formas de pagamento que o monitor diferencia.
PAY_KINDS = ("dinheiro", "saldo_steam", "troca")


@dataclass
class Offer:
    """Um anúncio (ou o menor preço de um item, quando a loja não expõe anúncios individuais)."""

    source: str
    offer_id: str  # estável dentro da loja: id do anúncio ou chave do agregado
    name: str  # market hash name em inglês, ex.: "★ Skeleton Knife | Slaughter (Minimal Wear)"
    price: float  # preço anunciado, na moeda da loja
    currency: str  # BRL, USD ou EUR
    url: str
    link_kind: str = "offer"  # "offer" abre o anúncio; "search" abre a lista/busca da loja
    float_value: float | None = None
    aggregated: bool = False  # True: menor preço por item, sem anúncio individual
    quantity: int | None = None  # quantidade de anúncios (fontes agregadas)
    note: str = ""  # observação curta para o e-mail, ex.: "entrega manual"
    data_time: float | None = None  # quando a loja gerou o dado (listas de preço atualizadas em lote)


@dataclass(frozen=True)
class Alert:
    id: int
    name: str  # nome da skin sem desgaste, ex.: "★ Skeleton Knife | Slaughter"
    max_price: float  # teto em reais
    basis: str = "total"  # "total" = custo estimado com taxas; "listed" = preço anunciado
    include_incomplete: bool = True  # aceitar ofertas cujo total não pôde ser calculado por inteiro
    wears: tuple = ()  # subconjunto de FN, MW, FT, WW, BS; vazio = qualquer desgaste
    stattrak: str = "any"  # "any", "only" ou "exclude"
    active: bool = True


@dataclass(frozen=True)
class MarketInfo:
    id: str
    label: str
    currency: str
    pay_kind: str = "dinheiro"
    pay_note: str = ""
    link_kind: str = "offer"
