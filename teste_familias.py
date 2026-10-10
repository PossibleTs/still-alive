#!/usr/bin/env python3
"""
Testa a regra da nota de origem dos detentores - sem tocar na rede.

A nota e a primeira coisa na pagina que pode soar como acusacao. Cada caso
aqui e um jeito de errar que apareceu (ou quase) no piloto de 300 tokens.
"""

import datetime as dt
import os
import tempfile

import familias
from familias import NOTA_FRACAO, NOTA_MINIMO, alvos, nota

FALHAS = []
EMISSOR = "rEMISSOR1111111111111111111111111"
FABRICA = "rFABRICA1111111111111111111111111"


def checa(nome: str, obtido, esperado) -> None:
    ok = obtido == esperado
    print(f"  {'ok  ' if ok else 'FALHA'} {nome}: {obtido!r}" + ("" if ok else f" (esperava {esperado!r})"))
    if not ok:
        FALHAS.append(nome)


def leitura(grupos: dict, amostra: int = 60, ativ_emissor=None) -> dict:
    return {"medido_em": "2026-10-09T12:00:00+00:00", "amostra": amostra, "pools": 0,
            "via_conhecida": 0, "sem_resposta": 0, "unicas": 0,
            "ativadora_do_emissor": ativ_emissor, "grupos": grupos}


