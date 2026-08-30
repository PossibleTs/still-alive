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
import http.client
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


# Tudo que uma leitura de rede pode jogar. IncompleteRead entrou na lista
# depois de derrubar uma coleta de duas horas no token 190 de 308: o no
# publico fechou a conexao no meio da resposta, e HTTPException nao e
# URLError - passava direto pelo except e matava o processo inteiro.
FALHAS_DE_REDE = (
    urllib.error.URLError,
    http.client.HTTPException,
    TimeoutError,
    ConnectionError,
    json.JSONDecodeError,
    OSError,
)


def _get_json(url: str, tentativas: int = 3) -> Any:
    """
    GET com retentativa e espera crescente.

    O XRPL Meta pendura a conexao com frequencia, e em rajadas: medido em
    30/08/2026, cinco chamadas seguidas deram timeout de 45s e a sexta
    respondeu em 6s - sem relacao com o tamanho do pedido. Tres tentativas
    nao cobrem uma rajada dessas; a coleta diaria abortava por causa disso.
    """
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    espera = 2.0
    for tentativa in range(tentativas):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except FALHAS_DE_REDE as e:
            if tentativa == tentativas - 1:
                raise
            print(
                f"    . {url} falhou ({e}); tentativa {tentativa + 2} de {tentativas} "
                f"em {espera:.0f}s",
                file=sys.stderr,
            )
            time.sleep(espera)
            espera = min(espera * 2, 30.0)


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
        except FALHAS_DE_REDE as e:
            if tentativa == 2:
                print(f"    ! rpc {metodo} falhou: {e}", file=sys.stderr)
                return {}
            time.sleep(1.5 * (tentativa + 1))
    return {}


# Hospedeiros que servem SO o xrp-ledger.toml. Quem registra token pela
# FirstLedger ganha um subdominio desses como "dominio" no XRPL Meta - e um
# endereco de metadado, nao o site do projeto. Bater na raiz da 404 sempre, e
# dizer "site fora do ar" seria acusar de morto quem nunca teve site ali.
HOSPEDEIROS_DE_METADADO = (".toml.firstledger.net",)


