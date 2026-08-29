#!/usr/bin/env python3
"""
Descoberta e medicao de projetos SEM token: fornecedores de infraestrutura,
projetos corporativos, validadores e ferramentas.

O coletor.py resolve o caso facil (quem emite token aparece no XRPL Meta).
Este modulo resolve o caso dificil, com tres instrumentos:

  1. IDENTIDADE  - xrp-ledger.toml, o registro empresarial que a rede ja tem.
  2. PAPEL       - os tipos de objeto que a conta possui no ledger.
  3. OPERACAO    - validador na UNL, servidor publico respondendo.

E declara honestamente o quarto caso: projeto que nao tem pegada nenhuma no
ledger, onde o instrumento certo e o GitHub, nao a rede.
"""

from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

from coletor import RPC, TIMEOUT, AGENTE, _rpc, PAUSA_ENTRE_CHAMADAS, RIPPLE_EPOCH

# --------------------------------------------------------------------------
# 1. IDENTIDADE: xrp-ledger.toml
# --------------------------------------------------------------------------
#
# Em https://dominio/.well-known/xrp-ledger.toml uma empresa declara as contas
# que possui, os validadores que opera, os servidores publicos que mantem, seus
# responsaveis e as moedas que emite.
#
# A verificacao e de mao dupla e e o ponto todo:
#   - o dominio afirma controlar a conta, listando-a em [[ACCOUNTS]]
#   - a conta afirma controlar o dominio, no campo Domain do AccountSet
# Um lado sozinho nao vale nada. Os dois juntos sao prova forte.

CAMINHO_TOML = "/.well-known/xrp-ledger.toml"


def ler_toml(dominio: str) -> tuple[dict | None, str]:
    """Busca e interpreta o xrp-ledger.toml. Devolve (conteudo, motivo).

    O motivo importa: "nao publica identidade" e uma afirmacao sobre o projeto,
    "nao consegui ler" e uma afirmacao sobre nos. Misturar as duas coisas e
    acusar alguem de opacidade por causa de um timeout nosso.

    Motivos: ok | ausente | nao_e_toml | bloqueado | erro_rede | sem_tomllib
    """
    if tomllib is None:
        print("! precisa de Python 3.11+ para ler TOML", file=sys.stderr)
        return None, "sem_tomllib"

    dominio = dominio.replace("https://", "").replace("http://", "").strip("/")
    url = f"https://{dominio}{CAMINHO_TOML}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            bruto = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, "ausente"
        # 403/429 sao bloqueio de bot: nao sabemos se o arquivo existe.
        return None, "bloqueado" if e.code in (401, 403, 429) else "erro_rede"
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None, "erro_rede"

    try:
        return tomllib.loads(bruto), "ok"
    except tomllib.TOMLDecodeError:
        # Muito site devolve o HTML da pagina inicial com 200 no lugar de 404
        # (gatehub.net faz isso). Nao publica TOML, mas nao e falha nossa.
        return None, "nao_e_toml"


def resumir_toml(toml: dict | None, motivo: str = "ok") -> dict:
    """Extrai os sinais uteis do arquivo, incluindo se ele proprio venceu."""
    if not toml:
        return {"tem_toml": False, "toml_motivo": motivo}

    meta = toml.get("METADATA") or {}
    expira = meta.get("expires")
    modificado = meta.get("modified")

    vencido = None
    if expira is not None:
        try:
            # pode vir como datetime (o tomllib converte) ou como string
            ts = expira.timestamp() if hasattr(expira, "timestamp") else None
            vencido = (ts is not None and ts < time.time())
        except Exception:
            vencido = None

    return {
        "tem_toml": True,
        "toml_modificado": str(modificado) if modificado else None,
        "toml_vencido": vencido,
        "contas_declaradas": [
            a.get("address") for a in (toml.get("ACCOUNTS") or []) if a.get("address")
        ],
        "validadores_declarados": [
            v.get("public_key") for v in (toml.get("VALIDATORS") or []) if v.get("public_key")
        ],
        "servidores_declarados": [
            s.get("json_rpc") or s.get("ws") or s.get("domain")
            for s in (toml.get("SERVERS") or [])
        ],
        "moedas_declaradas": [
            c.get("code") for c in (toml.get("CURRENCIES") or []) if c.get("code")
        ],
        "tem_responsavel": bool(toml.get("PRINCIPALS")),
    }


