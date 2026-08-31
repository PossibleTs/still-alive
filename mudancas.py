#!/usr/bin/env python3
"""
O que mudou entre duas medicoes - material pronto para post.

Por que existe: a pagina, sozinha, e um objeto estatico. Ninguem segue um
objeto estatico. O que da razao para acompanhar e a MUDANCA: "3 projetos
cruzaram para dormant nesta semana, e um voltou". Isso a pagina produz de
graca, todo dia, e ninguem estava lendo.

Le os snapshots de historico/ e compara dois. Imprime em ingles porque a saida
e para publicar; o cabecalho e em PT-BR porque quem le a saida crua e o quem mantem o projeto.

Uso:
    python mudancas.py                    # ultimo contra 7 dias antes
    python mudancas.py --dias 1           # ontem
    python mudancas.py --de 2026-08-31 --para 2026-09-07
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os

PASTA = "historico"

# Ordem de gravidade. Descer nessa lista e piorar.
ESCALA = ["ativo", "morrendo", "parado", "morto"]
ROTULO = {
    "ativo": "alive",
    "morrendo": "fading",
    "parado": "dormant",
    "morto": "dead",
    "indeterminado": "unknown",
}


def snapshots() -> list[str]:
    return sorted(glob.glob(os.path.join(PASTA, "*.json")))


def carregar(caminho: str) -> dict:
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def _data(caminho: str) -> str:
    return os.path.basename(caminho)[:-5]


def escolher(dias: int, de: str | None, para: str | None) -> tuple[str, str]:
    todos = snapshots()
    if not todos:
        raise SystemExit(f"! nenhum snapshot em {PASTA}/")
    if de and para:
        return os.path.join(PASTA, f"{de}.json"), os.path.join(PASTA, f"{para}.json")

    novo = todos[-1]
    alvo = dt.date.fromisoformat(_data(novo)) - dt.timedelta(days=dias)
    # O snapshot mais proximo do alvo, sem passar dele.
    anteriores = [c for c in todos if _data(c) <= alvo.isoformat()]
    velho = anteriores[-1] if anteriores else todos[0]
    if velho == novo:
        raise SystemExit("! so existe um snapshot; nao ha o que comparar ainda")
    return velho, novo


def piorou(antes: str, depois: str) -> bool:
    if antes not in ESCALA or depois not in ESCALA:
        return False
    return ESCALA.index(depois) > ESCALA.index(antes)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=7)
    ap.add_argument("--de")
    ap.add_argument("--para")
    args = ap.parse_args()

    cv, cn = escolher(args.dias, args.de, args.para)
    velho, novo = carregar(cv), carregar(cn)
    d_velho, d_novo = _data(cv), _data(cn)

    print(f"# {d_velho} -> {d_novo}  ({len(velho)} -> {len(novo)} projetos)\n")

    def nome(chave: str, reg: dict) -> str:
        return reg.get("nome") or chave

    trocas = []
    for chave, reg in novo.items():
        antes = (velho.get(chave) or {}).get("situacao")
        agora = reg.get("situacao")
        if antes and agora and antes != agora:
            trocas.append((chave, reg, antes, agora))

    # Sem situacao nos snapshots antigos nao ha comparacao possivel.
    if not any((velho.get(k) or {}).get("situacao") for k in velho):
        print("(o snapshot antigo nao guardava a situacao; o primeiro"
              " comparativo util sai na proxima coleta)\n")

    caiu = [t for t in trocas if piorou(t[2], t[3])]
    subiu = [t for t in trocas if piorou(t[3], t[2])]
    novos = [k for k in novo if k not in velho]
    sairam = [k for k in velho if k not in novo]

    print("## Para publicar\n")
    if caiu:
        print(f"{len(caiu)} project(s) declined this week:")
        for chave, reg, antes, agora in sorted(
            caiu, key=lambda t: -(t[1].get("holders") or 0)
        ):
            h = reg.get("holders")
            print(f"  - {nome(chave, reg)}"
                  f"{f' ({h:,} holders)' if isinstance(h, int) else ''}: "
                  f"{ROTULO.get(antes, antes)} -> {ROTULO.get(agora, agora)}")
            print(f"      {reg.get('motivo', '')}")
            print(f"      {chave}")
    if subiu:
        print(f"\n{len(subiu)} project(s) recovered:")
        for chave, reg, antes, agora in subiu:
            print(f"  - {nome(chave, reg)}: "
                  f"{ROTULO.get(antes, antes)} -> {ROTULO.get(agora, agora)}")
            print(f"      {reg.get('motivo', '')}")
    if novos:
        print(f"\n{len(novos)} project(s) measured for the first time.")
    if sairam:
        print(f"\n{len(sairam)} project(s) left the scope.")
    if not (caiu or subiu or novos or sairam):
        print("Nada mudou de situacao. Semana sem noticia - e isso tambem e"
              " informacao: a rede nao esta morrendo mais rapido do que ontem.")

    # Movimento de detentores: a outra fonte de assunto, e a que aparece antes
    # de a situacao mudar.
    quedas = []
    for chave, reg in novo.items():
        a = (velho.get(chave) or {}).get("holders")
        b = reg.get("holders")
        if isinstance(a, int) and isinstance(b, int) and a >= 500:
            var = (b - a) / a * 100
            if abs(var) >= 5:
                quedas.append((var, chave, reg, a, b))
    if quedas:
        quedas.sort(key=lambda q: q[0])
        print("\n## Biggest holder swings (>=5%, projects above 500 holders)\n")
        for var, chave, reg, a, b in quedas[:10]:
            print(f"  {var:+6.1f}%  {nome(chave, reg):22} {a:,} -> {b:,}")

    print("\n## Contagem por situacao\n")
    for k in ESCALA + ["indeterminado"]:
        antes = sum(1 for r in velho.values() if r.get("situacao") == k)
        agora = sum(1 for r in novo.values() if r.get("situacao") == k)
        seta = "" if antes == agora else f"  ({agora - antes:+d})"
        print(f"  {ROTULO[k]:10} {antes:4} -> {agora:4}{seta}")


if __name__ == "__main__":
    main()
