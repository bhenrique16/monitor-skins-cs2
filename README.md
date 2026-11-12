# Monitor de ofertas de skins de CS2

Consulta as lojas, calcula quanto a skin custa de verdade em reais e manda um e-mail quando aparece uma
oferta dentro do teto. Começa com a **★ Skeleton Knife | Slaughter até R$ 1.700** (total com taxas),
qualquer desgaste, com ou sem StatTrak.

Roda de graça no **GitHub Actions**, do mesmo jeito que o monitor de concursos: o computador pode ficar
desligado. Python puro, sem dependências.

## Como funciona no GitHub

- A cada 5 minutos o GitHub roda uma **rodada**: lê o `config.json`, consulta as lojas cuja vez chegou,
  manda os e-mails e grava o estado.
- O estado (banco SQLite com o que já foi avisado e a última consulta de cada loja) fica na branch
  `estado`, sobrescrita a cada rodada. Por isso reiniciar não repete alerta.
- A página de situação é o README da branch `estado`:
  `https://github.com/SEU-USUARIO/monitor-skins-cs2/tree/estado`. Ela mostra a última consulta bem-sucedida
  de cada loja, o menor preço e os últimos e-mails.
- Para mudar o teto, edite o `config.json` na branch `main` (no celular: app do GitHub, abrir o arquivo,
  lápis, salvar). A mudança dispara uma rodada na hora.

### Custo e limites (conferidos em 12/11/2026)

| Item | Repositório público | Repositório privado |
| --- | --- | --- |
| Minutos do Actions | grátis e ilimitados | US$ 12 por mês incluídos, cerca de 2.000 minutos |
| Intervalo possível | a cada 5 min | a cada 30 min (`*/30 * * * *`) para caber no gratuito |
| Custo | R$ 0 | R$ 0 |

- O GitHub avisa que a agenda **pode atrasar em horários de pico** e que algumas execuções podem ser
  descartadas. Na prática, conte com 5 a 15 minutos entre uma oferta aparecer e o e-mail chegar.
- Em repositório público, o GitHub desativa a agenda depois de 60 dias sem atividade no repositório e
  avisa por e-mail; um clique em Actions reativa.
- Os termos do GitHub pedem que o Actions seja usado para o próprio projeto e com carga baixa. Cada rodada
  dura menos de 1 minuto. O risco, se o GitHub discordar, é desativar o Actions neste repositório.
- Em repositório público o código, o `config.json` e os registros das execuções ficam visíveis. Senhas e
  o seu e-mail ficam nos segredos e aparecem como `***` nos registros.

## Colocar no ar

1. Crie o repositório em https://github.com/new com o nome `monitor-skins-cs2`. Não marque "Add a README".
2. Envie esta pasta (PowerShell, dentro de `C:\projetos\monitor-skins-cs2`):

```powershell
git init; git add .; git commit -m "Monitor de skins"; git branch -M main
```

```powershell
git remote add origin https://github.com/SEU-USUARIO/monitor-skins-cs2.git; git push -u origin main
```

3. Cadastre os segredos em **Settings → Secrets and variables → Actions → New repository secret**:

