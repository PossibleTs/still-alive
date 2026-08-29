# CLAUDE.md

Contexto permanente deste repositório. Leia antes de mexer em qualquer arquivo.

## O que é

Uma página que mostra quais projetos da XRP Ledger ainda estão vivos, medindo
atividade real na rede todo dia. Os diretórios existentes (`map.xrpl-commons.org`,
`xrplpulse.com`, a página de projetos da `xrpl.org`) são curados à mão e viram
cemitério: listam projetos da onda de NFT de 2022 como se estivessem ativos, e um
deles ainda descreve o AMM como "que vem aí" — o AMM entrou em produção em 2024.

O diferencial não é listar. É **datar a morte, com prova**.

## Regras do projeto

**Zero dependências.** Só biblioteca padrão do Python 3.11+. Isso não é preguiça,
é a decisão que faz o projeto continuar rodando daqui a dois anos sem ninguém
mexer. Se você acha que precisa de `requests`, `pandas` ou um framework web, a
resposta é não. Discuta antes de adicionar qualquer import externo.

**Sem build, sem framework, sem banco.** O estado é `dados.json` e a pasta
`historico/`. A página é um HTML gerado. O GitHub Pages serve. Acabou.

**Comentários e strings de código em ASCII sem acento.** Os arquivos `.py` evitam
acentuação para não depender de encoding em nenhum ambiente. Markdown e o HTML
gerado usam acentuação normal.

**Toda classificação carrega o motivo.** Nunca marque um projeto sem gravar o
número que sustenta a marcação. Chamar o projeto de alguém de morto sem mostrar a
conta é como se perde a comunidade em uma semana.

## Arquitetura

```
coletor.py            projetos COM token
                      descobre no XRPL Meta -> mede na rede -> dados.json
descoberta.py         projetos SEM token
                      xrp-ledger.toml + tipos de objeto + validadores
gerar_site.py         dados.json -> site/index.html
teste_local.py        exercita a classificacao de tokens, sem rede
teste_corporativo.py  exercita a classificacao corporativa, sem rede
historico/            um snapshot JSON por dia, versionado
.github/workflows/    roda tudo as 03:17 e publica no Pages
```

Fluxo: `coletor.py` → `dados.json` → `gerar_site.py` → `site/index.html` → Pages.

## Comandos

```bash
python teste_local.py && python gerar_site.py dados_teste.json   # logica + visual, sem rede
python teste_corporativo.py                       # classificacao corporativa
python coletor.py --limite 60                     # coleta real, ~5 min
python coletor.py --no-rede                       # so reclassifica o que ja tem
python descoberta.py bithomp.com                  # inspeciona um dominio
python gerar_site.py
```

## As três armadilhas

Estão resolvidas no código. Não as reintroduza ao refatorar.

1. **Epoch da XRPL.** A rede conta segundos desde 2000-01-01, não 1970. A
   constante é `RIPPLE_EPOCH = 946684800`. Esquecer disso mostra todo mundo com
   trinta anos de inatividade.

2. **Emissor blackholed.** Conta emissora com a chave mestra desabilitada
   (`lsfDisableMaster`, flag `0x00100000`) nunca mais transaciona — e isso é boa
   prática de segurança, não abandono. Nesses casos julgue pelo token
   (detentores, negociação), nunca pela conta. Classificar esses como mortos
   derruba a credibilidade da página no primeiro dia.

3. **Campo `Domain` em hexadecimal.** Precisa de `bytes.fromhex(...).decode()`.
   Sem isso a verificação de mão dupla do `xrp-ledger.toml` falha sempre e você
   conclui, errado, que ninguém confirma o domínio.

## Fontes de dados

| Fonte | Uso | Custo |
|---|---|---|
| `s1.xrplmeta.org` | catálogo de tokens, detentores, volume | grátis, sem chave |
| `xrplcluster.com` | JSON-RPC com histórico completo | grátis, seja gentil |
| `/.well-known/xrp-ledger.toml` | identidade corporativa | do próprio projeto |
| `api.github.com` | vitalidade de repositório | grátis sem token, limitado |

O único contrato externo frágil é o esquema do XRPL Meta. `coletor.py` lê os
campos por `_cava()`, tolerante a mudança, mas se eles renomearem algo os
detentores vêm zerados e a classificação sai errada em silêncio. Confira uma vez.

## Estilo de trabalho aqui

- Mudou limiar de classificação? Rode os dois testes e cole o antes/depois.
- Nada de "melhorar" o HTML gerado com biblioteca de template.
- `historico/` é sagrado: é o que permite mostrar tendência. Nunca limpe.
- Antes de publicar qualquer lista pública, leia a seção "Antes de publicar" do
  README. A parte reputacional é mais arriscada que a técnica.