def site_responde(url: str) -> bool | None:
    """
    True se o site responde, False se esta fora do ar, None se nao da para
    afirmar nada.

    A diferenca entre False e None e o produto inteiro: False vira "site fora
    do ar" na pagina, e isso e uma acusacao. Dominio que nao resolve e prova.
    Erro 5xx e o servidor deles tropecando agora - pode ser transitorio, e uma
    amostra so nao basta para dizer que o projeto abandonou o site.
    """
    if not url:
        return None
    if not url.startswith("http"):
        url = "https://" + url

    hospedeiro = url.split("://", 1)[1].split("/", 1)[0].lower()
    if hospedeiro.endswith(HOSPEDEIROS_DE_METADADO):
        return None  # nao e site do projeto, e o TOML hospedado por terceiro

    req = urllib.request.Request(url, headers={"User-Agent": AGENTE}, method="GET")
    for tentativa in range(2):
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                return r.status < 400
        except urllib.error.HTTPError as e:
            # 401/403/429 sao bloqueio de bot: o site esta la, so nao quer robo.
            if e.code in (401, 403, 429):
                return True
            # 5xx e erro do servidor deles, nao ausencia de site.
            if e.code >= 500:
                return None
            return False
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Nome que nao resolve e dominio que acabou: isso e prova de morte.
            motivo = str(getattr(e, "reason", e))
            if "not known" in motivo or "Name or service" in motivo:
                return False
            if tentativa == 0:
                time.sleep(1.5)
                continue
            return False
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
    Mede a atividade da conta em DUAS medidas, que sao coisas diferentes:

      tx_janela / ultima_atividade  - tudo que tocou a conta na janela.
      tx_emissor / ultima_do_emissor - so o que a propria conta ASSINOU.

    A distincao e o coracao da medicao. O account_tx devolve toda transacao que
    afeta a conta, e a maioria e de estranho: gente abrindo trustline, bot
    mandando poeira, oferta batendo no livro. Um emissor abandonado ha meses
    parece movimentado por causa disso - foi o que escondeu os mortos na
    primeira coleta de 300. Quem assinou responde "a equipe ainda esta ai?";
    o total responde "o token ainda circula?". Sao perguntas distintas e a
    pagina precisa das duas para nao chamar de vivo quem so tem visita.

    Pagina para tras e para assim que passa do corte, em vez de tentar
    adivinhar um ledger_index inicial.
    """
    corte = int(time.time()) - dias * 86400
    ultima: int | None = None
    ultima_emissor: int | None = None
    total = 0
    total_emissor = 0
    marker = None
    paginas = 0
    truncado = False

    def _saida(erro=None) -> dict:
        return {
            "ultima_atividade": ultima,
            "ultima_do_emissor": ultima_emissor,
            "tx_janela": total,
            "tx_emissor": total_emissor,
            "truncado": truncado,
            "erro": erro,
        }

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
            return _saida(erro=res.get("error"))

        for t in txs:
            quando = _data_da_transacao(t)
            if quando is None:
                continue
            tx = t.get("tx_json") or t.get("tx") or {}
            foi_o_emissor = tx.get("Account") == endereco

            if ultima is None:
                ultima = quando
            if foi_o_emissor and ultima_emissor is None:
                ultima_emissor = quando

            if quando >= corte:
                total += 1
                if foi_o_emissor:
                    total_emissor += 1
            else:
                # Passou do corte: a janela acabou. Mas seguimos so ate achar a
                # ultima assinatura do emissor, que pode ser bem mais antiga -
                # sem ela nao da para dizer "a equipe sumiu ha N dias".
                if ultima_emissor is not None:
                    return _saida()
                break
        else:
            marker = res.get("marker")
            paginas += 1
            if not marker:
                break
            time.sleep(PAUSA_ENTRE_CHAMADAS)
            continue

        # Saiu do laco pelo break: janela encerrada, ainda procurando o emissor.
        marker = res.get("marker")
        paginas += 1
        if not marker:
            break
        time.sleep(PAUSA_ENTRE_CHAMADAS)

    truncado = paginas >= 12
    return _saida()


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
        # Esta chamada e a unica insubstituivel: sem ela nao ha coleta.
        # Vale insistir mais do que nas outras.
        bruto = _get_json(url, tentativas=6)
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
                # padrao=None de proposito: campo AUSENTE nao e o mesmo que
                # zero. Se o XRPL Meta mudar o esquema ou responder pela
                # metade, zero viraria "sem negociacao nas ultimas 24h" - a
                # pagina acusaria de moribundo o catalogo inteiro por causa de
                # um defeito nosso.
                "holders": _num(_cava(t, "metrics.holders"), padrao=None),
                "trustlines": _num(_cava(t, "metrics.trustlines"), padrao=None),
                "volume_24h": _num(_cava(t, "metrics.volume_24h"), padrao=None),
                "trocas_24h": _num(
                    _cava(t, "metrics.exchanges_24h", "metrics.exchanges24h"),
                    padrao=None,
                ),
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
    # None = nao sabemos; 0 = sabemos que nao houve. So o segundo acusa.
    trocas = p.get("trocas_24h")
    sem_negociacao = trocas == 0
    negociou = isinstance(trocas, (int, float)) and trocas > 0
    # Com o teto de paginacao a contagem e um piso: dizer "2400" seria mentira
    # pequena, e o motivo e a unica prova que a pagina oferece.
    tx_txt = f"{tx}+" if p.get("tx_truncado") else str(tx)

    # Quase toda transacao que aparece no account_tx e de terceiro abrindo
    # trustline ou mandando poeira. So podemos afirmar que a equipe sumiu
    # quando a leitura NAO foi truncada - com teto de paginacao, nao ter visto
    # o emissor assinar nao prova que ele nao assinou.
    tx_emissor = p.get("tx_emissor")
    leitura_completa = not p.get("tx_truncado")
    emissor_calado = (
        leitura_completa and tx_emissor == 0 and p["categoria"] == "Token"
    )
    dias_calado = p.get("dias_sem_emissor")
    holders = p.get("holders") or 0  # None vira 0 so para comparar, nao para acusar
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
        if holders >= LIMIARES["holders_minimo"] and negociou:
            return "ativo", f"Emissor blackholed (boa pratica); {holders} detentores e negociacao nas ultimas 24h."
        if holders >= LIMIARES["holders_minimo"]:
            if not sem_negociacao:  # nao sabemos se negociou
                return "indeterminado", (
                    f"Emissor blackholed com {holders} detentores, mas o catalogo "
                    "nao informou negociacao - sem dado para julgar."
                )
            return "morrendo", f"Emissor blackholed; {holders} detentores, mas sem negociacao nas ultimas 24h."
        return "parado", f"Emissor blackholed e apenas {holders} detentores."

    if dias > LIMIARES["dias_morto"]:
        return "morto", f"Sem nenhuma transacao ha {dias} dias."

    # Conta movimentada por estranhos, emissor calado. Nao e morte - o token
    # circula -, mas dizer "ativo" aqui seria creditar ao projeto o movimento
    # que os outros fazem.
    if emissor_calado:
        desde = f"ha {dias_calado} dias" if dias_calado else "na janela medida"
        if negociou:
            return "ativo", (
                f"Token negociado nas ultimas 24h e {tx_txt} transacoes na conta, "
                f"mas nenhuma assinada pelo emissor {desde}."
            )
        if not sem_negociacao:
            return "indeterminado", (
                f"As {tx_txt} transacoes da conta sao todas de terceiros e o "
                f"emissor nao assina nada {desde}; sem dado de negociacao para "
                "concluir."
            )
        return "morrendo", (
            f"As {tx_txt} transacoes da conta sao todas de terceiros; o emissor "
            f"nao assina nada {desde}, e nao houve negociacao nas ultimas 24h."
        )

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
            "tx_emissor": p.get("tx_emissor"),
            "dias_sem_emissor": p.get("dias_sem_emissor"),
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
        try:
            _medir(p, agora)
        except Exception as e:
            # Uma coleta de 300 leva horas. Deixar um projeto estranho derrubar
            # o lote inteiro ja custou duas horas uma vez; melhor marcar este
            # como nao medido e seguir.
            print(f"    ! {p['nome']}: {type(e).__name__}: {e}", file=sys.stderr)
            p["erro_medicao"] = f"{type(e).__name__}: {e}"
            p.setdefault("dias_sem_atividade", None)

    aplicar_tendencia(projetos)

    for p in projetos:
        situacao, motivo = classificar(p)
        p["situacao"] = situacao
        p["motivo"] = motivo

    return projetos


def _medir(p: dict, agora: int) -> None:
    """Mede um projeto. Separado para o laco poder seguir se este falhar."""
    if p.get("emissor"):
        p["blackholed"] = conta_esta_blackholed(p["emissor"])
        time.sleep(PAUSA_ENTRE_CHAMADAS)
        sinais = atividade_da_conta(p["emissor"])
        p["tx_janela"] = sinais["tx_janela"]
        p["tx_emissor"] = sinais.get("tx_emissor")
        p["tx_truncado"] = bool(sinais.get("truncado"))
        ue = sinais.get("ultima_do_emissor")
        p["ultima_do_emissor"] = ue
        p["dias_sem_emissor"] = max(0, (agora - ue) // 86400) if ue else None
        ultima = sinais["ultima_atividade"]
        p["ultima_atividade"] = ultima
        # max(0,...): a coleta demora minutos e "agora" foi lido no inicio;
        # uma transacao recem-confirmada dava "ha -1 dias" na pagina.
        p["dias_sem_atividade"] = max(0, (agora - ultima) // 86400) if ultima else None
        time.sleep(PAUSA_ENTRE_CHAMADAS)
    else:
        p.setdefault("dias_sem_atividade", None)

    p["site_ok"] = site_responde(p.get("site", ""))


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
