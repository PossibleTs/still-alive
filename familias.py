"""
Origem dos detentores: os maiores detentores de um token sao gente diferente?

Na XRPL toda conta nasce de um pagamento de outra conta (a "ativadora"). Se
boa parte dos maiores detentores foi criada pela mesma carteira, eles nao
chegaram sozinhos: pode ser um app que cria carteira para o usuario, um
airdrop, ou uma pessoa so com muitas carteiras. E o ponto cego que a pagina
admite no disclaimer: "an active market is exactly what a pump needs".

Este sinal NUNCA muda a situacao de um projeto. Vira uma nota na linha, com a
conta que a sustenta, e so quando passa dos limiares abaixo.

As armadilhas, aprendidas no piloto de 300 tokens (09/10/2026):

1. Exchange cria milhares de contas legitimas. Quem saca XRP da Binance para
   carteira nova tem a Binance como ativadora. Contas da lista publica do
   XRPSCAN nao formam grupo. Ha servicos fora da lista (246 no piloto), mas
   eles se comportam diferente de fabrica: aparecem em muitos tokens com 1 ou
   2 detentores em cada - nenhum passou de 9 num mesmo token. O limiar de 10
   detentores separa os dois sem precisar adivinhar quem e servico.

2. Fabrica se divide. No piloto, uma rede de 5 carteiras criou ~40 dos 60
   maiores detentores de 9 tokens - mas nenhuma sozinha passou de 11, e a
   nota nao disparou. Por isso a nota soma FAMILIAS: carteiras criadas por
   outra fabrica do mesmo token, ou pela mesma carteira privada, contam
   juntas. So um nivel: subir mais na arvore acaba sempre numa exchange.

3. Pool AMM e uma conta. O maior detentor de muito token e a pool, e a
   ativadora dela e quem criou a pool. Pools saem da amostra.

4. No sem historico completo devolve a primeira transacao QUE ELE TEM, nao a
   de criacao da conta - inventaria uma ativadora. Nesses casos: nao sei.

Estado:
    origens.json     uma leitura por token (versionado, uma linha por token)
    ativadores.json  conta -> quem a criou. Nunca muda, entao e cache eterno:
                     e o que torna o sinal barato depois da primeira volta.

Uso:
    python familias.py                    # rodizio do dia, com teto de tempo
    python familias.py --minutos 0 --limite 20
    python familias.py --token X:ruxT12tH2mrccHFDjnjqWyGfAxYxYMHLA
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

import coletor
from coletor import FALHAS_DE_REDE, PRIMEIRO_LEDGER, XRPLMETA, _get_json, _rpc

ARQ_ORIGENS = "origens.json"
ARQ_ATIVADORES = "ativadores.json"
LISTA_CONHECIDAS = "https://api.xrpscan.com/api/v1/names/well-known"

TOP = 60                 # maiores detentores por token; fraude que importa mora no topo
CICLO_DIAS = 30          # origem muda devagar; uma volta por mes basta
ORCAMENTO_MINUTOS = 25
PAUSA = coletor.PAUSA_ENTRE_CHAMADAS

# Limiares da nota na pagina. Os dois juntos: 10 sozinho seria pouco num
# token de 60 detentores "de verdade" na amostra, 20% sozinho seria 2 de 10.
NOTA_MINIMO = 10
NOTA_FRACAO = 0.20

# A pagina so fala de INFLACAO DE CONTAGEM: a familia inteira segura menos que
# isto da oferta. Carteira que existe so para contar como detentor segura
# poeira - e e ai que o "alive" engana. Acima disso e concentracao de posse,
# outro assunto, e a pagina se cala. Caso que ensinou: AUG (10/10/2026), ouro
# tokenizado da Phi Wallet - 59 dos 60 maiores detentores criados por uma
# carteira so, segurando 36.6% da oferta. Clientes de app, nao poeira.
SELO_OFERTA_MAXIMA = 1.0

# Leitura mais velha que isto sai da pagina: o rodizio so rele alive e quiet,
# e um token que saiu desse grupo nao pode ficar com nota velha para sempre.
VALIDADE_DIAS = 2 * CICLO_DIAS

# Quem entra no rodizio: onde a inflacao engana. Token "unknown" ou "dead" ja
# esta rotulado como sem pulso; ler a origem dele gasta no publico para nada.
SITUACOES_LIDAS = ("ativo", "quieto")

AMM = "amm"
SEM_HISTORICO = "sem historico"


# --------------------------------------------------------------------------
# Arquivos
# --------------------------------------------------------------------------


def _ler(caminho: str, padrao):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def _gravar_linhas(caminho: str, cabeca: dict, chave: str, itens: dict) -> None:
    """
    JSON valido com UMA entrada por linha, em ordem. O commit diario do robo
    vira um diff de poucas linhas em vez de reescrever megabytes.
    """
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("{\n")
        for k, v in cabeca.items():
            f.write(f" {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)},\n")
        f.write(f' {json.dumps(chave)}: {{\n')
        linhas = [
            f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
            for k, v in sorted(itens.items())
        ]
        f.write(",\n".join(linhas))
        f.write("\n }\n}\n")
    os.replace(tmp, caminho)


def carregar_origens(caminho: str = ARQ_ORIGENS) -> dict:
    return _ler(caminho, {}).get("tokens", {})


def salvar_origens(tokens: dict, caminho: str = ARQ_ORIGENS) -> None:
    _gravar_linhas(caminho, {"top": TOP, "ciclo_dias": CICLO_DIAS}, "tokens", tokens)


def carregar_ativadores() -> dict:
    return _ler(ARQ_ATIVADORES, {}).get("contas", {})


def salvar_ativadores(cache: dict) -> None:
    _gravar_linhas(ARQ_ATIVADORES, {}, "contas", cache)


def contas_conhecidas() -> dict[str, str]:
    """Endereco -> nome publico (exchanges, servicos), da lista do XRPSCAN."""
    lista = _get_json(LISTA_CONHECIDAS)
    return {x["account"]: x.get("name") or "?" for x in lista if x.get("account")}


# --------------------------------------------------------------------------
# Rede
# --------------------------------------------------------------------------


def ativadora(conta: str, cache: dict) -> str | None:
    """
    Quem criou a conta: o endereco, AMM para pool, SEM_HISTORICO quando o no
    nao tem o historico inteiro, ou None se a rede nao respondeu (nao cacheia:
    a proxima volta pergunta de novo).
    """
    if conta in cache:
        return cache[conta]
    res = _rpc("account_tx", {
        "account": conta, "forward": True, "limit": 1,
        "ledger_index_min": -1, "ledger_index_max": -1,
    })
    time.sleep(PAUSA)
    if "erro_rede" in res or res.get("error"):
        return None
    if (res.get("ledger_index_min") or 0) > PRIMEIRO_LEDGER:
        return SEM_HISTORICO
    txs = res.get("transactions") or []
    if not txs:
        return None
    tx = txs[0].get("tx") or txs[0].get("tx_json") or {}
    tipo = tx.get("TransactionType")
    if tipo == "AMMCreate":
        origem = AMM
    elif tipo == "Payment" and tx.get("Destination") == conta:
        origem = tx.get("Account")
    else:
        origem = f"tipo:{tipo}"   # genese ou algo raro: registra e segue
    cache[conta] = origem
    return origem


def maiores_detentores(p: dict) -> list[dict]:
    moeda = p.get("moeda_hex") or p["moeda"]
    dados = _get_json(f"{XRPLMETA}/v2/token/{moeda}:{p['emissor']}/holders?limit={TOP}")
    return dados.get("holders") or []


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------


def ler_origem(p: dict, cache: dict, conhecidas: dict) -> dict:
    """Uma leitura de origem para um token. So guarda grupo de 2 ou mais."""
    emissor = p["emissor"]
    origem_emissor = ativadora(emissor, cache)
    amostra = pools = via_conhecida = sem_resposta = unicas = 0
    grupos: dict[str, list] = {}
    for h in maiores_detentores(p):
        conta = h.get("account")
        if not conta or conta == emissor:
            continue
        origem = ativadora(conta, cache)
        if origem == AMM:
            pools += 1
            continue
        if origem is None or origem == SEM_HISTORICO:
            sem_resposta += 1
            continue
        amostra += 1
        if origem in conhecidas:
            via_conhecida += 1
        elif origem.startswith("r"):
            g = grupos.setdefault(origem, [0, 0.0])
            g[0] += 1
            g[1] += float(h.get("percent") or 0)
    for a in [a for a, g in grupos.items() if g[0] < 2]:
        del grupos[a]
        unicas += 1
    # Quem criou cada fabrica: e o que permite somar a familia em nota().
    # Exchange conhecida nao vira pai - senao todo saque da Kraken seria parente.
    for a, g in grupos.items():
        pai = ativadora(a, cache)
        g.append(pai if (pai or "").startswith("r") and pai not in conhecidas else None)
    return {
        "medido_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "amostra": amostra, "pools": pools, "via_conhecida": via_conhecida,
        "sem_resposta": sem_resposta, "unicas": unicas,
        "ativadora_do_emissor": origem_emissor if (origem_emissor or "").startswith("r") else None,
        "grupos": {a: [n, round(pct, 3), pai] for a, (n, pct, pai) in grupos.items()},
    }


def familias_do_token(grupos: dict) -> dict[str, list]:
    """
    Junta grupos da mesma familia: raiz -> [n, pct, carteiras]. A raiz de uma
    fabrica e quem a criou quando esse pai tambem criou detentores deste token
    ou criou outra fabrica deste token; senao, ela mesma.
    """
    pais: dict[str, int] = {}
    for g in grupos.values():
        pai = g[2] if len(g) > 2 else None
        if pai:
            pais[pai] = pais.get(pai, 0) + 1
    fams: dict[str, list] = {}
    for a, g in grupos.items():
        pai = g[2] if len(g) > 2 else None
        raiz = pai if pai and (pai in grupos or pais.get(pai, 0) >= 2) else a
        f = fams.setdefault(raiz, [0, 0.0, set()])
        f[0] += g[0]
        f[1] += g[1]
        f[2].add(a)
    return fams


def _curto(a: str) -> str:
    return f"{a[:6]}…{a[-4:]}"


def nota(r: dict | None, emissor: str | None, hoje: dt.date | None = None) -> dict | None:
    """
    O que a pagina diz, ou None. Regra pura, sem rede - testada em
    teste_familias.py. So inflacao de contagem: a maior familia passa dos dois
    limiares E segura menos de SELO_OFERTA_MAXIMA da oferta.
    """
    if not r or not r.get("amostra") or not r.get("grupos"):
        return None
    if hoje and (hoje - dt.date.fromisoformat(r["medido_em"][:10])).days > VALIDADE_DIAS:
        return None
    ativ, (n, pct, carteiras) = max(
        familias_do_token(r["grupos"]).items(), key=lambda kv: (kv[1][0], kv[1][1])
    )
    if n < NOTA_MINIMO or n / r["amostra"] < NOTA_FRACAO or pct >= SELO_OFERTA_MAXIMA:
        return None
    do_emissor = ativ == emissor or (ativ and ativ == r.get("ativadora_do_emissor"))
    if do_emissor:
        quem = "by the issuer itself, or by the wallet that created the issuer"
    elif len(carteiras) > 1 and ativ in carteiras:
        quem = f"by {len(carteiras)} related wallets ({_curto(ativ)} and wallets it created)"
    elif len(carteiras) > 1:
        quem = f"by {len(carteiras)} wallets that were all created by {_curto(ativ)}"
    else:
        quem = f"by the same wallet ({_curto(ativ)})"
    # "0.0%" parece erro de conta; e o achado: carteira que existe so para
    # contar como detentor segura poeira.
    fatia = "less than 0.1% of supply" if pct < 0.1 else f"{pct:.1f}% of supply"
    texto = (
        f"Holder origin: {n} of the top {r['amostra']} holders were created {quem}, "
        f"holding {fatia} together. They hold almost none of the token: they add to "
        f"the holder count without holding it. Read on {r['medido_em'][:10]}."
    )
    return {"n": n, "amostra": r["amostra"], "ativadora": ativ, "pct": pct,
            "carteiras": sorted(carteiras), "do_emissor": bool(do_emissor), "texto": texto}


# --------------------------------------------------------------------------
# Rodizio
# --------------------------------------------------------------------------


def alvos(projetos: list[dict], origens: dict, hoje: dt.date) -> list[dict]:
    """
    So alive e quiet. Quem nunca foi lido primeiro, depois quem passou do
    ciclo. Dentro de cada grupo, vivos antes e mais detentores antes.
    """
    peso = {"ativo": 0, "quieto": 1}
    fila = []
    for p in projetos:
        if p.get("categoria") != "Token" or not p.get("emissor"):
            continue
        if p.get("situacao") not in SITUACOES_LIDAS:
            continue
        r = origens.get(coletor.chave_do_projeto(p))
        if r:
            idade = (hoje - dt.date.fromisoformat(r["medido_em"][:10])).days
            if idade < CICLO_DIAS:
                continue
        fila.append((0 if not r else 1, peso.get(p.get("situacao"), 9), -(p.get("holders") or 0), p))
    fila.sort(key=lambda t: t[:3])
    return [t[3] for t in fila]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--minutos", type=int, default=ORCAMENTO_MINUTOS, help="teto de tempo; 0 desliga")
    ap.add_argument("--limite", type=int, default=0, help="no maximo N tokens")
    ap.add_argument("--token", action="append", default=[], help="MOEDA:EMISSOR (repetivel)")
    args = ap.parse_args()

    try:
        conhecidas = contas_conhecidas()
    except FALHAS_DE_REDE as e:
        # Sem a lista, toda exchange viraria "fabrica". Melhor nao ler hoje.
        print(f"! lista de contas conhecidas indisponivel ({e}); origem nao lida hoje", file=sys.stderr)
        return

    projetos = coletor.carregar_projetos()
    origens = carregar_origens()
    cache = carregar_ativadores()
    if args.token:
        por_id = {(p.get("moeda"), p.get("emissor")): p for p in projetos}
        fila = []
        for t in args.token:
            moeda, emissor = t.split(":", 1)
            fila.append(por_id.get((moeda, emissor)) or {"nome": moeda, "moeda": moeda, "emissor": emissor})
    else:
        fila = alvos(projetos, origens, dt.date.today())
    if args.limite:
        fila = fila[: args.limite]
    print(f"origem: {len(fila)} tokens na fila, {len(cache)} ativadoras em cache")

    fim = time.time() + args.minutos * 60 if args.minutos else None
    lidos = 0
    try:
        for p in fila:
            if fim and time.time() > fim:
                print("origem: teto de tempo; o resto fica para amanha")
                break
            try:
                r = ler_origem(p, cache, conhecidas)
            except FALHAS_DE_REDE as e:
                print(f"  ! {p.get('nome')}: {e}", file=sys.stderr)
                continue
            origens[coletor.chave_do_projeto(p)] = r
            lidos += 1
            n = nota(r, p["emissor"])
            if n:
                print(f"  {p.get('nome')}: {n['texto']}")
    finally:
        # O trabalho caro (ativadoras) nunca se perde, nem se a corrida cair.
        salvar_ativadores(cache)
        salvar_origens(origens)
    com_nota = sum(1 for p in projetos if nota(origens.get(coletor.chave_do_projeto(p)), p.get("emissor")))
    print(f"origem: {lidos} lidos hoje; {len(origens)} tokens com leitura, {com_nota} com nota")


if __name__ == "__main__":
    main()
