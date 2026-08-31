# RWAlive — quem ainda está vivo na XRPL

Diretório nenhum diz quais projetos morreram. Este mede a atividade real de cada
um na rede, todo dia, e mostra a conta.

Três arquivos, nenhuma dependência além do Python padrão, zero custo de operação.

```
coletor.py           projetos COM token: descobre no XRPL Meta e mede na rede
descoberta.py        projetos SEM token: infra, corporativos, validadores
gerar_site.py        transforma dados.json em site/index.html
teste_local.py       exercita a classificação de tokens sem tocar na rede
teste_corporativo.py exercita a classificação de projetos sem token
```

## Rodar

```bash
python teste_local.py && python gerar_site.py dados_teste.json   # confere a lógica e o visual
open site/index.html

python coletor.py --limite 60                   # coleta de verdade (~5 min)
python gerar_site.py
```

Na primeira coleta real, confira o esquema do XRPL Meta:

```bash
curl -s "https://s1.xrplmeta.org/tokens?limit=1" | python -m json.tool
```

O coletor lê os campos de forma defensiva (`_cava`), mas se o XRPL Meta tiver
renomeado algo, os holders vêm zerados e a classificação sai errada. É o único
ponto do código que depende de um contrato externo — vale conferir uma vez.

## Publicar

Suba num repositório do GitHub, ative Pages apontando para GitHub Actions, e
pronto. O workflow em `.github/workflows/atualizar.yml` roda todo dia às 3h17 da
manhã, regenera a página e faz o deploy. Também dá para disparar na mão pela aba
Actions.

O histórico fica versionado em `historico/`, um JSON por dia. É ele que permite
mostrar variação de detentores — esse sinal só aparece a partir do segundo mês.

## Os sinais

Para projeto com token:

| Sinal | De onde vem | O que indica |
|---|---|---|
| Dias desde a última transação | `account_tx` no emissor | Abandono |
| Transações em 30 dias | `account_tx` paginado | Intensidade de uso |
| Detentores e trustlines | XRPL Meta | Tamanho da base |
| Negociação em 24h | XRPL Meta | Mercado ativo |
| Site responde | HTTP GET | Time ainda existe |
| Variação de detentores | histórico local | Direção |

Para projeto sem token (carteira, explorador, ferramenta), não existe sinal
on-chain: sobra o site e, se você quiser acrescentar, o último commit do
repositório.

## Projetos sem token: infraestrutura e corporativos

Medir só quem emite token deixa de fora justamente os projetos mais sérios da
rede. `descoberta.py` resolve isso com três instrumentos, e declara honestamente
o quarto caso.

### 1. Identidade — `xrp-ledger.toml`

A XRPL já tem um registro empresarial e quase ninguém o usa como diretório. Em
`https://dominio/.well-known/xrp-ledger.toml` uma empresa declara suas contas,
seus validadores, seus servidores públicos, seus responsáveis e suas moedas.

A verificação é de mão dupla, e é aí que está o valor:

- o **domínio** afirma controlar a conta, listando-a em `[[ACCOUNTS]]`
- a **conta** afirma controlar o domínio, no campo `Domain` do `AccountSet`

Um lado sozinho não prova nada. Os dois juntos são evidência forte de controle
compartilhado. Isso te dá o que nenhum diretório manual tem: uma lista de
projetos corporativos **auto-declarados e verificáveis**.

De brinde, o arquivo traz `[METADATA]` com `modified` e `expires` — data de
validade posta pelo próprio dono. Um toml vencido é o melhor sinal de abandono
que existe: não é heurística sua, é a empresa dizendo que parou de cuidar.

### 2. Papel — os objetos que a conta possui

Conta corporativa não precisa emitir token para deixar rastro. O tipo dos objetos
que ela guarda no ledger (`account_objects` com filtro `type`) diz o que ela faz,
e é bem mais difícil de falsificar que uma página institucional:

| Objeto | O que revela |
|---|---|
| `Oracle` | Provedor de oráculo — infraestrutura pura |
| `Bridge`, `XChainOwnedClaimID` | Operador de ponte |
| `Credential`, `PermissionedDomain` | Compliance e acesso institucional |
| `MPTokenIssuance`, `Vault` | Emissor de RWA, cofre tokenizado |
| `LoanBroker`, `Loan` | Protocolo de crédito |
| `PayChannel` | Serviço de canal de pagamento |
| `SignerList`, `Delegate` | Operação multi-assinatura ou delegada |
| `DepositPreauth` | Conta que exige pré-autorização |

`SignerList` merece destaque: empresa opera com multi-assinatura, pessoa física
quase nunca. É um dos separadores mais baratos entre conta corporativa e pessoal.

### 3. Operação — validadores e servidores

Quem opera validador é fornecedor de infraestrutura por definição. E aqui o sinal
de vida é o menos discutível de todos: a **NegativeUNL** é a própria rede
declarando quais validadores considera fora do ar. Para servidores públicos,
basta um `server_info` no endpoint que o projeto declarou no toml.

### 4. O caso honesto que sobra

Biblioteca, SDK, ferramenta de linha de comando: não têm pegada nenhuma no
ledger, e fingir que têm seria desonesto. Para esses o instrumento certo é o
GitHub — último push, se o repositório foi arquivado, issues abertas. Trate como
categoria separada, com método declarado na página.

### Descobrir quem você ainda não conhece

O acima mede projetos que você já listou. Para *descobrir* atores institucionais
que ninguém listou, dois caminhos:

- assinar o fluxo de transações e capturar os tipos raros conforme aparecem
  (`OracleSet`, `XChainCreateBridge`, `CredentialCreate`, `MPTokenIssuanceCreate`,
  `PermissionedDomainSet`, `VaultCreate`) — barato e contínuo;
- varrer `ledger_data` filtrando por esses tipos de objeto — caro, mas roda uma
  vez e depois só incrementa.

O primeiro caminho é o que eu faria: descobre para frente, sem castigar nó público.

## As duas armadilhas

**Emissor blackholed.** Um emissor com a chave mestra desabilitada nunca mais
transaciona — e isso é boa prática de segurança, não abandono. A atividade
acontece entre os detentores. Classificar esses como mortos derrubaria a
credibilidade da página no primeiro dia. O `coletor.py` detecta a flag
`lsfDisableMaster` e passa a julgar pelo token, não pela conta.

**Epoch da XRPL.** A rede conta o tempo em segundos desde 2000-01-01, não desde
1970. Quem esquece de somar 946684800 vê todo mundo com trinta anos de inatividade.

E uma terceira, específica dos projetos corporativos: **o campo `Domain` vem em
hexadecimal**. Esquecer de decodificar faz a verificação de mão dupla falhar
sempre, e você conclui que ninguém confirma nada.

## Os cortes

Estão no topo do `coletor.py`, em `LIMIARES`, e aparecem na própria página. São
opinião editorial, vão ser questionados, e é bom que sejam fáceis de discutir:

- **morto** — mais de 180 dias sem transação, ou site fora do ar com menos de 10 transações no mês
- **parado** — mais de 90 dias sem atividade, ou menos de 10 transações no mês
- **morrendo** — menos de 100 transações no mês, ou site fora do ar
- **ativo** — pelo menos 100 transações no mês e movimento nos últimos 7 dias

## Antes de publicar

Chamar o projeto de alguém de morto em público tem consequência. Duas defesas,
ambas já no código: cada classificação vem com o motivo e os números que a
sustentam, e a página diz que um projeto quieto na rede pode estar vivo fora
dela. Deixe um canal de contestação bem visível e responda rápido — a primeira
correção que você fizer publicamente vale mais que a lista inteira.