| Nome | Valor |
| --- | --- |
| `SMTP_USER` | seu Gmail |
| `SMTP_PASS` | senha de app do Gmail (https://myaccount.google.com/apppasswords) |
| `MAIL_TO` | e-mail que recebe os alertas |
| `CSFLOAT_API_KEY` | opcional: chave da CSFloat |

4. Na aba **Actions**, se aparecer, clique em "I understand my workflows, go ahead and enable them".

## Teste com oferta real

Na aba **Actions → Monitor de skins → Run workflow**, preencha **teto_teste** com um valor acima das ofertas
atuais (ex.: `2000`) e clique em **Run workflow**. Essa execução:

- usa o teto temporário só nela e consulta todas as lojas;
- manda os e-mails com **[TESTE]** no assunto;
- volta o teto para o valor do `config.json` (R$ 1.700) no fim.

Rode de novo com o mesmo valor: é outro processo, com o estado recuperado da branch `estado`, e não deve
sair nenhum e-mail repetido.

## Lojas

| Loja | Fonte | Intervalo próprio | Link no e-mail | Pagamento |
| --- | --- | --- | --- | --- |
| DashSkins.com.br | API pública do site | 1 min | faca específica | PIX |
| DashSkins.gg | API pública do site | 1 min | faca específica | PIX |
| BRSKINS | API pública do site (cache de 60 s) | 1 min | faca específica | PIX |
| NeshaStore | API pública do site | 1 min | faca específica | PIX |
| CSFloat com chave | API oficial | 1 min | faca específica | cartão internacional |
| CSFloat sem chave | lista pública de menor preço, renovada ~1 vez por hora | 10 min | busca (exige login) | cartão internacional |
| Bleik Store | página pública do produto | 5 min | página da skin | PIX |
| Steam | endpoints públicos do Mercado | 3 min | página do item | saldo Steam |
| LIS-SKINS | exportação pública | 5 min | página do item | cartão ou cripto |
| Market.CSGO | lista pública de preços | 5 min | busca | cartão ou cripto |
| Waxpeer | endpoint público de preços | 2 min | busca | cartão ou cripto |
| Tradeit.gg (loja) | inventário público | 2 min | busca | cartão ou cripto |
| Tradeit.gg (troca) | inventário público | 2 min | busca | troca, vem desligada |

No GitHub, o intervalo real é o maior entre o da loja e o da agenda (5 min). Lojas com link de busca ou
página do item informam só o menor preço: o e-mail diz **preço de referência** e, se o dado da loja tiver
mais de 10 minutos, mostra o horário em que a loja gerou o preço.

Sem cobertura: CS.MONEY Market (a API dos anúncios em dinheiro recusa clientes automáticos com HTTP 403;
a Pricempire acompanha a loja, mas a API custa US$ 119,90 por mês), Skinport, DMarket, SkinBaron,
BUFF.market, BUFF163, YouPin898, SkinSwap, BitSkins e HaloSkins.

### Chave da CSFloat

1. Entre em https://csfloat.com com a sua conta Steam.
2. Abra https://csfloat.com/profile, aba **Developer**, botão **New Key**.
3. Cadastre como segredo `CSFLOAT_API_KEY` no repositório.

## config.json

```json
{
  "alertas": [
    { "skin": "★ Skeleton Knife | Slaughter", "teto": 1700, "comparar": "total",
      "aceitar_total_incompleto": true, "desgastes": [], "stattrak": "qualquer", "ativo": true }
  ],
  "lojas": { "tradeit_troca": { "ativa": false } },
  "custos": { "iof": 3.5, "spread": 4.0 },
  "avisar_loja_fora_do_ar": true
}
```

- `comparar`: `total` (com câmbio e taxas) ou `anunciado`.
- `desgastes`: vazio = qualquer; ou `["FN", "MW"]` etc.
- `stattrak`: `qualquer`, `somente` ou `sem`.
- `lojas`: por loja, `ativa`, `taxa_percentual` (vazio/`null` = desconhecida) e `taxa_fixa`. Ids:
  `dashskins_br`, `dashskins_gg`, `brskins`, `neshastore`, `csfloat`, `bleik`, `steam`, `lisskins`,
  `marketcsgo`, `waxpeer`, `tradeit`, `tradeit_troca`.

Para outra skin, adicione outro item em `alertas` com o nome em inglês, como na Steam.

## Como o total é estimado

- **Loja em reais**: preço anunciado (PIX) + taxa da loja.
- **Loja em dólar, paga em dinheiro**: (preço + taxa da loja) × câmbio comercial, mais o spread do cartão,
  mais o IOF (3,5%).
- **Saldo Steam**: o preço do Mercado já inclui as taxas.
- **Troca**: sem valor em dinheiro; o total fica incompleto.

## Quando o e-mail é enviado

- Oferta nova dentro do teto.
- Anúncio já visto que baixou e cruzou o teto (o e-mail mostra o preço anterior).
- Oferta que passou a caber porque o teto subiu.
- Nova queda de 1% ou mais numa oferta já avisada.

## Rodar no computador

```bash
python -m unittest discover -s tests
```

```bash
python -m skinmon rodada
```

```bash
python -m skinmon
```

O primeiro roda os testes, sem rede. O segundo faz uma rodada igual à do GitHub. O terceiro sobe monitor e
painel em http://localhost:8787 (com `.env`, veja `.env.example`). Sem SMTP, os e-mails vão para
`data/outbox/`.
