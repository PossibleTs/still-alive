#!/usr/bin/env python3
"""
Testa a identidade de projeto entre coletas - sem tocar na rede.

Um projeto so tem historico e tendencia se a chave que o identifica for
estavel de uma coleta para a outra. Isso ja quebrou uma vez neste projeto
(a chave usava so o emissor, e 12 emissores emitem mais de uma moeda - ver
o commit a6bfa95) e o proprio auditor apontou um segundo jeito de quebrar:
o mesmo codigo de moeda padrao (3 letras) tem duas serializacoes validas
para o mesmo valor on-ledger, curta ("USD") e longa (40 hex). Este arquivo
prova que as duas colapsam na mesma chave.
"""

from coletor import chave_do_projeto, moeda_canonica

FALHAS = []


def checa(nome: str, obtido, esperado) -> None:
    ok = obtido == esperado
    print(f"  {'ok  ' if ok else 'FALHA'} {nome}: {obtido!r}" + ("" if ok else f" (esperava {esperado!r})"))
    if not ok:
        FALHAS.append(nome)


def main() -> None:
    print("Codigo padrao de 3 letras: curto e longo sao o MESMO valor")
    checa("forma curta", moeda_canonica("USD"), "USD")
    checa("caixa baixa", moeda_canonica("usd"), "USD")
    checa(
        "forma longa (12 zero + USD + 5 zero)",
        moeda_canonica("0000000000000000000000005553440000000000"),
        "USD",
    )
    checa(
        "EUR pela forma longa",
        moeda_canonica("0000000000000000000000004555520000000000".replace("4555", "4555")),
        moeda_canonica("EUR"),
    )

    print("\nCodigo nao-padrao (nome > 3 letras): so existe uma forma, sem ambiguidade")
    checa("SOLO permanece hex", moeda_canonica("534F4C4F00000000000000000000000000000000"),
          "534F4C4F00000000000000000000000000000000")
    checa("X de 1 letra na posicao errada permanece hex",
          moeda_canonica("5800000000000000000000000000000000000000"),
          "5800000000000000000000000000000000000000")
    checa("RLUSD permanece hex", moeda_canonica("524C555344000000000000000000000000000000"),
          "524C555344000000000000000000000000000000")

    print("\nVazio e None nao explodem")
    checa("vazio", moeda_canonica(""), "")
    checa("None", moeda_canonica(None), "")

    print("\nchave_do_projeto() usa a forma canonica")
    p_curto = {"emissor": "rABC", "moeda_hex": "USD"}
    p_longo = {"emissor": "rABC", "moeda_hex": "0000000000000000000000005553440000000000"}
    checa(
        "mesmo emissor, mesmo USD, formas diferentes -> mesma chave",
        chave_do_projeto(p_curto) == chave_do_projeto(p_longo),
        True,
    )
    p_outro_emissor = {"emissor": "rXYZ", "moeda_hex": "USD"}
    checa(
        "emissor diferente -> chave diferente mesmo com o mesmo codigo",
        chave_do_projeto(p_curto) != chave_do_projeto(p_outro_emissor),
        True,
    )

    print()
    if FALHAS:
        print(f"{len(FALHAS)} falha(s):", ", ".join(FALHAS))
        raise SystemExit(1)
    print("A identidade do projeto resiste a troca de serializacao do codigo de moeda.")


if __name__ == "__main__":
    main()
