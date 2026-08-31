#!/usr/bin/env python3
"""
Descoberta continua de atores institucionais na XRPL.

Certos tipos de transacao so aparecem quando ha empresa por tras: ninguem
publica oraculo, abre ponte entre cadeias ou emite credencial por hobby. Em vez
de varrer o ledger inteiro atras deles - caro e cruel com no publico - a gente
fica ouvindo o fluxo de transacoes validadas e anota quem aparece.

O resultado NAO entra na pagina automaticamente. Vai para candidatos.json, para
revisao humana. Endereco visto uma vez e pista, nao projeto.

Uso:
    python institucional.py --minutos 10
    python institucional.py --minutos 60 --arquivo candidatos.json
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import socket
import ssl
import struct
import sys
import time

# Tipos de transacao que denunciam ator institucional. Um hobbysta emite token;
# ele nao publica oraculo de preco nem abre ponte entre cadeias.
TIPOS_INSTITUCIONAIS = {
    "OracleSet": "Oraculo de precos",
    "XChainCreateBridge": "Ponte entre cadeias",
    "XChainCreateClaimID": "Ponte entre cadeias",
    "CredentialCreate": "Emissor de credencial",
    "MPTokenIssuanceCreate": "Emissor de token multiuso",
    "PermissionedDomainSet": "Dominio permissionado",
    "VaultCreate": "Cofre / mercado de credito",
    "LoanBrokerSet": "Corretora de emprestimo",
    "LoanSet": "Corretora de emprestimo",
}

WS_PADRAO = "wss://xrplcluster.com"


# --------------------------------------------------------------------------
# Cliente WebSocket minimo (RFC 6455), so com biblioteca padrao
# --------------------------------------------------------------------------
#
# A regra do projeto e zero dependencia externa, e a stdlib nao traz cliente
# WebSocket. Sao ~100 linhas: aperto de mao HTTP, quadros mascarados na ida,
# quadros crus na volta. So precisamos de texto, ping e fechamento.


class WebSocketMinimo:
    def __init__(self, url: str, timeout: float = 40.0):
        seguro = url.startswith("wss://")
        resto = url.split("://", 1)[1]
        host, _, caminho = resto.partition("/")
        host, _, porta = host.partition(":")
        self.host = host
        self.porta = int(porta) if porta else (443 if seguro else 80)
        self.caminho = "/" + caminho
        self.timeout = timeout

        cru = socket.create_connection((self.host, self.porta), timeout=timeout)
        self.sock = (
            ssl.create_default_context().wrap_socket(cru, server_hostname=self.host)
            if seguro
            else cru
        )
        self._aperto_de_mao()
        self._buffer = b""

    def _aperto_de_mao(self) -> None:
        chave = base64.b64encode(os.urandom(16)).decode()
        pedido = (
            f"GET {self.caminho} HTTP/1.1\r\n"
            f"Host: {self.host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {chave}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "User-Agent: rwalive/1.0\r\n\r\n"
        )
        self.sock.sendall(pedido.encode())

        resposta = b""
        while b"\r\n\r\n" not in resposta:
            pedaco = self.sock.recv(4096)
            if not pedaco:
                raise ConnectionError("servidor fechou durante o aperto de mao")
            resposta += pedaco
        if b" 101 " not in resposta.split(b"\r\n", 1)[0]:
            raise ConnectionError(f"aperto de mao recusado: {resposta[:120]!r}")
        self._buffer = resposta.split(b"\r\n\r\n", 1)[1]

    def _ler(self, n: int) -> bytes:
        while len(self._buffer) < n:
            pedaco = self.sock.recv(65536)
            if not pedaco:
                raise ConnectionError("conexao encerrada pelo servidor")
            self._buffer += pedaco
        dados, self._buffer = self._buffer[:n], self._buffer[n:]
        return dados

    def enviar(self, texto: str) -> None:
        corpo = texto.encode()
        cabeca = bytearray([0x81])  # FIN + opcode texto
        n = len(corpo)
        if n < 126:
            cabeca.append(0x80 | n)
        elif n < 65536:
            cabeca.append(0x80 | 126)
            cabeca += struct.pack(">H", n)
        else:
            cabeca.append(0x80 | 127)
            cabeca += struct.pack(">Q", n)
        mascara = os.urandom(4)
        cabeca += mascara
        self.sock.sendall(
            bytes(cabeca) + bytes(b ^ mascara[i % 4] for i, b in enumerate(corpo))
        )

    def receber(self) -> str | None:
        """Devolve a proxima mensagem de texto, ou None se a conexao fechou."""
        partes = []
        while True:
            b1, b2 = self._ler(2)
            fim = b1 & 0x80
            opcode = b1 & 0x0F
            tamanho = b2 & 0x7F
            if tamanho == 126:
                tamanho = struct.unpack(">H", self._ler(2))[0]
            elif tamanho == 127:
                tamanho = struct.unpack(">Q", self._ler(8))[0]
            carga = self._ler(tamanho) if tamanho else b""

            if opcode == 0x8:  # fechar
                return None
            if opcode == 0x9:  # ping -> pong com a mesma carga
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if opcode == 0xA:  # pong
                continue

            partes.append(carga)
            if fim:
                return b"".join(partes).decode("utf-8", errors="replace")

    def fechar(self) -> None:
        try:
            self.sock.sendall(bytes([0x88, 0x80]) + os.urandom(4))
            self.sock.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Escuta
# --------------------------------------------------------------------------


def _contas_da_transacao(tx: dict) -> list[str]:
    """Quem assinou e, quando faz sentido, o alvo. So enderecos r..."""
    contas = []
    for campo in ("Account", "Destination", "Owner", "Issuer", "Subject"):
        valor = tx.get(campo)
        if isinstance(valor, str) and valor.startswith("r"):
            contas.append(valor)
    return contas


def escutar(minutos: float, ws_url: str = WS_PADRAO, verboso: bool = True) -> dict:
    """Ouve o fluxo de transacoes validadas e anota os atores institucionais."""
    fim = time.time() + minutos * 60
    achados: dict[str, dict] = {}
    total = 0

    ws = WebSocketMinimo(ws_url)
    ws.enviar(json.dumps({"id": 1, "command": "subscribe", "streams": ["transactions"]}))

    try:
        while time.time() < fim:
            restante = max(1.0, fim - time.time())
            ws.sock.settimeout(restante)
            try:
                bruto = ws.receber()
            except (socket.timeout, TimeoutError):
                break
            if bruto is None:
                print("! o no fechou a conexao antes do fim", file=sys.stderr)
                break

            msg = json.loads(bruto)
            if msg.get("type") != "transaction":
                continue
            total += 1

            # v1 traz "transaction", v2 traz "tx_json".
            tx = msg.get("tx_json") or msg.get("transaction") or {}
            tipo = tx.get("TransactionType")
            if tipo not in TIPOS_INSTITUCIONAIS:
                continue
            if (msg.get("meta") or {}).get("TransactionResult") != "tesSUCCESS":
                continue

            agora = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            for conta in _contas_da_transacao(tx):
                reg = achados.setdefault(
                    conta,
                    {
                        "conta": conta,
                        "papeis": [],
                        "tipos": [],
                        "vezes": 0,
                        "primeira_vez": agora,
                        "ultima_vez": agora,
                    },
                )
                reg["vezes"] += 1
                reg["ultima_vez"] = agora
                if tipo not in reg["tipos"]:
                    reg["tipos"].append(tipo)
                papel = TIPOS_INSTITUCIONAIS[tipo]
                if papel not in reg["papeis"]:
                    reg["papeis"].append(papel)
                if verboso:
                    print(f"  {tipo:24} {conta}")
    finally:
        ws.fechar()

    if verboso:
        print(f"\n{total} transacoes ouvidas, {len(achados)} contas institucionais.")
    return achados


def juntar(arquivo: str, novos: dict) -> dict:
    """Soma o que ja havia no arquivo, sem perder a primeira aparicao."""
    antigos = {}
    if os.path.exists(arquivo):
        with open(arquivo, encoding="utf-8") as f:
            dados = json.load(f)
        antigos = {c["conta"]: c for c in dados.get("candidatos", [])}

    for conta, novo in novos.items():
        velho = antigos.get(conta)
        if not velho:
            antigos[conta] = novo
            continue
        velho["vezes"] += novo["vezes"]
        velho["ultima_vez"] = novo["ultima_vez"]
        for chave in ("tipos", "papeis"):
            for v in novo[chave]:
                if v not in velho[chave]:
                    velho[chave].append(v)
    return antigos


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutos", type=float, default=10, help="quanto tempo ouvir")
    ap.add_argument("--arquivo", default="candidatos.json")
    ap.add_argument("--no", default=WS_PADRAO, dest="no_ws")
    args = ap.parse_args()

    print(f"Ouvindo {args.no_ws} por {args.minutos} min...")
    achados = escutar(args.minutos, args.no_ws)
    todos = juntar(args.arquivo, achados)

    saida = {
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "AVISO": "candidatos brutos - exigem revisao humana antes de entrar na pagina",
        "total": len(todos),
        "candidatos": sorted(todos.values(), key=lambda c: -c["vezes"]),
    }
    with open(args.arquivo, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=1)
    print(f"{args.arquivo} escrito ({len(todos)} contas acumuladas).")


if __name__ == "__main__":
    main()
