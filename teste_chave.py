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

import datetime as dt

from coletor import aplicar_tendencia, chave_do_projeto, mesclar, moeda_canonica

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

    print("\nmesclar() carrega a medicao anterior para calcular tendencia depois")
    ha_5_dias = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=5)).isoformat(timespec="seconds")
    ha_15_dias = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=15)).isoformat(timespec="seconds")
    agora = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    antigos = [
        {"nome": "Topo", "emissor": "rTOPO", "moeda_hex": "TOP", "holders": 1000, "medido_em": ha_5_dias},
        {"nome": "Cauda", "emissor": "rCAUDA", "moeda_hex": "TAI", "holders": 1000, "medido_em": ha_15_dias},
    ]
    novos = [
        {"nome": "Topo", "emissor": "rTOPO", "moeda_hex": "TOP", "holders": 1050, "medido_em": agora},
        {"nome": "Cauda", "emissor": "rCAUDA", "moeda_hex": "TAI", "holders": 1150, "medido_em": agora},
    ]
    mesclados = mesclar(antigos, novos)
    por_nome = {p["nome"]: p for p in mesclados}
    checa("Topo carrega holders_anterior", por_nome["Topo"].get("holders_anterior"), 1000)
    checa("Cauda carrega holders_anterior", por_nome["Cauda"].get("holders_anterior"), 1000)

    aplicar_tendencia(mesclados)
    print("\naplicar_tendencia() usa a janela real de CADA projeto, nao uma data comum")
    # Mesmos +5% e +15% em holders, mas o Topo levou 5 dias e a Cauda 15 - se a
    # taxa (%/dia) nao bater, a comparacao entre os dois volta a ser injusta.
    checa("Topo: +5.0% em ~5 dias", por_nome["Topo"].get("variacao_holders"), 5.0)
    checa("Topo: janela de 5 dias", por_nome["Topo"].get("dias_variacao"), 5)
    checa("Cauda: +15.0% em ~15 dias", round(por_nome["Cauda"].get("variacao_holders"), 1), 15.0)
    checa("Cauda: janela de 15 dias", por_nome["Cauda"].get("dias_variacao"), 15)
    taxa_topo = por_nome["Topo"]["variacao_holders"] / por_nome["Topo"]["dias_variacao"]
    taxa_cauda = por_nome["Cauda"]["variacao_holders"] / por_nome["Cauda"]["dias_variacao"]
    checa(
        "por taxa (%/dia) as duas ficam quase empatadas, nao 15% > 5%",
        abs(taxa_topo - taxa_cauda) < 0.1,
        True,
    )

    print("\nProjeto sem medicao anterior nao gera tendencia (e nao explode)")
    so_agora = mesclar([], [{"nome": "Novo", "emissor": "rNOVO", "moeda_hex": "NEW",
                              "holders": 100, "medido_em": agora}])
    aplicar_tendencia(so_agora)
    checa("sem holders_anterior, sem variacao_holders", "variacao_holders" in so_agora[0], False)

    print()
    if FALHAS:
        print(f"{len(FALHAS)} falha(s):", ", ".join(FALHAS))
        raise SystemExit(1)
    print("A identidade do projeto resiste a troca de serializacao do codigo de moeda,")
    print("e a tendencia compara cada projeto com a sua propria janela, nunca com a de outro.")


if __name__ == "__main__":
    main()
