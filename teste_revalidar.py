#!/usr/bin/env python3
"""
Exercita os freios do pedido de remedicao, sem tocar a rede.

O botao de revalidar e a unica porta pela qual um estranho faz este
repositorio gastar chamadas no no publico da XRPL. Os limites sao a parte que
precisa estar certa; a medicao em si ja e testada pelos outros arquivos.
"""

from __future__ import annotations

import datetime as dt

from revalidar import (
    POR_PESSOA_DIA,
    TETO_DIARIO,
    achar,
    avaliar_limites,
    candidatos,
)

FALHAS = []


def checa(nome: str, condicao: bool) -> None:
    print(f"  {'ok  ' if condicao else 'FALHA'} {nome}")
    if not condicao:
        FALHAS.append(nome)


def agora_menos(horas: float) -> str:
    return (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=horas)
    ).isoformat(timespec="seconds")


def hoje_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    print("Busca de projeto")
    lista = [
        {"nome": "Alpha", "emissor": "rAAA", "moeda_hex": "AAA"},
        {"nome": "Beta", "emissor": "rBBB", "moeda_hex": "BBB"},
    ]
    checa("acha pelo nome, sem ligar para caixa", achar(lista, "alpha") is not None)
    checa("acha pelo emissor", achar(lista, "rBBB") is not None)
    checa("nao inventa projeto que nao existe", achar(lista, "rZZZ") is None)

    print("\nAmbiguidade: nome nao identifica projeto")
    # A ordem imita a lista real: ela chega ordenada por situacao e detentores,
    # entao o homonimo saudavel vem primeiro. Devolver "o primeiro" media o
    # projeto errado e respondia com o nome pedido.
    homonimos = [
        {"nome": "GCB", "emissor": "rVIVO", "moeda_hex": "GCB", "situacao": "ativo"},
        {"nome": "GCB", "emissor": "rMORTO", "moeda_hex": "GCB", "situacao": "morto"},
    ]
    checa("nao escolhe entre dois nomes iguais", achar(homonimos, "GCB") is None)
    checa("mostra os dois candidatos", len(candidatos(homonimos, "GCB")) == 2)
    checa(
        "a chave completa desempata",
        (achar(homonimos, "rMORTO:GCB") or {}).get("emissor") == "rMORTO",
    )

    # Mesmo emissor, duas moedas: e o caso da Bitstamp (US Dollar e Euro).
    duas_moedas = [
        {"nome": "US Dollar", "emissor": "rHUB", "moeda_hex": "USD"},
        {"nome": "Euro", "emissor": "rHUB", "moeda_hex": "EUR"},
    ]
    checa("emissor com duas moedas nao identifica", achar(duas_moedas, "rHUB") is None)
    checa(
        "emissor:moeda identifica",
        (achar(duas_moedas, "rHUB:EUR") or {}).get("nome") == "Euro",
    )
    checa("nome unico ainda funciona", achar(duas_moedas, "euro") is not None)

    print("\nEspera entre medicoes do mesmo projeto")
    recente = {"nome": "Alpha", "medido_em": agora_menos(1)}
    velho = {"nome": "Alpha", "medido_em": agora_menos(48)}
    checa("recusa projeto medido ha 1h", avaliar_limites(recente, "eu", []) is not None)
    checa("aceita projeto medido ha 48h", avaliar_limites(velho, "eu", []) is None)
    checa(
        "aceita projeto nunca medido",
        avaliar_limites({"nome": "Alpha"}, "eu", []) is None,
    )

    print("\nLimite por pessoa")
    meus = [{"quando": hoje_iso(), "autor": "eu"} for _ in range(POR_PESSOA_DIA)]
    checa("recusa quem ja bateu a cota do dia", avaliar_limites(velho, "eu", meus) is not None)
    checa("nao pune outra pessoa pela cota alheia", avaliar_limites(velho, "voce", meus) is None)

    print("\nTeto do dia, somando todo mundo")
    muitos = [{"quando": hoje_iso(), "autor": f"p{i}"} for i in range(TETO_DIARIO)]
    checa("recusa quando o dia estourou", avaliar_limites(velho, "novo", muitos) is not None)

    ontem = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
    velhos = [{"quando": ontem, "autor": "eu"} for _ in range(TETO_DIARIO + 5)]
    checa("pedido de ontem nao conta para hoje", avaliar_limites(velho, "eu", velhos) is None)

    print()
    if FALHAS:
        print(f"{len(FALHAS)} falha(s):", ", ".join(FALHAS))
        raise SystemExit(1)
    print("Todos os freios passaram.")


if __name__ == "__main__":
    main()