def main() -> None:
    print("Limiares: os dois juntos, nunca um so (poeira em todos os casos)")
    checa("58 de 60 de uma carteira, 0.4% da oferta -> nota", bool(nota(leitura({FABRICA: [58, 0.4]}), EMISSOR)), True)
    checa(f"{NOTA_MINIMO - 1} de 60 -> sem nota (servico chega a 9 por token)",
          nota(leitura({FABRICA: [NOTA_MINIMO - 1, 0.1]}), EMISSOR), None)
    checa("11 de 60 (18%) -> sem nota", nota(leitura({FABRICA: [11, 0.1]}), EMISSOR), None)
    checa("10 de 20 -> nota", bool(nota(leitura({FABRICA: [10, 0.1]}, amostra=20), EMISSOR)), True)
    checa("fracao exata no limite conta", bool(nota(leitura({FABRICA: [12, 0.1]}), EMISSOR)),
          12 / 60 >= NOTA_FRACAO)

    print("\nSo inflacao de contagem: quem segura oferta de verdade nao e assunto da pagina")
    checa("AUG (ouro da Phi Wallet: 59 de 60, 36.6% da oferta) -> sem nota",
          nota(leitura({FABRICA: [59, 36.6]}), EMISSOR), None)
    checa("emissor que distribuiu 63.6% -> sem nota (concentracao, outro assunto)",
          nota(leitura({EMISSOR: [60, 63.6]}), EMISSOR), None)
    checa("limite: exatamente o teto ja nao tem nota",
          nota(leitura({FABRICA: [30, familias.SELO_OFERTA_MAXIMA]}), EMISSOR), None)
    checa("logo abaixo do teto tem", bool(nota(leitura({FABRICA: [30, familias.SELO_OFERTA_MAXIMA - 0.01]}), EMISSOR)), True)

    print("\nSem leitura nao ha nota (falta de dado nao acusa), e leitura velha sai")
    checa("sem registro", nota(None, EMISSOR), None)
    checa("amostra vazia", nota(leitura({}, amostra=0), EMISSOR), None)
    checa("sem grupos", nota(leitura({}), EMISSOR), None)
    velha = leitura({FABRICA: [40, 0.1]})
    checa("dentro da validade aparece", bool(nota(velha, EMISSOR, dt.date(2026, 11, 1))), True)
    checa(f"com mais de {familias.VALIDADE_DIAS} dias some", nota(velha, EMISSOR, dt.date(2027, 1, 1)), None)

    print("\nQuem criou: o proprio emissor e dito com essas palavras")
    n = nota(leitura({EMISSOR: [60, 0.2]}), EMISSOR)
    checa("emissor como ativadora", n["do_emissor"], True)
    checa("texto nomeia o emissor", "by the issuer itself" in n["texto"], True)
    n = nota(leitura({FABRICA: [40, 0.3]}, ativ_emissor=FABRICA), EMISSOR)
    checa("quem criou o emissor tambem conta como emissor", n["do_emissor"], True)
    n = nota(leitura({FABRICA: [40, 0.3]}), EMISSOR)
    checa("carteira qualquer: endereco curto no texto", "rFABRI…1111" in n["texto"], True)

    print("\nO texto carrega a conta (regra do projeto)")
    checa("numero e amostra", "40 of the top 60" in n["texto"], True)
    checa("fatia da oferta", "0.3% of supply" in n["texto"], True)
    checa("diz o que significa", "add to the holder count without holding it" in n["texto"], True)
    checa("data da leitura", "2026-10-09" in n["texto"], True)

    print("\nFamilia: fabrica que se divide nao escapa (a rede dos 9 tokens do piloto)")
    PAI = "rPAIPAIPAI111111111111111111111111"
    rede = {PAI: [9, 0.01, None], "rFILHA1": [11, 0.01, PAI], "rFILHA2": [9, 0.01, PAI]}
    n = nota(leitura(rede), EMISSOR)
    checa("nenhuma passa sozinha, a familia soma 29", n and n["n"], 29)
    checa("tres carteiras na familia", n and len(n["carteiras"]), 3)
    checa("texto diz que sao relacionadas", n and "3 related wallets" in n["texto"], True)
    checa("poeira e dita como poeira", n and "less than 0.1% of supply" in n["texto"], True)
    irmas = {"rIRMA1": [6, 0.2, PAI], "rIRMA2": [6, 0.2, PAI]}
    n = nota(leitura(irmas), EMISSOR)
    checa("duas irmas do mesmo pai privado somam 12", n and n["n"], 12)
    checa("texto nomeia o pai", n and "all created by rPAIPA" in n["texto"], True)
    sozinha = {"rSO1": [6, 0.2, PAI], "rSO2": [6, 0.2, "rOUTRO"]}
    checa("pais diferentes nao se juntam", nota(leitura(sozinha), EMISSOR), None)
    checa("leitura antiga sem pai ainda funciona",
          bool(nota(leitura({FABRICA: [30, 0.3]}), EMISSOR)), True)

    print("\nMaior grupo vence, empate decide pela oferta")
    n = nota(leitura({FABRICA: [20, 1.0], EMISSOR: [30, 0.5]}), EMISSOR)
    checa("30 > 20", n["n"], 30)

    print("\nRodizio: so alive e quiet; nunca lidos primeiro, vivos antes, ninguem dentro do ciclo")
    hoje = dt.date(2026, 10, 9)
    proj = [
        {"categoria": "Token", "emissor": "rA", "moeda": "AAA", "situacao": "quieto", "holders": 900},
        {"categoria": "Token", "emissor": "rB", "moeda": "BBB", "situacao": "ativo", "holders": 100},
        {"categoria": "Token", "emissor": "rC", "moeda": "CCC", "situacao": "ativo", "holders": 500},
        {"categoria": "Token", "emissor": "rD", "moeda": "DDD", "situacao": "ativo", "holders": 9000},
        {"categoria": "Carteira", "site": "x"},
        {"categoria": "Token", "emissor": "rE", "moeda": "EEE", "situacao": "indeterminado", "holders": 99999},
        {"categoria": "Token", "emissor": "rF", "moeda": "FFF", "situacao": "morto", "holders": 99999},
    ]
    origens = {
        "rC:CCC": {"medido_em": "2026-10-01T00:00:00+00:00"},   # dentro do ciclo
        "rD:DDD": {"medido_em": "2026-08-01T00:00:00+00:00"},   # vencido
    }
    checa("ordem", [p["moeda"] for p in alvos(proj, origens, hoje)], ["BBB", "AAA", "DDD"])

    print("\nArquivo de uma linha por token continua JSON valido")
    with tempfile.TemporaryDirectory() as d:
        caminho = os.path.join(d, "o.json")
        dados = {"rB:BBB": leitura({FABRICA: [12, 1.5]}), "rA:AAA": leitura({})}
        familias.salvar_origens(dados, caminho)
        checa("ida e volta", familias.carregar_origens(caminho), dados)
        with open(caminho, encoding="utf-8") as f:
            checa("uma linha por token", sum(1 for l in f if l.startswith('  "r')), 2)

    print()
    if FALHAS:
        print(f"{len(FALHAS)} falha(s):", ", ".join(FALHAS))
        raise SystemExit(1)
    print("A nota so fala de inflacao de contagem, com os dois limiares e a conta,")
    print("e falta de dado nunca vira acusacao.")


if __name__ == "__main__":
    main()
