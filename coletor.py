#!/usr/bin/env python3
"""
Coletor de sinais de vida de projetos da XRPL.

Descobre tokens pelo XRPL Meta, mede atividade real na rede via JSON-RPC de um
no publico, checa se o site do projeto ainda responde, e classifica cada projeto
em: ativo, morrendo, parado, morto ou indeterminado.

Guarda um snapshot por execucao em historico/, o que permite medir tendencia
(variacao de holders) a partir da segunda semana.

Uso:
    python coletor.py                  # coleta padrao (40 tokens + projetos sem token)
    python coletor.py --limite 100     # mais tokens
    python coletor.py --no-rede        # so recalcula a classificacao do dados.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

# --------------------------------------------------------------------------
# Configuracao
# --------------------------------------------------------------------------

# XRPL Meta: catalogo de tokens da rede, gratuito e sem chave.
XRPLMETA = "https://s1.xrplmeta.org"

# No publico com historico completo. Alternativas: https://s1.ripple.com:51234
# (historico curto) ou o seu proprio Clio quando o volume justificar.
RPC = "https://xrplcluster.com"

# A XRPL conta o tempo em segundos desde 2000-01-01, nao desde 1970.
# Errar isso desloca todas as datas em 30 anos - e o bug classico de quem
# comeca a ler a rede.
RIPPLE_EPOCH = 946684800

TIMEOUT = 25
PAUSA_ENTRE_CHAMADAS = 0.35  # no publico e gentileza, nao direito adquirido

AGENTE = "xrpl-vivo/1.0 (+coletor de sinais de atividade)"

# Projetos sem token proprio (carteiras, exploradores, ferramentas). Para esses
# nao existe sinal on-chain de token: medimos o site e, quando houver, o
# repositorio. Preencha com os projetos que voce quer acompanhar.
PROJETOS_SEM_TOKEN = [
    {"nome": "Bithomp", "site": "https://bithomp.com", "categoria": "Explorador"},
    {"nome": "XRPSCAN", "site": "https://xrpscan.com", "categoria": "Explorador"},
    {"nome": "Xaman", "site": "https://xaman.app", "categoria": "Carteira"},
    {"nome": "GemWallet", "site": "https://gemwallet.app", "categoria": "Carteira"},
    {"nome": "XRP Toolkit", "site": "https://www.xrptoolkit.com", "categoria": "Ferramenta"},
    {"nome": "xrp.cafe", "site": "https://xrp.cafe", "categoria": "NFT"},
    {"nome": "OnTheDex", "site": "https://onthedex.live", "categoria": "Dados"},
    {"nome": "XRPL Meta", "site": "https://xrplmeta.org", "categoria": "Dados"},
]


# --------------------------------------------------------------------------
# Utilidades de rede
# --------------------------------------------------------------------------


def _get_json(url: str) -> Any:
    """GET com retentativa. O XRPL Meta pendura a conexao de vez em quando
    (medido: ~1 em 3 chamadas). Sem retentativa a coleta diaria as vezes sai
    sem token nenhum e ninguem percebe."""
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if tentativa == 2:
                raise
            print(f"    . {url} falhou ({e}); tentando de novo", file=sys.stderr)
            time.sleep(2.0 * (tentativa + 1))


def _rpc(metodo: str, params: dict) -> dict:
    """Chamada JSON-RPC ao no da XRPL. Devolve result ou {} em caso de erro."""
    corpo = json.dumps({"method": metodo, "params": [params]}).encode("utf-8")
    req = urllib.request.Request(
        RPC,
        data=corpo,
        headers={"Content-Type": "application/json", "User-Agent": AGENTE},
    )
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                resposta = json.loads(r.read().decode("utf-8"))
            return resposta.get("result", {}) or {}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if tentativa == 2:
                print(f"    ! rpc {metodo} falhou: {e}", file=sys.stderr)
                return {}
            time.sleep(1.5 * (tentativa + 1))
    return {}


def site_responde(url: str) -> bool | None:
    """True se o site responde, False se nao, None se nem deu para tentar."""
    if not url:
        return None
    if not url.startswith("http"):
        url = "https://" + url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": AGENTE}, method="GET")
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status < 400
    except urllib.error.HTTPError as e:
        # 403 e 429 sao bloqueio de bot, nao site morto.
        return e.code in (401, 403, 429)
    except Exception:
        return False


# --------------------------------------------------------------------------
# Sinais on-chain
# --------------------------------------------------------------------------


def _data_da_transacao(t: dict) -> int | None:
    """
    Extrai o timestamp unix de um item de account_tx.

    Trata os dois formatos: a API v1 devolve {"tx": {...,"date": N}} e a v2
    devolve {"tx_json": {...}, "close_time_iso": "..."}. Um coletor que so
    entende um dos dois quebra silenciosamente quando o no e atualizado.
    """
    tx = t.get("tx") or t.get("tx_json") or {}
    if isinstance(tx.get("date"), int):
        return tx["date"] + RIPPLE_EPOCH
    iso = t.get("close_time_iso") or tx.get("close_time_iso")
    if iso:
        try:
            return int(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def atividade_da_conta(endereco: str, dias: int = 30) -> dict:
    """
    Mede a atividade da conta: quando foi a ultima transacao e quantas
    aconteceram na janela. Pagina para tras e para assim que passa do corte,
    em vez de tentar adivinhar um ledger_index inicial.
    """
    corte = int(time.time()) - dias * 86400
    ultima: int | None = None
    total = 0
    marker = None
    paginas = 0

    while paginas < 12:  # teto de seguranca: 12 x 200 = 2400 transacoes
        params = {
            "account": endereco,
            "ledger_index_min": -1,
            "ledger_index_max": -1,
            "limit": 200,
            "forward": False,
        }
        if marker:
            params["marker"] = marker

        res = _rpc("account_tx", params)
        txs = res.get("transactions") or []
        if not txs and paginas == 0:
            return {"ultima_atividade": None, "tx_janela": 0, "erro": res.get("error")}

        for t in txs:
            quando = _data_da_transacao(t)
            if quando is None:
                continue
            if ultima is None:
                ultima = quando
            if quando >= corte:
                total += 1
            else:
                return {"ultima_atividade": ultima, "tx_janela": total, "erro": None}

        marker = res.get("marker")
        paginas += 1
        if not marker:
            break
        time.sleep(PAUSA_ENTRE_CHAMADAS)

    return {"ultima_atividade": ultima, "tx_janela": total, "erro": None, "truncado": True}


# Endereco "buraco negro" canonico da XRPL: chave publica de valor zero, sem
# chave privada correspondente. Regular key apontada para ca = ninguem assina.
BURACO_NEGRO = "rrrrrrrrrrrrrrrrrrrrBZbvji"


def conta_esta_blackholed(endereco: str) -> bool:
    """
    Emissor 'blackholed' (ninguem consegue mais assinar pela conta) e boa
    pratica de seguranca, nao abandono. Contar isso como morte e o erro que
    faria a pagina inteira perder credibilidade no primeiro dia.

    Mestra desabilitada NAO basta: e so metade do teste. O emissor do RLUSD tem
    a mestra desabilitada e transaciona todo dia, porque a Ripple assina por
    signer list de 26 chaves. Blackhole de verdade exige que nao sobre nenhum
    caminho de assinatura: mestra desabilitada, regular key ausente ou no
    buraco negro, e nenhuma signer list.
    """
    res = _rpc(
        "account_info",
        {"account": endereco, "ledger_index": "validated", "signer_lists": True},
    )
    dados = res.get("account_data") or {}
    flags = dados.get("Flags", 0)
    LSF_DISABLE_MASTER = 0x00100000
    if not flags & LSF_DISABLE_MASTER:
        return False

    chave = dados.get("RegularKey")
    if chave and chave != BURACO_NEGRO:
        return False

    # A signer list vem em account_data.signer_lists ou na raiz do result,
    # conforme a versao da API do no.
    listas = dados.get("signer_lists") or res.get("signer_lists") or []
    for lista in listas:
        if lista.get("SignerEntries"):
            return False

    return True


# --------------------------------------------------------------------------
# Descoberta de tokens
# --------------------------------------------------------------------------


def _cava(d: dict, *caminhos, padrao=None):
    """Le d['a']['b'] sem explodir quando o esquema muda."""
    for caminho in caminhos:
        atual: Any = d
        ok = True
        for parte in caminho.split("."):
            if isinstance(atual, dict) and parte in atual:
                atual = atual[parte]
            else:
                ok = False
                break
        if ok and atual not in (None, ""):
            return atual
    return padrao


def _num(v, padrao=0):
    """XRPL Meta devolve parte das metricas como string ("447", "4983.50").
    Converte para numero; sem isso a comparacao com os limiares explode."""
    if v in (None, ""):
        return padrao
    try:
        f = float(v)
    except (TypeError, ValueError):
        return padrao
    return int(f) if f.is_integer() else f


def nome_da_moeda(codigo: str | None) -> str:
    """Codigo de moeda de 40 hex vira o texto que ele representa.

    A XRPL guarda moedas de mais de tres letras como 20 bytes em hexadecimal:
    "5852576562000..." e "XRWeb". Mostrar o hex cru na pagina e como listar um
    projeto pelo numero de serie - ninguem reconhece, e parece erro.
    Codigos que nao sao texto (tokens de pool, por exemplo, que comecam com
    0x03) ficam como estao, abreviados.
    """
    if not codigo:
        return ""
    if len(codigo) != 40:
        return codigo  # ja e um codigo de 3 letras
    try:
        cru = bytes.fromhex(codigo)
    except ValueError:
        return codigo
    if cru[:1] == b"\x03":  # token de liquidez, nao tem nome legivel
        return codigo[:8] + "..."
    texto = cru.rstrip(b"\x00").decode("ascii", errors="ignore").strip()
    return texto if texto.isprintable() and texto else codigo[:8] + "..."


def normalizar_nomes(projetos: list[dict]) -> None:
    """Conserta nome/moeda em hexadecimal de coletas antigas, no lugar."""
    for p in projetos:
        hexa = p.get("moeda_hex") or p.get("moeda")
        if hexa and len(str(hexa)) == 40:
            p["moeda_hex"] = hexa
            p["moeda"] = nome_da_moeda(hexa)
        nome = str(p.get("nome") or "")
        if len(nome) == 40:
            p["nome"] = nome_da_moeda(nome)


def descobrir_tokens(limite: int) -> list[dict]:
    url = f"{XRPLMETA}/tokens?limit={limite}&sort_by=holders"
    try:
        bruto = _get_json(url)
    except Exception as e:
        print(f"! nao consegui falar com o XRPL Meta: {e}", file=sys.stderr)
        return []

    tokens = bruto.get("tokens", bruto if isinstance(bruto, list) else [])
    saida = []
    for t in tokens:
        emissor = _cava(t, "issuer")
        if not emissor:
            continue
        saida.append(
            {
                "nome": _cava(t, "meta.token.name", "meta.issuer.name", padrao=None)
                or nome_da_moeda(_cava(t, "currency"))
                or "(sem nome)",
                "categoria": "Token",
                "emissor": emissor,
                "moeda": nome_da_moeda(_cava(t, "currency")),
                "moeda_hex": _cava(t, "currency"),
                "site": _cava(t, "meta.issuer.domain", "meta.token.domain", padrao=""),
                "holders": _num(_cava(t, "metrics.holders")),
                "trustlines": _num(_cava(t, "metrics.trustlines")),
                "volume_24h": _num(_cava(t, "metrics.volume_24h")),
                "trocas_24h": _num(_cava(t, "metrics.exchanges_24h", "metrics.exchanges24h")),
            }
        )
    return saida


# --------------------------------------------------------------------------
# Classificacao
# --------------------------------------------------------------------------

# Os limiares estao aqui em cima de proposito: sao a opiniao editorial do
# projeto e vao ser questionados pela comunidade. Deixe-os faceis de discutir.
LIMIARES = {
    "dias_morto": 180,
    "dias_parado": 90,
    "dias_ativo": 7,
    "tx_ativo": 100,
    "tx_minimo": 10,
    "holders_minimo": 25,
}


def classificar(p: dict) -> tuple[str, str]:
    """Devolve (situacao, motivo). O motivo aparece na pagina: sem ele a
    classificacao vira acusacao sem prova."""
    dias = p.get("dias_sem_atividade")
    tx = p.get("tx_janela") or 0
    # Com o teto de paginacao a contagem e um piso: dizer "2400" seria mentira
    # pequena, e o motivo e a unica prova que a pagina oferece.
    tx_txt = f"{tx}+" if p.get("tx_truncado") else str(tx)
    holders = p.get("holders") or 0
    site = p.get("site_ok")
    blackholed = p.get("blackholed")

    if dias is None and p["categoria"] != "Token":
        if site is True:
            return "ativo", "Site no ar; projeto sem token para medir na rede."
        if site is False:
            return "morto", "Site fora do ar e sem atividade mensuravel na rede."
        return "indeterminado", "Nao foi possivel medir."

    if dias is None:
        return "indeterminado", "Conta do emissor nao respondeu."

    # Emissor blackholed e desenho intencional: a atividade acontece entre os
    # detentores, nao pela conta emissora. Julga-se pelo token, nao pela conta.
    if blackholed:
        if holders >= LIMIARES["holders_minimo"] and (p.get("trocas_24h") or 0) > 0:
            return "ativo", f"Emissor blackholed (boa pratica); {holders} detentores e negociacao nas ultimas 24h."
        if holders >= LIMIARES["holders_minimo"]:
            return "morrendo", f"Emissor blackholed; {holders} detentores, mas sem negociacao nas ultimas 24h."
        return "parado", f"Emissor blackholed e apenas {holders} detentores."

    if dias > LIMIARES["dias_morto"]:
        return "morto", f"Sem nenhuma transacao ha {dias} dias."

    if site is False and tx < LIMIARES["tx_minimo"]:
        return "morto", f"Site fora do ar e so {tx_txt} transacoes em 30 dias."

    if dias > LIMIARES["dias_parado"] or tx < LIMIARES["tx_minimo"]:
        return "parado", f"Ultima atividade ha {dias} dias; {tx_txt} transacoes em 30 dias."

    if tx < LIMIARES["tx_ativo"] or site is False:
        motivo = f"{tx_txt} transacoes em 30 dias"
        if site is False:
            motivo += "; site fora do ar"
        return "morrendo", motivo + "."

    if dias <= LIMIARES["dias_ativo"]:
        return "ativo", f"{tx_txt} transacoes em 30 dias; ultima " + ("hoje." if dias == 0 else f"ha {dias} dias.")

    return "morrendo", f"{tx_txt} transacoes em 30 dias, mas nada nos ultimos {dias} dias."


# --------------------------------------------------------------------------
# Historico e tendencia
# --------------------------------------------------------------------------


def salvar_snapshot(projetos: list[dict]) -> None:
    os.makedirs("historico", exist_ok=True)
    hoje = dt.date.today().isoformat()
    resumo = {
        p.get("emissor") or p["nome"]: {
            "holders": p.get("holders"),
            "tx_janela": p.get("tx_janela"),
            "tx_truncado": p.get("tx_truncado"),
        }
        for p in projetos
    }
    with open(f"historico/{hoje}.json", "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=1)


def aplicar_tendencia(projetos: list[dict]) -> None:
    """Compara com o snapshot mais antigo disponivel dentro de ~35 dias."""
    if not os.path.isdir("historico"):
        return
    arquivos = sorted(os.listdir("historico"))
    if len(arquivos) < 2:
        return

    limite = dt.date.today() - dt.timedelta(days=35)
    antigo = None
    for nome in arquivos:
        try:
            data = dt.date.fromisoformat(nome.removesuffix(".json"))
        except ValueError:
            continue
        if data >= limite:
            with open(f"historico/{nome}", encoding="utf-8") as f:
                antigo = json.load(f)
            break
    if not antigo:
        return

    for p in projetos:
        chave = p.get("emissor") or p["nome"]
        antes = (antigo.get(chave) or {}).get("holders")
        agora = p.get("holders")
        if isinstance(antes, int) and isinstance(agora, int) and antes > 0:
            p["variacao_holders"] = round((agora - antes) / antes * 100, 1)


# --------------------------------------------------------------------------
# Orquestracao
# --------------------------------------------------------------------------


def coletar(limite: int) -> list[dict]:
    projetos = descobrir_tokens(limite)
    projetos += [dict(p) for p in PROJETOS_SEM_TOKEN]
    agora = int(time.time())

    for i, p in enumerate(projetos, 1):
        print(f"[{i}/{len(projetos)}] {p['nome']}")

        if p.get("emissor"):
            p["blackholed"] = conta_esta_blackholed(p["emissor"])
            time.sleep(PAUSA_ENTRE_CHAMADAS)
            sinais = atividade_da_conta(p["emissor"])
            p["tx_janela"] = sinais["tx_janela"]
            p["tx_truncado"] = bool(sinais.get("truncado"))
            ultima = sinais["ultima_atividade"]
            p["ultima_atividade"] = ultima
            # max(0,...): a coleta demora minutos e "agora" foi lido no inicio;
            # uma transacao recem-confirmada dava "ha -1 dias" na pagina.
            p["dias_sem_atividade"] = max(0, (agora - ultima) // 86400) if ultima else None
            time.sleep(PAUSA_ENTRE_CHAMADAS)
        else:
            p.setdefault("dias_sem_atividade", None)

        p["site_ok"] = site_responde(p.get("site", ""))

    aplicar_tendencia(projetos)

    for p in projetos:
        situacao, motivo = classificar(p)
        p["situacao"] = situacao
        p["motivo"] = motivo

    return projetos


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=40, help="quantos tokens buscar")
    ap.add_argument("--no-rede", action="store_true", help="so reclassifica o dados.json existente")
    args = ap.parse_args()

    if args.no_rede:
        with open("dados.json", encoding="utf-8") as f:
            projetos = json.load(f)["projetos"]
        normalizar_nomes(projetos)
        for p in projetos:
            p["situacao"], p["motivo"] = classificar(p)
    else:
        projetos = coletar(args.limite)
        # Sem tokens a pagina inteira perde o sentido. Melhor abortar e manter
        # o dados.json anterior do que publicar em silencio uma lista vazia.
        if args.limite > 0 and not any(p.get("categoria") == "Token" for p in projetos):
            print(
                "! nenhum token veio do XRPL Meta - dados.json NAO foi alterado.",
                file=sys.stderr,
            )
            sys.exit(1)
        salvar_snapshot(projetos)

    ordem = {"ativo": 0, "morrendo": 1, "parado": 2, "morto": 3, "indeterminado": 4}
    projetos.sort(key=lambda p: (ordem.get(p["situacao"], 9), -(p.get("holders") or 0)))

    saida = {
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "limiares": LIMIARES,
        "total": len(projetos),
        "contagem": {
            s: sum(1 for p in projetos if p["situacao"] == s) for s in ordem
        },
        "projetos": projetos,
    }

    with open("dados.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=1)

    print("\nResumo:", saida["contagem"])
    print("dados.json escrito.")


if __name__ == "__main__":
    main()
