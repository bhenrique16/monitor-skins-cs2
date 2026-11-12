"""Estimativa do valor que sai do bolso em reais.

Modelo:
- Loja em BRL: preço + taxa percentual da loja/meio de pagamento + taxa fixa.
- Loja em moeda estrangeira (compra no cartão): (preço + taxas da loja) convertido pelo câmbio
  comercial, mais o spread do cartão, mais o IOF.
- Troca: não há valor em dinheiro; o total fica marcado como incompleto.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarketFees:
    pay_kind: str = "dinheiro"  # dinheiro | saldo_steam | troca
    fee_pct: float | None = 0.0  # None = taxa desconhecida
    fee_fixed: float = 0.0  # na moeda da loja


@dataclass(frozen=True)
class CostSettings:
    iof_pct: float = 3.5  # IOF de compra internacional no cartão
    spread_pct: float = 4.0  # spread do cartão/banco sobre o câmbio comercial


@dataclass
class Cost:
    listed: float
    currency: str
    listed_brl: float | None  # preço anunciado convertido, sem taxas
    total_brl: float | None  # estimativa do que sai do bolso
    complete: bool  # False quando falta algum dado para fechar o total
    missing: list = field(default_factory=list)  # o que faltou
    parts: list = field(default_factory=list)  # [(rótulo, valor em BRL)] que somam o total
    fx_rate: float | None = None


def _pct(value: float) -> str:
    return f"{value:g}".replace(".", ",") + "%"


def estimate(price: float, currency: str, fees: MarketFees, settings: CostSettings, fx: dict) -> Cost:
    currency = (currency or "BRL").upper()
    missing = []
    fee_pct = fees.fee_pct
    if fees.pay_kind == "troca":
        missing.append("troca: o valor é pago em itens, não em dinheiro")
        fee_pct = 0.0
    elif fee_pct is None:
        missing.append("taxa de pagamento desta loja não informada")
        fee_pct = 0.0

    if currency == "BRL":
        rate = 1.0
    else:
        rate = fx.get(currency)
        if not rate:
            return Cost(price, currency, None, None, False, ["câmbio indisponível para " + currency], [], None)

    listed_brl = price * rate
    parts = [("Preço anunciado", listed_brl)]
    store_fee = (price * fee_pct / 100.0 + fees.fee_fixed) * rate
    if store_fee:
        parts.append(("Taxa da loja/pagamento", store_fee))
    total = listed_brl + store_fee

    if currency != "BRL" and fees.pay_kind == "dinheiro":
        spread = total * settings.spread_pct / 100.0
        iof = (total + spread) * settings.iof_pct / 100.0
        if spread:
            parts.append((f"Spread do cartão ({_pct(settings.spread_pct)})", spread))
        if iof:
            parts.append((f"IOF ({_pct(settings.iof_pct)})", iof))
        total += spread + iof

    return Cost(
        listed=price,
        currency=currency,
        listed_brl=round(listed_brl, 2),
        total_brl=round(total, 2),
        complete=not missing,
        missing=missing,
        parts=[(label, round(value, 2)) for label, value in parts],
        fx_rate=None if currency == "BRL" else rate,
    )
