#!/usr/bin/env python3
"""
Exercita a fronteira entre "o projeto esta calado" e "nao conseguimos ler",
sem tocar a rede.

E a fronteira que a pagina mais precisa respeitar: tudo aqui existe porque em
07-13/09/2026 o no publico passou a responder `tooBusy` e a pagina traduziu
isso como "The issuer account did not respond" em 1141 dos 2184 projetos -
RLUSD e Bitcoin entre eles. Acusacao de terceiro feita com falha nossa.
"""

from __future__ import annotations

import json
import urllib.error

import coletor
from coletor import (
    NOS_RPC,
    PRIMEIRO_LEDGER,
    alvos_nao_medidos,
    atividade_da_conta,
    chaves_nao_medidas,
    classificar,
    conta_esta_blackholed,
    mesclar,
)

FALHAS = []


def checa(nome: str, condicao: bool) -> None:
    print(f"  {'ok  ' if condicao else 'FALHA'} {nome}")
    if not condicao:
        FALHAS.append(nome)


class _Resposta:
    """Imita o objeto de urlopen: context manager com read()."""

    def __init__(self, corpo: dict):
        self._corpo = json.dumps(corpo).encode("utf-8")

    def read(self) -> bytes:
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def finge_rede(por_no: dict):
    """Troca a rede por um dicionario {url do no: result ou excecao}."""
    chamadas = []

    def falso_urlopen(req, timeout=None):
        chamadas.append(req.full_url)
        saida = por_no.get(req.full_url, {"error": "tooBusy"})
        if isinstance(saida, Exception):
            raise saida
        return _Resposta({"result": saida})

    coletor.urllib.request.urlopen = falso_urlopen
    return chamadas


