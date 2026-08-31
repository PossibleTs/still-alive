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
mudancas.py           compara dois snapshots de historico/ e gera o material
                      recorrente para post (mudanca de situacao, quedas de
                      detentores). A pagina e estatica; a MUDANCA e o assunto.
revalidar.py          atende pedido de remedicao vindo de issue no GitHub
                      (os freios de abuso ficam AQUI, nao no YAML)
institucional.py      descoberta continua de atores institucionais
                      ouve o fluxo de transacoes (WebSocket proprio, stdlib)
                      -> candidatos.json, para revisao humana
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
python coletor.py                                 # a fatia do dia (topo + cauda)
python coletor.py --fatia 3                       # forca uma fatia do ciclo
python coletor.py --limite 60                     # modo avulso, ignora o ciclo
python teste_revalidar.py                         # freios do botao de revalidar
python teste_chave.py                             # identidade do projeto entre coletas
python coletor.py --no-rede                       # so reclassifica o que ja tem
python descoberta.py bithomp.com                  # inspeciona um dominio
python gerar_site.py
python institucional.py --minutos 10            # ouve a rede, junta candidatos
python mudancas.py                              # o que mudou, pronto para post
python mudancas.py --dias 1                     # so o dia anterior
```

Antes de publicar, defina `STILLALIVE_REPO` (ou `REPO` em `gerar_site.py`) com o
endereço do repositório: é o canal de contestação da página. Sem ele o gerador
avisa e a página sai sem para onde reclamar.

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
- **Escopo:** o universo é definido por um **piso de detentores**
  (`PISO_PRETENDIDO`, hoje 100), não por um número redondo de projetos. Medido em
  31/08/2026: posição 2000 do catálogo = 150 detentores, posição 3000 = 83; daí
  `CAUDA_TOTAL` ir até a posição ~2700. Abaixo disso é poeira que nunca foi
  projeto. A página **declara o piso real medido**, não a meta — enquanto o
  rodízio não cobre a cauda inteira, os dois números diferem, e anunciar a meta
  seria prometer cobertura inexistente.
- **Cadência:** o topo (`TOPO_DIARIO`) é medido em toda corrida; a cauda
  (`CAUDA_TOTAL`) é dividida em `CICLO_DIAS` fatias, uma por dia, derivadas do
  calendário — sem estado entre corridas. Por isso a coleta **mescla** com o
  `dados.json` anterior em vez de sobrescrever, e cada projeto carrega
  `medido_em`. Nunca troque a mesclagem por sobrescrita: apagaria catorze
  quinze avos da página.
- `historico/` é sagrado: é o que permite mostrar tendência. Nunca limpe.
- Antes de publicar qualquer lista pública, leia a seção "Antes de publicar" do
  README. A parte reputacional é mais arriscada que a técnica.
