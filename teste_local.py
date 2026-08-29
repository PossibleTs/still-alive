#!/usr/bin/env python3
"""
Teste local sem tocar na rede.

Monta casos sinteticos que exercitam cada ramo da classificacao e gera a pagina
a partir deles, para voce conferir a logica e o visual antes de rodar o coletor
de verdade. Os numeros aqui sao INVENTADOS - servem so para testar o codigo.

    python teste_local.py && python gerar_site.py
"""

import datetime as dt
import json

from coletor import LIMIARES, classificar

CASOS = [
    # (descricao esperada, projeto)
    ("ativo normal", {
        "nome": "Token movimentado", "categoria": "Token", "emissor": "rTESTE1",
        "site": "exemplo.test", "holders": 12000, "tx_janela": 4200,
        "dias_sem_atividade": 0, "site_ok": True, "blackholed": False,
        "trocas_24h": 300, "variacao_holders": 4.2}),
    ("emissor blackholed com vida", {
        "nome": "Token blackholed vivo", "categoria": "Token", "emissor": "rTESTE2",
        "site": "exemplo.test", "holders": 8000, "tx_janela": 0,
        "dias_sem_atividade": 900, "site_ok": True, "blackholed": True,
        "trocas_24h": 45}),
    ("emissor blackholed sem negociacao", {
        "nome": "Token blackholed quieto", "categoria": "Token", "emissor": "rTESTE3",
        "site": "", "holders": 900, "tx_janela": 0, "dias_sem_atividade": 1200,
        "site_ok": None, "blackholed": True, "trocas_24h": 0}),
    ("morrendo por volume baixo", {
        "nome": "Token minguando", "categoria": "Token", "emissor": "rTESTE4",
        "site": "exemplo.test", "holders": 400, "tx_janela": 60,
        "dias_sem_atividade": 2, "site_ok": True, "blackholed": False,
        "trocas_24h": 1, "variacao_holders": -11.5}),
    ("parado", {
        "nome": "Projeto encostado", "categoria": "Token", "emissor": "rTESTE5",
        "site": "exemplo.test", "holders": 150, "tx_janela": 3,
        "dias_sem_atividade": 120, "site_ok": True, "blackholed": False,
        "trocas_24h": 0}),
    ("morto por tempo", {
        "nome": "Projeto da onda de NFT", "categoria": "Token", "emissor": "rTESTE6",
        "site": "exemplo.test", "holders": 80, "tx_janela": 0,
        "dias_sem_atividade": 800, "site_ok": False, "blackholed": False,
        "trocas_24h": 0}),
    ("morto por site fora do ar", {
        "nome": "Projeto sumido", "categoria": "Token", "emissor": "rTESTE7",
        "site": "exemplo.test", "holders": 30, "tx_janela": 2,
        "dias_sem_atividade": 40, "site_ok": False, "blackholed": False,
        "trocas_24h": 0}),
    ("ferramenta sem token, viva", {
        "nome": "Explorador qualquer", "categoria": "Explorador",
        "site": "exemplo.test", "site_ok": True, "dias_sem_atividade": None}),
    ("ferramenta sem token, morta", {
        "nome": "Ferramenta abandonada", "categoria": "Ferramenta",
        "site": "exemplo.test", "site_ok": False, "dias_sem_atividade": None}),
    ("indeterminado", {
        "nome": "Conta que nao respondeu", "categoria": "Token", "emissor": "rTESTE8",
        "site": "", "holders": 0, "tx_janela": 0, "dias_sem_atividade": None,
        "site_ok": None, "blackholed": False, "trocas_24h": 0}),
]


def main() -> None:
    projetos = []
    print("Classificacao dos casos de teste:\n")
    for descricao, p in CASOS:
        situacao, motivo = classificar(p)
        p["situacao"], p["motivo"] = situacao, motivo
        projetos.append(p)
        print(f"  {situacao:14} <- {descricao}")
        print(f"                  {motivo}")

    ordem = {"ativo": 0, "morrendo": 1, "parado": 2, "morto": 3, "indeterminado": 4}
    projetos.sort(key=lambda p: (ordem[p["situacao"]], -(p.get("holders") or 0)))

    dados = {
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "limiares": LIMIARES,
        "total": len(projetos),
        "contagem": {s: sum(1 for p in projetos if p["situacao"] == s) for s in ordem},
        "projetos": projetos,
        "AVISO": "DADOS SINTETICOS DE TESTE - nao sao medicoes reais da rede",
    }
    with open("dados.json", "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    print("\nContagem:", dados["contagem"])
    print("dados.json de teste escrito.")


if __name__ == "__main__":
    main()