def main() -> None:
    real_urlopen = coletor.urllib.request.urlopen
    coletor.time.sleep = lambda _s: None  # o teste nao espera a espera

    print("Recusa do no nao e resposta da conta")
    coletor._NO_ATUAL = 0
    coletor._RECUSAS_SEGUIDAS = 0
    finge_rede({NOS_RPC[1]: {"account_data": {"Flags": 0}}})
    res = coletor._rpc("account_info", {"account": "rX"})
    checa("troca de no quando o primeiro diz tooBusy", res.get("error") is None)
    checa("o no que atendeu fica sendo o preferido", coletor._NO_ATUAL == 1)

    coletor._NO_ATUAL = 0
    coletor._RECUSAS_SEGUIDAS = 0
    finge_rede({NOS_RPC[1]: urllib.error.URLError("conexao caiu"),
                NOS_RPC[2]: {"account_data": {"Flags": 0}}})
    res = coletor._rpc("account_info", {"account": "rX"})
    checa("falha de rede tambem troca de no", res.get("error") is None)

    coletor._NO_ATUAL = 0
    coletor._RECUSAS_SEGUIDAS = 0
    finge_rede({})  # todos ocupados
    res = coletor._rpc("account_info", {"account": "rX"})
    checa("com todos ocupados, devolve o erro - nao um vazio", res.get("error") == "tooBusy")
    checa("blackholed vira None, nao False, quando ninguem respondeu",
          conta_esta_blackholed("rX") is None)

    print("\nDisjuntor: recusa geral nao pode virar corrida de 4 horas")
    coletor._NO_ATUAL = 0
    coletor._RECUSAS_SEGUIDAS = 0
    chamadas = finge_rede({})
    for _ in range(coletor.LIMITE_DE_INSISTENCIA):
        coletor._rpc("account_info", {"account": "rX"})
    gastas = len(chamadas)
    checa("enquanto ha esperanca, insiste nas duas voltas", gastas == coletor.LIMITE_DE_INSISTENCIA * len(NOS_RPC) * 2)
    chamadas.clear()
    coletor._rpc("account_info", {"account": "rX"})
    checa("passado o limite, uma volta so por pergunta", len(chamadas) == len(NOS_RPC))
    chamadas.clear()
    finge_rede({NOS_RPC[0]: {"account_data": {"Flags": 0}}})
    coletor._rpc("account_info", {"account": "rX"})
    checa("um no que volta a responder rearma a insistencia", coletor._RECUSAS_SEGUIDAS == 0)

    print("\nLeitura de historico")
    coletor._NO_ATUAL = 0
    coletor._RECUSAS_SEGUIDAS = 0
    finge_rede({NOS_RPC[0]: {"transactions": [], "ledger_index_min": PRIMEIRO_LEDGER}})
    sinais = atividade_da_conta("rX")
    checa("conta sem transacao nenhuma nao vira erro", sinais["erro"] is None)

    agora = int(coletor.time.time())
    tx_recente = {"tx_json": {"Account": "rOUTRO"},
                  "close_time_iso": None,
                  "tx": {"date": agora - coletor.RIPPLE_EPOCH, "Account": "rOUTRO"}}
    coletor._NO_ATUAL = 0
    coletor._RECUSAS_SEGUIDAS = 0
    finge_rede({NOS_RPC[0]: {"transactions": [tx_recente],
                             "ledger_index_min": PRIMEIRO_LEDGER + 90_000_000}})
    sinais = atividade_da_conta("rX")
    checa("no de historico curto nunca declara a janela coberta", sinais["truncado"] is True)

    # Uma leitura interrompida no meio nao pode virar "acabou o historico".
    coletor._NO_ATUAL = 0
    coletor._RECUSAS_SEGUIDAS = 0
    paginas = [{"transactions": [tx_recente] * 200, "marker": {"m": 1},
                "ledger_index_min": PRIMEIRO_LEDGER},
               {"error": "tooBusy"}]

    def uma_pagina_depois_recusa(req, timeout=None):
        return _Resposta({"result": paginas.pop(0) if paginas else {"error": "tooBusy"}})

    coletor.urllib.request.urlopen = uma_pagina_depois_recusa
    sinais = atividade_da_conta("rX")
    checa("leitura interrompida no meio conta como piso, nao como total",
          sinais["truncado"] is True and sinais["tx_janela"] == 200)

    coletor.urllib.request.urlopen = real_urlopen

    print("\nO que a pagina diz quando nao ha leitura")
    sem_leitura = {"nome": "Novo", "categoria": "Token", "emissor": "rN",
                   "holders": 500, "dias_sem_atividade": None}
    _, motivo = classificar(sem_leitura)
    checa("projeto ainda nao lido nao e acusado de nada", "queued" in motivo)

    recusado = dict(sem_leitura, erro_leitura="tooBusy", leitura_ok=False,
                    releitura_falhou_em="2026-09-14T03:17:00+00:00")
    situacao, motivo = classificar(recusado)
    checa("recusa do no aparece como limite da pagina", "refused the query" in motivo)
    checa("e diz que nao e sinal sobre o projeto", "says nothing about the project" in motivo)
    checa("nunca mais 'the issuer account did not respond' por tooBusy",
          "did not respond" not in motivo and situacao == "indeterminado")

    print("\nOrcamento de tempo: parar e gravar, nunca ser morto no meio")
    relogio = iter([1000, 1000, 1001] + [999_999] * 20)
    real_time, real_site = coletor.time.time, coletor.site_responde
    coletor.time.time = lambda: next(relogio)
    coletor.site_responde = lambda _url: True
    fila = [{"nome": f"Projeto {n}", "categoria": "Ferramenta", "site": "x.test"}
            for n in range(3)]
    coletor.coletar(fila, orcamento_minutos=1)
    coletor.time.time, coletor.site_responde = real_time, real_site
    checa("o que deu tempo foi medido", fila[0].get("leitura_ok") is True)
    checa("o resto fica marcado como nao medido",
          [p.get("erro_leitura") for p in fila[1:]] == [coletor.ORCAMENTO_ESGOTADO] * 2)
    checa("e a pagina diz que foi falta de tempo, nao falta de vida",
          "ran out of time" in fila[2]["motivo"] and fila[2]["situacao"] == "indeterminado")

    print("\nLeitura que falha nao apaga medicao boa")
    anterior = [{"nome": "Token", "categoria": "Token", "emissor": "rA", "moeda_hex": "AAA",
                 "holders": 9000, "dias_sem_atividade": 1, "tx_janela": 3000,
                 "tx_emissor": 40, "tx_truncado": False, "blackholed": False,
                 "trocas_7d": 80, "medido_em": "2026-09-10T03:20:00+00:00",
                 "ledger_em": "2026-09-10T03:20:00+00:00", "situacao": "ativo"}]
    hoje_falhou = [{"nome": "Token", "categoria": "Token", "emissor": "rA", "moeda_hex": "AAA",
                    "holders": 9100, "trocas_7d": 75, "dias_sem_atividade": None,
                    "leitura_ok": False, "erro_leitura": "tooBusy",
                    "medido_em": "2026-09-14T03:17:00+00:00",
                    "releitura_falhou_em": "2026-09-14T03:17:00+00:00"}]
    juntos = mesclar(anterior, hoje_falhou)
    p = juntos[0]
    checa("herda os sinais de ledger da medicao boa", p["tx_janela"] == 3000)
    checa("holders de hoje continuam sendo os de hoje", p["holders"] == 9100)
    checa("guarda a data real da leitura de ledger", p["ledger_em"].startswith("2026-09-10"))
    situacao, motivo = classificar(p)
    checa("o veredito sobrevive a recusa do no", situacao == "ativo")
    checa("e a pagina diz de quando e o dado", "measured on 2026-09-10" in motivo)

    novo_sem_historico = [{"nome": "Token", "categoria": "Token", "emissor": "rB",
                           "moeda_hex": "BBB", "holders": 300, "dias_sem_atividade": None,
                           "leitura_ok": False, "erro_leitura": "tooBusy"}]
    p2 = mesclar([], novo_sem_historico)[0]
    checa("sem medicao anterior, nao inventa uma", p2.get("tx_janela") is None)
    checa("e assume que nao sabe", classificar(p2)[0] == "indeterminado")

    print("\nA corrida de reparo alcanca quem o rodizio deixaria esperando")
    # Sem isto a espera e de ate CICLO_DIAS: em 07-13/09/2026 o no recusou dias
    # seguidos e 687 projetos ficaram doze dias na pagina como "nao medido",
    # sem nada de errado com eles.
    pagina = [
        {"nome": "Recusado", "categoria": "Token", "emissor": "rA", "moeda_hex": "AAA",
         "erro_leitura": "slowDown"},
        {"nome": "Sem tempo", "categoria": "Token", "emissor": "rB", "moeda_hex": "BBB",
         "erro_leitura": coletor.ORCAMENTO_ESGOTADO},
        {"nome": "Conta nao existe", "categoria": "Token", "emissor": "rC",
         "moeda_hex": "CCC", "erro_leitura": "actNotFound"},
        {"nome": "Medido", "categoria": "Token", "emissor": "rD", "moeda_hex": "DDD",
         "leitura_ok": True, "erro_leitura": None, "tx_janela": 12},
    ]
    pendentes = chaves_nao_medidas(pagina)
    checa("recusa do no entra na fila do reparo", "rA:AAA" in pendentes)
    checa("falta de tempo tambem - so adiou", "rB:BBB" in pendentes)
    checa("conta inexistente nao: remedir daria o mesmo erro", "rC:CCC" not in pendentes)
    checa("quem foi medido nao e remedido a toa", "rD:DDD" not in pendentes)

    catalogo = [
        {"nome": "Recusado", "categoria": "Token", "emissor": "rA", "moeda_hex": "AAA",
         "holders": 200},
        {"nome": "Sem tempo", "categoria": "Token", "emissor": "rB", "moeda_hex": "BBB",
         "holders": 150},
        {"nome": "Terceiro", "categoria": "Token", "emissor": "rZ", "moeda_hex": "ZZZ",
         "holders": 900},
    ]
    real_descobrir = coletor.descobrir_tokens
    coletor.descobrir_tokens = lambda limite, offset=0: catalogo if offset == 0 else []
    alvos = alvos_nao_medidos(pagina)
    coletor.descobrir_tokens = real_descobrir
    checa("mede so os pendentes, nao o catalogo inteiro",
          sorted(a["nome"] for a in alvos) == ["Recusado", "Sem tempo"])
    checa("com os numeros de hoje, nao os guardados",
          all(a.get("holders") for a in alvos))
    checa("pagina inteira medida nao gera corrida nenhuma",
          alvos_nao_medidos([pagina[3]]) == [])

    print()
    if FALHAS:
        print(f"{len(FALHAS)} falha(s):", ", ".join(FALHAS))
        raise SystemExit(1)
    print("A fronteira entre nao-medido e calado esta de pe.")


if __name__ == "__main__":
    main()