def _dominio_da_conta(endereco: str) -> str | None:
    """Le o campo Domain da conta. Vem em hexadecimal - esquecer de decodificar
    e o erro que faz a verificacao de mao dupla falhar sempre."""
    res = _rpc("account_info", {"account": endereco, "ledger_index": "validated"})
    dados = res.get("account_data") or {}
    hexa = dados.get("Domain")
    if not hexa:
        return None
    try:
        return bytes.fromhex(hexa).decode("utf-8", errors="replace").lower().strip()
    except ValueError:
        return None


def verificar_mao_dupla(dominio: str, contas_declaradas: list[str]) -> dict:
    """Confere quais das contas declaradas apontam de volta para o dominio."""
    alvo = dominio.replace("https://", "").replace("http://", "").strip("/").lower()
    confirmadas, so_declaradas = [], []

    for conta in contas_declaradas[:12]:  # teto para nao abusar do no publico
        de_volta = _dominio_da_conta(conta)
        if de_volta and (de_volta == alvo or de_volta.endswith("." + alvo) or alvo.endswith("." + de_volta)):
            confirmadas.append(conta)
        else:
            so_declaradas.append(conta)
        time.sleep(PAUSA_ENTRE_CHAMADAS)

    return {
        "contas_confirmadas": confirmadas,
        "contas_so_declaradas": so_declaradas,
        "verificacao": "mao dupla" if confirmadas else ("so o dominio afirma" if so_declaradas else "nenhuma"),
    }


# --------------------------------------------------------------------------
# 2. PAPEL: o que a conta guarda no ledger
# --------------------------------------------------------------------------
#
# Uma conta corporativa nao precisa emitir token para deixar rastro. O tipo dos
# objetos que ela possui diz o que ela faz - e e um sinal muito mais dificil de
# falsificar que uma pagina institucional.

PAPEL_POR_OBJETO = {
    "Oracle":              "Provedor de oraculo",
    "Bridge":              "Operador de ponte",
    "XChainOwnedClaimID":  "Operador de ponte",
    "Credential":          "Emissor de credencial (KYC)",
    "PermissionedDomain":  "Dominio permissionado",
    "MPTokenIssuance":     "Emissor de MPT / RWA",
    "Vault":               "Cofre tokenizado",
    "LoanBroker":          "Protocolo de credito",
    "Loan":                "Protocolo de credito",
    "PayChannel":          "Servico de canal de pagamento",
    "AMM":                 "Pool de liquidez",
    "NFTokenOffer":        "Mercado de NFT",
    "Check":               "Emissor de cheques",
    "Escrow":              "Custodia por escrow",
    "DepositPreauth":      "Conta com pre-autorizacao",
    "Delegate":            "Operacao com permissoes delegadas",
    "SignerList":          "Conta multi-assinatura",
}

# Tipos que sozinhos ja indicam ator institucional, nao pessoa fisica.
SINAIS_CORPORATIVOS = {
    "Oracle", "Bridge", "XChainOwnedClaimID", "Credential", "PermissionedDomain",
    "MPTokenIssuance", "Vault", "LoanBroker", "PayChannel", "DepositPreauth",
    "Delegate", "SignerList",
}


def papel_da_conta(endereco: str) -> dict:
    """Conta os objetos por tipo e deduz o papel da conta na rede."""
    contagem: dict[str, int] = {}
    marker = None
    paginas = 0

    while paginas < 6:
        params: dict[str, Any] = {
            "account": endereco,
            "ledger_index": "validated",
            "limit": 200,
        }
        if marker:
            params["marker"] = marker

        res = _rpc("account_objects", params)
        objetos = res.get("account_objects") or []
        if not objetos and paginas == 0:
            return {"papeis": [], "objetos": {}, "corporativa": False}

        for o in objetos:
            tipo = o.get("LedgerEntryType")
            if tipo:
                contagem[tipo] = contagem.get(tipo, 0) + 1

        marker = res.get("marker")
        paginas += 1
        if not marker:
            break
        time.sleep(PAUSA_ENTRE_CHAMADAS)

    papeis = []
    for tipo in contagem:
        rotulo = PAPEL_POR_OBJETO.get(tipo)
        if rotulo and rotulo not in papeis:
            papeis.append(rotulo)

    return {
        "papeis": papeis,
        "objetos": contagem,
        "corporativa": bool(SINAIS_CORPORATIVOS & set(contagem)),
        "truncado": bool(marker),
    }


