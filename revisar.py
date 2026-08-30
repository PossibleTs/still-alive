#!/usr/bin/env python3
"""
Ajuda a revisao humana da lista antes de publicar.

Imprime, em ordem de gravidade, todo projeto que a pagina vai acusar de morto,
parado ou moribundo - com os numeros que sustentam a acusacao ao lado. E o
passo que o HANDOFF chama de "leia projeto por projeto": aqui ele cabe numa
tela em vez de num HTML de 300 cartoes.

Uso:
    python revisar.py                # so os acusados
    python revisar.py --todos        # a lista inteira
"""

from __future__ import annotations

import argparse
import json

ORDEM = ["morto", "parado", "morrendo", "indeterminado", "ativo"]


def linha(p: dict) -> str:
    def n(x):
        return "?" if x is None else x

    return (
        f"  {p['nome'][:22]:24} "
        f"det={n(p.get('holders')):>7} "
        f"tr24={n(p.get('trocas_24h')):>6} "
        f"tx={n(p.get('tx_janela')):>5}{'+' if p.get('tx_truncado') else ' '} "
        f"emis={n(p.get('tx_emissor')):>4} "
        f"quieto={n(p.get('dias_sem_atividade')):>4}d "
        f"emis_quieto={n(p.get('dias_sem_emissor')):>5}d "
        f"site={str(p.get('site_ok')):5} "
        f"bh={str(p.get('blackholed'))[:1]}\n"
        f"      {p.get('site') or '(sem site)'}\n"
        f"      -> {p.get('motivo','')}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arquivo", default="dados.json")
    ap.add_argument("--todos", action="store_true")
    args = ap.parse_args()

    with open(args.arquivo, encoding="utf-8") as f:
        dados = json.load(f)

    print(f"{dados.get('gerado_em')} | {dados.get('total')} projetos | {dados.get('contagem')}")

    falhou = [p for p in dados["projetos"] if p.get("erro_medicao")]
    if falhou:
        print(f"\n!! {len(falhou)} projetos nao foram medidos:")
        for p in falhou:
            print(f"   {p['nome'][:24]:26} {p['erro_medicao']}")

    alvos = ORDEM if args.todos else ORDEM[:4]
    for situacao in alvos:
        do_grupo = [p for p in dados["projetos"] if p["situacao"] == situacao]
        if not do_grupo:
            continue
        print(f"\n=== {situacao.upper()} ({len(do_grupo)})")
        for p in do_grupo:
            print(linha(p))


if __name__ == "__main__":
    main()
