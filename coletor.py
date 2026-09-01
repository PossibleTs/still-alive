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

AGENTE = "still-alive/1.0 (+coletor de sinais de atividade)"

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
                # Marcado, e nao {} vazio: "a rede falhou" e "a conta nao tem
                # nada" davam o mesmo resultado, e dez projetos de 208 foram
                # dados como nao medidos quando o problema era nosso.
                return {"erro_rede": str(e)}
            time.sleep(1.5 * (tentativa + 1))
    return {"erro_rede": "tentativas esgotadas"}


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

      tx_janela / ultima_atividade   - tudo que tocou a conta na janela.
      tx_emissor / ultima_do_emissor - so o que a propria conta ASSINOU.

    A distincao e o coracao da medicao. O account_tx devolve toda transacao que
    afeta a conta, e a maioria e de estranho: gente abrindo trustline, bot
    mandando poeira, oferta batendo no livro. Um emissor abandonado ha meses
    parece movimentado por causa disso. Quem assinou responde "a equipe ainda
    esta ai?"; o total responde "o token ainda circula?".

    Le para tras ate CRUZAR o corte da janela, e para ali. Cruzar o corte e o
    que torna as contagens exatas; se paramos antes, por bater no teto de
    paginas, elas viram piso e `truncado` diz isso. Nao vale a pena seguir
    lendo historico antigo so para achar a ultima assinatura do emissor: sao
    doze chamadas por conta e a resposta que importa - "assinou algo no mes?" -
    ja esta dada.
    """
    corte = int(time.time()) - dias * 86400
    ultima: int | None = None
    ultima_emissor: int | None = None
    total = 0
    total_emissor = 0
    marker = None
    paginas = 0
    janela_completa = False

    def _saida(erro=None) -> dict:
        return {
            "ultima_atividade": ultima,
            "ultima_do_emissor": ultima_emissor,
            "tx_janela": total,
            "tx_emissor": total_emissor,
            "truncado": not janela_completa,
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
            return _saida(erro=res.get("error") or res.get("erro_rede"))

        for t in txs:
            quando = _data_da_transacao(t)
            if quando is None:
                continue
            if quando < corte:
                janela_completa = True
                break

            tx = t.get("tx_json") or t.get("tx") or {}
            if ultima is None:
                ultima = quando
            total += 1
            if tx.get("Account") == endereco:
                total_emissor += 1
                if ultima_emissor is None:
                    ultima_emissor = quando

        if janela_completa:
            break

        marker = res.get("marker")
        paginas += 1
        if not marker:
            # Acabou o historico da conta: a janela esta coberta por inteiro.
            janela_completa = True
            break
        time.sleep(PAUSA_ENTRE_CHAMADAS)

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


def dominio_valido(texto: str | None) -> str:
    """
    Filtra o que o catalogo chama de "domain" antes de virar link publico.

    O campo e preenchido por quem cadastra o token, sem validacao nenhuma do
    lado deles - achamos um projeto (XRG) que pos o proprio e-mail pessoal
    ali. Sem este filtro, coletor.py publicava "" como site
    e ainda o transformava em link (https://): expunha o
    endereco de alguem E gerava link quebrado, dois problemas de um so.

    Nao tenta validar DNS nem alcancar a rede - so recusa o que claramente
    nao e um dominio (tem @, tem espaco, ou nao tem ponto nenhum).
    """
    texto = (texto or "").strip()
    if not texto or "@" in texto or " " in texto or "." not in texto:
        return ""
    return texto


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


def _perfil_no_x(t: dict) -> str:
    """Link do projeto no X, quando ele mesmo publicou.

    O XRPL Meta guarda as urls declaradas com um tipo ("website", "social").
    Cerca de um em cada cinco tokens publica o X ali. Nao ha adivinhacao aqui:
    perfil errado ao lado de um projeto acusado de morto e pior que perfil
    nenhum.
    """
    for onde in ("token", "issuer"):
        for u in (_cava(t, f"meta.{onde}.urls") or []):
            url = str(u.get("url") or "")
            if "x.com/" in url or "twitter.com/" in url:
                return url
    return ""


def moeda_canonica(codigo: str | None) -> str:
    """
    Normaliza um codigo de moeda para a forma que identifica o valor
    on-ledger, nao a forma que uma API decidiu devolver hoje.

    A raiz do problema: um codigo padrao de 3 letras (USD, EUR...) tem DUAS
    serializacoes validas para o MESMO valor de 160 bits - "USD" curto, ou o
    hex de 40 caracteres com 12 bytes zero, o codigo nos bytes 12-14, e mais 5
    bytes zero. O proprio rippled e deterministico e sempre devolve a forma
    curta (confirmado batendo book_offers direto no no publico); o risco e
    XRPL Meta nao aplicar a mesma regra em toda chamada, ou trocar de forma
    entre a versao do endpoint hoje ativa e a v2 para a qual vao migrar.

    Sem isto, chave_do_projeto() muda de baixo do projeto se isso acontecer, e
    a mesclagem trata o mesmo token como um projeto novo - perde historico e
    ele reaparece como "medido pela primeira vez".

    Codigo de mais de 3 letras (SOLO, RLUSD, X) nao tem essa ambiguidade: so
    existe a forma de 40 caracteres, e ela e devolvida como esta.
    """
    if not codigo:
        return ""
    codigo = str(codigo)
    if len(codigo) != 40:
        return codigo.upper()
    try:
        cru = bytes.fromhex(codigo)
    except ValueError:
        return codigo
    if (
        cru[:12] == b"\x00" * 12
        and cru[15:20] == b"\x00" * 5
        and all(32 <= b < 127 for b in cru[12:15])
    ):
        return cru[12:15].decode("ascii").upper()
    return codigo


def descobrir_tokens(limite: int, offset: int = 0) -> list[dict]:
    url = f"{XRPLMETA}/tokens?limit={limite}&sort_by=holders"
    if offset:
        # Os 300 primeiros por detentores sao os sobreviventes. O cemiterio
        # que a pagina promete datar comeca bem depois - em offset=1000 o
        # topo ja tem 544 detentores.
        url += f"&offset={offset}"
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
        # Token de pool de AMM (codigo comecando em 0x03) nao e projeto de
        # ninguem: e um recibo de liquidez. Listar isso como projeto - e pior,
        # acusar de moribundo - so mostra que o robo nao sabe o que esta lendo.
        moeda_hex = str(_cava(t, "currency") or "")
        if moeda_hex.startswith("03") and len(moeda_hex) == 40:
            continue
        saida.append(
            {
                "nome": _cava(t, "meta.token.name", "meta.issuer.name", padrao=None)
                or nome_da_moeda(_cava(t, "currency"))
                or "(sem nome)",
                "categoria": "Token",
                "emissor": emissor,
                "x": _perfil_no_x(t),
                "moeda": nome_da_moeda(_cava(t, "currency")),
                "moeda_hex": _cava(t, "currency"),
                "site": dominio_valido(_cava(t, "meta.issuer.domain", "meta.token.domain")),
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
                # 7 dias e a janela que sustenta acusacao. Um dia quieto e
                # rotina ate para token vivo de projeto pequeno; uma semana
                # inteira sem ninguem negociar ja diz alguma coisa.
                "trocas_7d": _num(_cava(t, "metrics.exchanges_7d"), padrao=None),
                "volume_7d": _num(_cava(t, "metrics.volume_7d"), padrao=None),
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


# Codigos de moeda fiduciaria e de metal. Um token desses nao e um projeto: e
# um IOU - a promessa de um gateway de resgatar valor de fora da rede.
MOEDAS_DE_RESGATE = {
    "USD", "EUR", "JPY", "CNY", "KRW", "GBP", "CAD", "AUD", "CHF", "BRL", "MXN",
    "SGD", "NZD", "HKD", "TRY", "RUB", "INR", "ILS", "SEK", "NOK", "DKK", "PLN",
    "ZAR", "VND", "THB", "IDR", "PHP", "MYR", "TWD", "AED", "SAR", "ARS", "CLP",
    "COP", "PEN", "XAU", "XAG", "XPT", "XPD",
}


def eh_iou_de_resgate(p: dict) -> bool:
    """Token de moeda fiduciaria ou metal, emitido por um gateway."""
    if p.get("categoria") != "Token":
        return False
    codigo = str(p.get("moeda") or p.get("moeda_hex") or "").upper()
    return codigo in MOEDAS_DE_RESGATE


def classificar(p: dict) -> tuple[str, str]:
    """
    Devolve (situacao, motivo). O motivo aparece na pagina: sem ele a
    classificacao vira acusacao sem prova.

    Um caso nao recebe veredito negativo: IOU de moeda fiduciaria ou metal.
    Chamar de "morta" uma memecoin quieta e uma observacao sobre a rede;
    dizer o mesmo de um `USD` ou `JPY` de gateway e uma afirmacao sobre uma
    PROMESSA DE RESGATE - que esta pagina nao tem como medir e nao se propoe a
    avaliar. A medicao continua na tela, com o mesmo numero e a mesma data; o
    que sai e a palavra que vira veredito. Se o gateway sumiu mesmo, a
    informacao util (silencio de N dias) continua ali, e quem tem o IOU na
    carteira decide o que ela significa.
    """
    situacao, motivo = _avaliar(p)
    if situacao in ("morto", "morrendo", "parado") and eh_iou_de_resgate(p):
        # O motivo original vai inteiro na frente: e a medicao que sustentaria
        # o veredito, e escondê-la para "proteger" o gateway seria trocar um
        # erro por outro. O que muda e so a palavra que julga.
        return "indeterminado", (
            f"{motivo} No call is made here: this is a fiat/metal IOU - a "
            "gateway's promise to redeem value off the ledger - and this page "
            "measures ledger activity, not promises. The measurement stands; "
            "the verdict does not."
        )
    return situacao, motivo


def _avaliar(p: dict) -> tuple[str, str]:
    """A classificacao propriamente dita. Ver classificar() para a excecao."""
    dias = p.get("dias_sem_atividade")
    tx = p.get("tx_janela") or 0
    # None = nao sabemos; 0 = sabemos que nao houve. So o segundo acusa.
    # A janela de 7 dias e a que vale: acusar um projeto por um unico dia
    # quieto e barulho, e a pagina paga o preco de cada acusacao errada.
    # O numero de 24h fica no dado bruto para quem quiser olhar.
    trocas = p.get("trocas_7d")
    if trocas is None:
        trocas = p.get("trocas_24h")
        janela_trocas = "in the last 24h"
    else:
        janela_trocas = "in the last 7 days"
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
            return "ativo", "Website up; no token to measure on-ledger."
        if site is False:
            return "morto", "Website down and no measurable on-ledger activity."
        return "indeterminado", "Could not measure."

    if dias is None:
        return "indeterminado", "The issuer account did not respond."

    # Emissor blackholed e desenho intencional: a atividade acontece entre os
    # detentores, nao pela conta emissora. Julga-se pelo token, nao pela conta.
    if blackholed:
        if holders >= LIMIARES["holders_minimo"] and negociou:
            return "ativo", f"Issuer blackholed (good practice); {holders} holders and trading {janela_trocas}."
        if holders >= LIMIARES["holders_minimo"]:
            if not sem_negociacao:  # nao sabemos se negociou
                return "indeterminado", (
                    f"Issuer blackholed with {holders} holders, but the catalogue "
                    "reported no trading data - nothing to judge on."
                )
            return "morrendo", f"Issuer blackholed; {holders} holders, but no trading {janela_trocas}."
        return "parado", f"Issuer blackholed and only {holders} holders."

    if dias > LIMIARES["dias_morto"]:
        return "morto", f"No transaction at all for {dias} days."

    if site is False and tx < LIMIARES["tx_minimo"]:
        return "morto", f"Website down and only {tx_txt} transactions in 30 days."

    # Conta movimentada por estranhos, emissor calado. Nao e morte - o token
    # circula -, mas dizer "ativo" aqui seria creditar ao projeto o movimento
    # que os outros fazem.
    if emissor_calado:
        desde = f"for {dias_calado} days" if dias_calado else "within the measured window"
        if negociou:
            return "ativo", (
                f"Token traded {janela_trocas} and {tx_txt} transactions on the "
                f"account, but none signed by the issuer {desde}."
            )
        if not sem_negociacao:
            return "indeterminado", (
                f"All {tx_txt} transactions on the account come from third "
                f"parties and the issuer has signed nothing {desde}; no trading "
                "data to conclude."
            )
        return "morrendo", (
            f"All {tx_txt} transactions on the account come from third parties; "
            f"the issuer has signed nothing {desde}, and there was no trading "
            f"{janela_trocas}."
        )


    if dias > LIMIARES["dias_parado"] or tx < LIMIARES["tx_minimo"]:
        return "parado", f"Last activity {dias} days ago; {tx_txt} transactions in 30 days."

    if tx < LIMIARES["tx_ativo"] or site is False:
        motivo = f"{tx_txt} transactions in 30 days"
        if site is False:
            motivo += "; website down"
        return "morrendo", motivo + "."

    if dias <= LIMIARES["dias_ativo"]:
        return "ativo", f"{tx_txt} transactions in 30 days; last one " + ("today." if dias == 0 else f"{dias} days ago.")

    return "morrendo", f"{tx_txt} transactions in 30 days, but nothing in the last {dias} days."


# --------------------------------------------------------------------------
# Historico e tendencia
# --------------------------------------------------------------------------


def salvar_snapshot(projetos: list[dict]) -> None:
    os.makedirs("historico", exist_ok=True)
    hoje = dt.date.today().isoformat()
    # nome e situacao entram aqui de proposito: sem eles o historico serve para
    # tendencia de detentores e para nada mais. Comparar dois snapshots e o que
    # permite dizer "3 projetos cruzaram para dormant nesta semana" - e essa
    # frase e o unico material recorrente que a pagina produz sozinha.
    resumo = {
        # chave_do_projeto, nao o emissor sozinho: 12 emissores nesta lista
        # emitem mais de uma moeda (a Bitstamp emite US Dollar E Euro), e a
        # chave curta fazia os dois colidirem - o ultimo escrito apagava o
        # outro, e a tendencia de detentores saia comparando token diferente.
        # Foi assim que apareceram quedas de -97% de um dia para o outro.
        chave_do_projeto(p): {
            "nome": p.get("nome"),
            "situacao": p.get("situacao"),
            "motivo": p.get("motivo"),
            "medido_em": p.get("medido_em"),
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
    """
    Calcula variacao_holders e dias_variacao a partir da PROPRIA medicao
    anterior de cada projeto (holders_anterior/medido_em_anterior, gravados
    por mesclar() na hora da remedicao) - nunca de um snapshot de calendario
    comum a todos.

    O motivo: o topo e medido todo dia e a cauda a cada 15. Comparar os dois
    contra a mesma data faz a cauda ficar "parada" por duas semanas e depois
    dar um salto que parece um movimento brusco, quando e so o acumulado de
    15 dias aparecendo de uma vez. dias_variacao vai junto do numero para a
    pagina nunca mostrar uma porcentagem sem dizer sobre que janela ela e.
    """
    for p in projetos:
        antes = p.get("holders_anterior")
        agora = p.get("holders")
        if not (isinstance(antes, int) and isinstance(agora, int) and antes > 0):
            continue
        p["variacao_holders"] = round((agora - antes) / antes * 100, 1)
        antes_em, agora_em = p.get("medido_em_anterior"), p.get("medido_em")
        if antes_em and agora_em:
            try:
                d1 = dt.datetime.fromisoformat(antes_em)
                d2 = dt.datetime.fromisoformat(agora_em)
                p["dias_variacao"] = max(1, round((d2 - d1).total_seconds() / 86400))
            except ValueError:
                pass


# --------------------------------------------------------------------------
# Orquestracao
# --------------------------------------------------------------------------


def chave_do_projeto(p: dict) -> str:
    """Identidade estavel de um projeto entre coletas."""
    if p.get("emissor"):
        return f"{p['emissor']}:{moeda_canonica(p.get('moeda_hex') or p.get('moeda'))}"
    return f"site:{p.get('site') or p.get('nome')}"


def mesclar(antigos: list[dict], novos: list[dict]) -> list[dict]:
    """
    Junta a medicao de hoje com o que ja se sabia.

    O ciclo mede uma fatia do catalogo por dia; sem mesclar, cada corrida
    apagaria os outros catorze quinze avos da pagina. Projeto nao medido hoje
    permanece com o que tinha, e o carimbo `medido_em` diz de quando e o dado.

    Ao SUBSTITUIR um projeto por uma medicao nova, guarda o holders/medido_em
    de antes em holders_anterior/medido_em_anterior. E o que permite calcular
    tendencia comparando cada projeto com a SUA PROPRIA medicao anterior, no
    intervalo real entre as duas - nao com um snapshot de calendario que serve
    o topo (medido todo dia) e a cauda (medida a cada 15 dias) igualmente mal.
    """
    por_chave = {chave_do_projeto(p): p for p in antigos}
    for novo in novos:
        chave = chave_do_projeto(novo)
        anterior = por_chave.get(chave)
        if anterior and isinstance(anterior.get("holders"), int) and anterior.get("medido_em"):
            novo["holders_anterior"] = anterior["holders"]
            novo["medido_em_anterior"] = anterior["medido_em"]
        por_chave[chave] = novo
    return list(por_chave.values())


def coletar(projetos: list[dict]) -> list[dict]:
    agora = int(time.time())
    carimbo = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

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

    # Segunda passada: quem nao respondeu por falha de rede merece outra
    # chance antes de virar "nao foi possivel medir" na pagina.
    repetir = [p for p in projetos if p.get("erro_leitura") or p.get("erro_medicao")]
    if repetir:
        print(f"\nsegunda passada em {len(repetir)} projetos que falharam")
        for i, p in enumerate(repetir, 1):
            print(f"[{i}/{len(repetir)}] {p['nome']}")
            p.pop("erro_medicao", None)
            try:
                _medir(p, agora)
            except Exception as e:
                print(f"    ! {p['nome']}: {type(e).__name__}: {e}", file=sys.stderr)
                p["erro_medicao"] = f"{type(e).__name__}: {e}"

    # aplicar_tendencia NAO entra aqui: ela le holders_anterior/medido_em_anterior,
    # e quem grava esses dois campos e mesclar() - que so roda depois, em main().
    # Chamar aqui rodava a tendencia ANTES de existir o que medir, e o campo
    # nunca aparecia na pagina, em silencio. E a mesma classe do bug de
    # 31/08 (chave que nao identificava o projeto): correcao presente no
    # codigo, sem efeito nenhum porque a ordem de chamada nao sustenta a
    # condicao que ela precisa.
    for p in projetos:
        p["medido_em"] = carimbo
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
        p["erro_leitura"] = sinais.get("erro")
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


# O topo se mexe todo dia e e o que as pessoas conferem; a cauda nao muda de
# terca para quarta - morte e lenta. Medir tudo todo dia seriam ~4h30 de
# chamadas ao no publico para descobrir quase nada de novo.
TOPO_DIARIO = 300     # medidos em toda corrida
# O universo e definido por um piso de detentores, nao por um numero redondo:
# medido em 31/08/2026, a posicao 2000 do catalogo tem 150 detentores e a 3000
# tem 83. Cobrir tudo acima de ~100 detentores quer dizer ir ate a posicao
# ~2700 - dai o 2400 de cauda somado aos 300 do topo. Alem disso mora poeira:
# na posicao 8000 o token do topo tem 17 detentores e nunca foi projeto.
CAUDA_TOTAL = 2400
CICLO_DIAS = 15       # cada fatia da cauda e remedida a cada 15 dias
PISO_PRETENDIDO = 100  # detentores; so para a pagina poder declarar a meta


def carregar_projetos(arquivo: str = "dados.json") -> list[dict]:
    if not os.path.exists(arquivo):
        return []
    try:
        with open(arquivo, encoding="utf-8") as f:
            return json.load(f).get("projetos") or []
    except (json.JSONDecodeError, OSError):
        return []


def fatia_do_dia(dia: dt.date | None = None) -> int:
    """Qual pedaco da cauda toca hoje. Deriva da data para nao precisar
    guardar estado nenhum entre corridas."""
    dia = dia or dt.date.today()
    return dia.toordinal() % CICLO_DIAS


def alvos_do_dia(fatia: int) -> list[dict]:
    """Descobre o topo (sempre) mais a fatia da cauda que cabe hoje."""
    tamanho = -(-CAUDA_TOTAL // CICLO_DIAS)  # divisao para cima
    offset = TOPO_DIARIO + fatia * tamanho
    print(
        f"fatia {fatia + 1}/{CICLO_DIAS}: topo {TOPO_DIARIO} + cauda "
        f"{tamanho} a partir de {offset}"
    )
    alvos = descobrir_tokens(TOPO_DIARIO)
    alvos += descobrir_tokens(tamanho, offset)
    alvos += [dict(p) for p in PROJETOS_SEM_TOKEN]
    return alvos


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=0,
                    help="modo avulso: quantos tokens buscar (ignora o ciclo)")
    ap.add_argument("--offset", type=int, default=0, help="pula os N primeiros do catalogo")
    ap.add_argument("--fatia", type=int, default=None,
                    help=f"forca uma fatia do ciclo de {CICLO_DIAS} dias")
    ap.add_argument("--no-rede", action="store_true", help="so reclassifica o dados.json existente")
    args = ap.parse_args()

    if args.no_rede:
        projetos = carregar_projetos()
        normalizar_nomes(projetos)
        for p in projetos:
            p["situacao"], p["motivo"] = classificar(p)
    else:
        if args.limite:
            alvos = descobrir_tokens(args.limite, args.offset)
            alvos += [dict(p) for p in PROJETOS_SEM_TOKEN]
        else:
            alvos = alvos_do_dia(
                args.fatia if args.fatia is not None else fatia_do_dia()
            )

        # Sem tokens a pagina inteira perde o sentido. Melhor abortar e manter
        # o dados.json anterior do que publicar em silencio uma lista vazia.
        if not any(p.get("categoria") == "Token" for p in alvos):
            print(
                "! nenhum token veio do XRPL Meta - dados.json NAO foi alterado.",
                file=sys.stderr,
            )
            sys.exit(1)

        medidos = coletar(alvos)
        projetos = mesclar(carregar_projetos(), medidos)
        # Aqui, e so aqui, holders_anterior/medido_em_anterior ja existem nos
        # projetos remedidos hoje - e a tendencia tem o que comparar.
        aplicar_tendencia(projetos)
        # Reclassifica tudo: os limiares podem ter mudado desde a ultima
        # medicao de quem nao foi medido hoje.
        for p in projetos:
            p["situacao"], p["motivo"] = classificar(p)
        salvar_snapshot(projetos)

    ordem = {"ativo": 0, "morrendo": 1, "parado": 2, "morto": 3, "indeterminado": 4}
    projetos.sort(key=lambda p: (ordem.get(p["situacao"], 9), -(p.get("holders") or 0)))

    medidos_em = sorted(p["medido_em"] for p in projetos if p.get("medido_em"))
    saida = {
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "medicao_mais_antiga": medidos_em[0] if medidos_em else None,
        "ciclo_dias": CICLO_DIAS,
        "piso_pretendido": PISO_PRETENDIDO,
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