# --------------------------------------------------------------------------
# 3. OPERACAO: validadores e servidores publicos
# --------------------------------------------------------------------------


# Lista de validadores publicada pela Ripple, a UNL padrao que a maioria dos
# servidores usa. O metodo "validators" do rippled e de administrador: no no
# publico ele volta vazio, entao a fonte honesta e a lista assinada.
UNL_PUBLICADA = "https://vl.ripple.com"


def _unl_publicada() -> dict:
    """Baixa e abre a UNL assinada. O conteudo vem num blob base64 - nao
    verificamos a assinatura aqui, so lemos; por isso a fonte fica declarada
    na saida, para quem quiser conferir."""
    req = urllib.request.Request(UNL_PUBLICADA, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        envelope = json.loads(r.read().decode("utf-8"))

    # Formato v1 traz um blob; o v2 traz uma lista deles (a atual e a ultima).
    blobs = [envelope["blob"]] if "blob" in envelope else [
        b["blob"] for b in envelope.get("blobs_v2", [])
    ]
    if not blobs:
        return {}
    return json.loads(base64.b64decode(blobs[-1]))


def estado_dos_validadores() -> dict:
    """
    Quem opera validador e, por definicao, fornecedor de infraestrutura.
    A NegativeUNL e a propria rede dizendo quais validadores considera fora do
    ar - nao ha sinal de vida mais direto e menos discutivel que esse.
    """
    quantidade = None
    expira_em = None
    try:
        blob = _unl_publicada()
        validadores = blob.get("validators") or []
        quantidade = len(validadores)
        if blob.get("expiration"):
            # A lista tambem conta o tempo no epoch da XRPL.
            expira_em = time.strftime(
                "%Y-%m-%d", time.gmtime(blob["expiration"] + RIPPLE_EPOCH)
            )
    except Exception as e:
        print(f"! nao consegui ler a UNL publicada: {e}", file=sys.stderr)

    # A NegativeUNL e um objeto unico do ledger. A opcao correta do
    # ledger_entry e "nunl"; "negative_unl" devolve unknownOption.
    # Quando nenhum validador esta desabilitado o objeto simplesmente nao
    # existe, e o no responde entryNotFound - isso e lista vazia, nao falha.
    negativa = set()
    res = _rpc("ledger_entry", {"nunl": True, "ledger_index": "validated"}) or {}
    erro = res.get("error")
    for d in (res.get("node") or {}).get("DisabledValidators") or []:
        chave = (d.get("DisabledValidator") or {}).get("PublicKey")
        if chave:
            negativa.add(chave)

    return {
        "fonte_unl": UNL_PUBLICADA,
        "quantidade_unl": quantidade,
        "unl_expira_em": expira_em,
        "na_lista_negativa": sorted(negativa),
        "lista_negativa_lida": erro in (None, "entryNotFound"),
    }


def servidor_publico_responde(url: str) -> bool | None:
    """Bate um server_info no endpoint publico declarado pelo projeto."""
    if not url:
        return None
    if url.startswith("ws"):
        return None  # WebSocket exige biblioteca; deixe para uma versao futura
    try:
        corpo = json.dumps({"method": "server_info", "params": [{}]}).encode()
        req = urllib.request.Request(
            url, data=corpo,
            headers={"Content-Type": "application/json", "User-Agent": AGENTE},
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            dados = json.loads(r.read().decode())
        estado = (dados.get("result", {}).get("info", {}) or {}).get("server_state")
        return estado in ("full", "validating", "proposing")
    except Exception:
        return False


# --------------------------------------------------------------------------
# 4. O caso honesto: projeto sem pegada no ledger
# --------------------------------------------------------------------------


def vitalidade_do_repositorio(repo: str) -> dict:
    """
    Biblioteca, SDK e ferramenta de linha de comando nao deixam rastro na rede.
    Fingir que deixam seria desonesto. Para esses, o instrumento certo e o
    repositorio. Sem token da API da o suficiente para uso leve.

    repo no formato "organizacao/projeto".
    """
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}",
            headers={"User-Agent": AGENTE, "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode())
        return {
            "repo": repo,
            "ultimo_push": d.get("pushed_at"),
            "estrelas": d.get("stargazers_count"),
            "arquivado": d.get("archived"),
            "issues_abertas": d.get("open_issues_count"),
        }
    except Exception:
        return {"repo": repo, "erro": True}


# --------------------------------------------------------------------------
# Orquestracao: mede um projeto corporativo inteiro
# --------------------------------------------------------------------------


def medir_projeto_corporativo(projeto: dict) -> dict:
    """
    projeto = {"nome":..., "site":..., "categoria":..., "repo": opcional,
               "contas": opcional (se voce ja conhece)}
    """
    p = dict(projeto)
    dominio = (p.get("site") or "").replace("https://", "").replace("http://", "").strip("/")

    toml, motivo_toml = ler_toml(dominio) if dominio else (None, "sem_dominio")
    p.update(resumir_toml(toml, motivo_toml))

    contas = p.get("contas") or p.get("contas_declaradas") or []
    if contas and dominio:
        p.update(verificar_mao_dupla(dominio, contas))

    # O papel vem da conta confirmada; se nenhuma confirmou, usa a primeira
    # declarada, mas registrando que a verificacao e mais fraca.
    alvo = (p.get("contas_confirmadas") or contas or [None])[0]
    if alvo:
        p["conta_medida"] = alvo
        p.update(papel_da_conta(alvo))

    for url in (p.get("servidores_declarados") or [])[:2]:
        if url and url.startswith("http"):
            p["servidor_publico_ok"] = servidor_publico_responde(url)
            break

    if p.get("repo"):
        p["github"] = vitalidade_do_repositorio(p["repo"])

    return p


def classificar_corporativo(p: dict) -> tuple[str, str]:
    """Regra separada: o que mantem um fornecedor de infra vivo nao e volume
    de transacao, e continuar operando e continuar se declarando."""
    tem_toml = p.get("tem_toml")
    vencido = p.get("toml_vencido")
    verificacao = p.get("verificacao")
    papeis = p.get("papeis") or []
    servidor = p.get("servidor_publico_ok")
    gh = p.get("github") or {}

    if gh.get("arquivado"):
        return "morto", "Repositorio arquivado pelo proprio autor."

    if tem_toml and vencido:
        return "morrendo", "Publica xrp-ledger.toml, mas o arquivo esta vencido."

    if tem_toml and verificacao == "mao dupla":
        detalhe = f"; atua como {', '.join(papeis[:2]).lower()}" if papeis else ""
        return "ativo", f"Identidade verificada nos dois sentidos{detalhe}."

    if servidor is True:
        return "ativo", "Servidor publico declarado esta respondendo."

    if papeis:
        return "ativo", f"Sem toml verificado, mas opera como {', '.join(papeis[:2]).lower()}."

    if tem_toml:
        return "morrendo", "Publica xrp-ledger.toml, mas nenhuma conta confirma o dominio de volta."

    if p.get("site_ok") is True:
        return "indeterminado", "Site no ar, mas sem identidade nem objetos na rede para medir."

    if p.get("site_ok") is False:
        return "morto", "Site fora do ar e sem nenhuma presenca no ledger."

    return "indeterminado", "Nao foi possivel medir."


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("uso: python descoberta.py <dominio>   ex: python descoberta.py bithomp.com")
        sys.exit(0)

    alvo = sys.argv[1]
    print(f"Lendo {alvo}{CAMINHO_TOML} ...\n")
    resultado = medir_projeto_corporativo({"nome": alvo, "site": alvo, "categoria": "Infra"})
    situacao, motivo = classificar_corporativo(resultado)
    resultado["situacao"], resultado["motivo"] = situacao, motivo
    print(json.dumps(resultado, ensure_ascii=False, indent=1, default=str))
