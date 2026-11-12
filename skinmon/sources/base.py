"""Contrato comum das lojas."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from .. import net
from ..models import MarketInfo


@dataclass
class Ctx:
    """Dados da rodada que uma loja pode precisar."""

    fx: dict = field(default_factory=dict)  # BRL por unidade de moeda, ex.: {"USD": 5.56}
    notes: list = field(default_factory=list)  # observações para o painel


@dataclass
class PollResult:
    offers: dict = field(default_factory=dict)  # alert_id -> [Offer]
    errors: list = field(default_factory=list)
    rate_limited: float | None = None  # segundos sugeridos de espera, quando a loja pede pausa


class Source:
    id = ""
    label = ""
    currency = "BRL"
    pay_kind = "dinheiro"  # dinheiro | saldo_steam | troca
    pay_note = ""
    link_kind = "offer"  # "offer": link do anúncio; "search": link da lista/busca
    interval = 60  # segundos entre consultas
    pause = 1.5  # segundos entre requisições da mesma rodada
    timeout = 25
    default_enabled = True
    default_fee_pct: float | None = 0.0  # None = taxa desconhecida (total sai como incompleto)
    default_fee_fixed = 0.0
    default_spread_pct: float | None = None  # câmbio próprio da loja; None = spread do cartão
    default_iof_pct: float | None = None  # 0 quando a taxa da loja já inclui o IOF
    key_env: str | None = None  # variável de ambiente com a chave do usuário, se houver
    data_note = ""  # de onde vêm os dados e com que frequência mudam
    validated = "dados reais"  # como foi validada durante o desenvolvimento

    def __init__(self, env=None, fetch=net.fetch, sleep=time.sleep):
        self.env = os.environ if env is None else env
        self.fetch = fetch
        self.sleep = sleep

    def info(self) -> MarketInfo:
        return MarketInfo(self.id, self.label, self.currency, self.pay_kind, self.pay_note, self.link_kind)

    def key(self) -> str:
        return (self.env.get(self.key_env, "") or "").strip() if self.key_env else ""

    def poll(self, alerts, ctx: Ctx) -> PollResult:
        """Padrão: uma busca por alerta, com pausa entre elas. Uma busca que falha não derruba as outras."""
        result = PollResult()
        for index, alert in enumerate(alerts):
            if index:
                self.sleep(self.pause)
            try:
                result.offers[alert.id] = self.search(alert, ctx)
            except net.RateLimited as exc:
                result.rate_limited = exc.retry_after or 600.0
                result.errors.append(str(exc))
                break
            except Exception as exc:
                result.errors.append(f"{alert.name}: {exc}")
        return result

    def search(self, alert, ctx: Ctx) -> list:
        raise NotImplementedError
