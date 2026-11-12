"""Lojas integradas. Para adicionar uma: criar o módulo com uma classe Source e incluí-la em ALL."""
from __future__ import annotations

from .bleik import Bleik
from .brskins import Brskins
from .csfloat import Csfloat
from .dashskins_br import DashskinsBr
from .dashskins_gg import DashskinsGg
from .lisskins import Lisskins
from .marketcsgo import Marketcsgo
from .neshastore import Neshastore
from .steam import Steam
from .tradeit import Tradeit, TradeitTroca
from .waxpeer import Waxpeer

# Ordem de exibição: primeiro as lojas em reais com anúncio individual.
ALL = (DashskinsBr, DashskinsGg, Brskins, Neshastore, Csfloat, Bleik, Steam, Lisskins, Marketcsgo, Waxpeer, Tradeit, TradeitTroca)


# Lojas pesquisadas e deixadas de fora, com o motivo observado nos testes de 11 e 12/11/2026.
NOT_INTEGRATED = (
    ("CS.MONEY Market", "A API dos anúncios em dinheiro responde HTTP 403 (código 4030) a clientes automáticos. "
                        "A Pricempire acompanha a loja, mas a API dela é paga (plano API de US$ 119,90 por mês)."),
    ("Skinport", "A API oficial e o canal de novos anúncios (WebSocket) responderam com desafio Cloudflare a clientes sem navegador."),
    ("DMarket", "O endpoint público antigo foi desativado; o atual exige chave e assinatura Ed25519 da sua conta."),
    ("SkinBaron", "A busca pública do site ignora o filtro por nome; a API oficial exige chave da conta."),
    ("BUFF.market e BUFF163", "Exigem login e proíbem automação; a BUFF163 também pede meio de pagamento chinês."),
    ("YouPin898", "Só responde ao aplicativo oficial e usa meios de pagamento chineses."),
    ("SkinSwap", "Site de troca; a API interna não aceita busca por nome."),
    ("BitSkins", "A busca pública devolveu HTTP 403 sem conta."),
    ("HaloSkins", "A API pública responde, mas o significado dos campos de preço e o pagamento a partir do Brasil não foram confirmados."),
)


def build(env=None) -> list:
    return [cls(env=env) for cls in ALL]
