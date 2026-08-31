#!/usr/bin/env python3
"""
Atende um pedido de remedicao de UM projeto, vindo de uma issue no GitHub.

Por que existe: a cauda do catalogo e remedida em rodizio, entao o dado de um
projeto pode ter ate duas semanas. Quem discorda da classificacao precisa de um
jeito de pedir "olha de novo, agora" sem esperar a vez dele no ciclo. Esse e o
mesmo canal de contestacao que a pagina promete - so que ele mede em vez de
discutir.

Por que tem freio: e um botao que faz um estranho gastar chamadas ao no publico
da XRPL em nome do projeto. Sem limite, vira um scanner gratuito para quem
quiser, e o no publico e de graca por gentileza, nao por direito.

As regras, todas checadas aqui e nao no YAML do workflow:

  1. So projeto que JA esta na lista. Nunca um endereco arbitrario - senao o
     repositorio vira um servico de consulta a XRPL para qualquer um.
  2. Um projeto so e remedido de novo depois de ESPERA_HORAS.
  3. Cada pessoa tem POR_PESSOA_DIA pedidos por dia.
  4. O dia inteiro tem TETO_DIARIO pedidos, somando todo mundo.

Uso:
    python revalidar.py --projeto "NOME" --autor "login"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from coletor import (
    _medir,
    carregar_projetos,
    chave_do_projeto,
    classificar,
    mesclar,
)

REGISTRO = "revalidacoes.json"
ESPERA_HORAS = 12
POR_PESSOA_DIA = 3
TETO_DIARIO = 20


def _agora() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _ler_registro() -> list[dict]:
    if not os.path.exists(REGISTRO):
        return []
    try:
        with open(REGISTRO, encoding="utf-8") as f:
            return json.load(f).get("pedidos") or []
    except (json.JSONDecodeError, OSError):
        return []


def _gravar_registro(pedidos: list[dict]) -> None:
    # Guarda so os ultimos 30 dias: o registro existe para aplicar limite, nao
    # para virar arquivo historico de quem pediu o que.
    corte = (_agora() - dt.timedelta(days=30)).isoformat()
    pedidos = [p for p in pedidos if p.get("quando", "") >= corte]
    with open(REGISTRO, "w", encoding="utf-8") as f:
        json.dump({"pedidos": pedidos}, f, ensure_ascii=False, indent=1)


def _horas_desde(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        quando = dt.datetime.fromisoformat(iso)
    except ValueError:
        return None
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=dt.timezone.utc)
    return (_agora() - quando).total_seconds() / 3600


def achar(projetos: list[dict], nome: str) -> dict | None:
    """Procura por nome, emissor ou chave. Nome bate sem diferenciar caixa."""
    alvo = nome.strip().lower()
    for p in projetos:
        if alvo in (
            str(p.get("nome", "")).lower(),
            str(p.get("emissor", "")).lower(),
            chave_do_projeto(p).lower(),
        ):
            return p
    return None


def avaliar_limites(projeto: dict, autor: str, pedidos: list[dict]) -> str | None:
    """Devolve o motivo da recusa, ou None se pode medir."""
    horas = _horas_desde(projeto.get("medido_em"))
    if horas is not None and horas < ESPERA_HORAS:
        return (
            f"This project was measured {horas:.0f}h ago. We only recheck after "
            f"{ESPERA_HORAS}h - below that the result would be the same and the "
            "call would be wasted on the network's public node."
        )

    hoje = _agora().date().isoformat()
    do_dia = [p for p in pedidos if p.get("quando", "")[:10] == hoje]
    if len(do_dia) >= TETO_DIARIO:
        return (
            f"We have already done {TETO_DIARIO} rechecks today, which is the "
            "daily cap. Try tomorrow - or wait for this project's turn in the "
            "rotation."
        )

    do_autor = [p for p in do_dia if p.get("autor") == autor]
    if len(do_autor) >= POR_PESSOA_DIA:
        return (
            f"You have already asked for {len(do_autor)} rechecks today, and the "
            f"per-person limit is {POR_PESSOA_DIA} per day."
        )
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projeto", required=True)
    ap.add_argument("--autor", default="anonimo")
    args = ap.parse_args()

    projetos = carregar_projetos()
    if not projetos:
        print("Could not read the project list. Nothing was measured.")
        return

    alvo = achar(projetos, args.projeto)
    if alvo is None:
        print(
            f"I could not find **{args.projeto}** in the list. This page only "
            "rechecks what it already tracks - it does not look up arbitrary "
            "addresses on the ledger. If the project should be here and is not, "
            "tell me the issuer address and we will consider adding it."
        )
        return

    pedidos = _ler_registro()
    recusa = avaliar_limites(alvo, args.autor, pedidos)
    if recusa:
        print(recusa)
        return

    antes = alvo.get("situacao")
    agora_ts = int(_agora().timestamp())
    try:
        _medir(alvo, agora_ts)
    except Exception as e:  # rede pode falhar; o pedido nao pode explodir
        print(f"The measurement failed just now ({type(e).__name__}). Try later.")
        return

    alvo["medido_em"] = _agora().isoformat(timespec="seconds")
    alvo["situacao"], alvo["motivo"] = classificar(alvo)

    pedidos.append(
        {
            "quando": _agora().isoformat(timespec="seconds"),
            "autor": args.autor,
            "projeto": alvo.get("nome"),
        }
    )
    _gravar_registro(pedidos)

    projetos = mesclar(projetos, [alvo])
    with open("dados.json", encoding="utf-8") as f:
        dados = json.load(f)
    dados["projetos"] = projetos
    dados["contagem"] = {
        s: sum(1 for p in projetos if p["situacao"] == s)
        for s in ("ativo", "morrendo", "parado", "morto", "indeterminado")
    }
    with open("dados.json", "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)

    mudou = "" if antes == alvo["situacao"] else f" (was: **{antes}**)"
    print(
        f"Measured just now: **{alvo['nome']}** is **{alvo['situacao']}**{mudou}.\n\n"
        f"> {alvo['motivo']}\n\n"
        "The page updates on the next publication. If you disagree with the "
        "criteria rather than the numbers, reply here - the cut-offs are "
        "arguable on purpose."
    )


if __name__ == "__main__":
    main()
