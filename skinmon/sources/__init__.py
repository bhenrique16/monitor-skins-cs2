"""Lojas integradas. Para adicionar uma: criar o módulo com uma classe Source e incluí-la em ALL."""
from __future__ import annotations

from .bleik import Bleik
from .brskins import Brskins
from .buffmarket import Buffmarket
from .csfloat import Csfloat
from .dashskins_br import DashskinsBr
from .dashskins_gg import DashskinsGg
from .lisskins import Lisskins
from .marketcsgo import Marketcsgo
from .neshastore import Neshastore
from .pricempire import PricempireCsmoney
from .steam import Steam
from .tradeit import Tradeit, TradeitTroca
from .waxpeer import Waxpeer

# Ordem de exibição: primeiro as lojas em reais com anúncio individual.
ALL = (DashskinsBr, DashskinsGg, Brskins, Neshastore, PricempireCsmoney, Csfloat, Buffmarket, Bleik, Steam, Lisskins, Marketcsgo, Waxpeer, Tradeit, TradeitTroca)


# Lojas pesquisadas e deixadas de fora, com o motivo observado nos testes de 11 e 12/11/2026.
NOT_INTEGRATED = (
    ("CS.MONEY Market (direto)", "A API dos anúncios em dinheiro responde HTTP 403 (código 4030) a clientes automáticos. "
                                 "Coberto pela Pricempire com a sua chave (menor preço, a cada 45 min)."),
    ("Skinport", "A API oficial e o canal de novos anúncios (WebSocket) responderam com desafio Cloudflare a clientes sem navegador."),
    ("DMarket", "O endpoint público antigo foi desativado; o atual exige chave e assinatura Ed25519 da sua conta."),
    ("SkinBaron", "A busca pública do site ignora o filtro por nome; a API oficial exige chave da conta."),
    ("BUFF163", "Exige login e meio de pagamento chinês. A BUFF.market, versão internacional, está integrada."),
    ("YouPin898", "Só responde ao aplicativo oficial e usa meios de pagamento chineses."),
    ("SkinSwap", "Site de troca; a API interna não aceita busca por nome."),
    ("BitSkins", "A busca pública devolveu HTTP 403 sem conta."),
    ("HaloSkins", "A API pública responde, mas o significado dos campos de preço e o pagamento a partir do Brasil não foram confirmados."),
)


def build(env=None) -> list:
    return [cls(env=env) for cls in ALL]
