#!/usr/bin/env python3
"""
Migracao de uma vez so: reescreve as chaves de historico/ para a chave nova.

Por que existe. Ate 31/08/2026 o `salvar_snapshot()` gravava o snapshot com
`emissor or nome` como chave, enquanto `chave_do_projeto()` - a identidade que
`mesclar()` e `aplicar_tendencia()` usam - e `emissor:moeda`. As duas nunca
casavam: a tendencia de detentores procurava `rABC:USD` num arquivo que so
tinha `rABC`, nao achava nada, e nao reclamava. Efeito medido em 31/08: zero
dos 678 projetos tinham `variacao_holders`. A pagina tinha uma coluna de
tendencia que nunca teve como aparecer.

O commit a6bfa95 corrigiu o lado que ESCREVE. Sem esta migracao a correcao
seguiria inerte por outro motivo: os arquivos no disco continuariam na chave
velha, e o primeiro `mudancas.py` depois da correcao compararia chave nova
contra chave velha - nenhuma em comum - e imprimiria "678 measured for the
first time / 656 left the scope" como material pronto para post. Falha em
silencio virando manchete falsa.

O que faz com cada chave velha:

  emissor com UMA moeda no dados.json  -> vira `emissor:moeda`.
  emissor com VARIAS moedas, nome bate -> vira `emissor:moeda` do nome que bate.
  emissor com VARIAS moedas, nome nao  -> APAGA. Este e o registro corrompido
      pela colisao: a chave curta fazia o ultimo token escrito apagar o outro,
      entao os numeros guardados podem ser de qualquer um dos dois. Guardar sob
      uma chave adivinhada inventaria uma comparacao - o oposto do projeto.
  projeto sem emissor (nome como chave) -> vira `site:<site>`.
  nao encontrado no dados.json          -> fica como esta. Saiu do escopo; nao
      da para adivinhar a moeda de quem nao esta mais na lista, e apagar
      historico por nao saber mapear seria pior.

`historico/` e sagrado: nada aqui inventa numero, nada renomeia projeto. So a
chave muda, e o arquivo original esta versionado no git - `git show
HEAD:historico/2026-08-31.json` devolve o de antes.

Uso:
    python migrar_historico.py --ensaio    # mostra o que faria, nao escreve
    python migrar_historico.py
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os

from coletor import carregar_projetos, chave_do_projeto, moeda_canonica

PASTA = "historico"


def mapa_de_chaves(projetos: list[dict]) -> tuple[dict, dict]:
    """(chave velha -> chave nova) para o caso simples, e (emissor -> projetos)
    para o caso de emissor com mais de uma moeda."""
    por_emissor = collections.defaultdict(list)
    por_nome = {}
    for p in projetos:
        if p.get("emissor"):
            por_emissor[p["emissor"]].append(p)
        else:
            # Antes, projeto sem token entrava no snapshot pelo nome.
            por_nome[str(p.get("nome") or "")] = chave_do_projeto(p)

    simples = {}
    for emissor, ps in por_emissor.items():
        if len(ps) == 1:
            simples[emissor] = chave_do_projeto(ps[0])
    simples.update(por_nome)
    return simples, dict(por_emissor)


def migrar(snap: dict, simples: dict, por_emissor: dict) -> tuple[dict, list, list]:
    novo = {}
    apagados = []
    intocados = []
    for velha, reg in snap.items():
        if ":" in velha:
            # Ja migrada, mas a forma canonica da moeda pode ter mudado depois
            # (o da1e3b7 passou a normalizar codigo de 3 letras para maiuscula,
            # e chaves como `...:sos` viraram `...:SOS`). Renormalizar aqui e o
            # que torna esta migracao repetivel: rodar de novo conserta em vez
            # de deixar chave velha passando batido.
            if velha.startswith("site:"):  # projeto sem token: nao tem moeda
                novo[velha] = reg
                continue
            emissor, _, moeda = velha.partition(":")
            novo[f"{emissor}:{moeda_canonica(moeda)}"] = reg
            continue
        if velha in simples:
            novo[simples[velha]] = reg
            continue
        candidatos = por_emissor.get(velha)
        if candidatos:
            nome = str(reg.get("nome") or "").lower()
            iguais = [p for p in candidatos if str(p.get("nome") or "").lower() == nome]
            if len(iguais) == 1:
                novo[chave_do_projeto(iguais[0])] = reg
            else:
                apagados.append((velha, reg.get("nome"), len(candidatos)))
            continue
        novo[velha] = reg
        intocados.append(velha)
    return novo, apagados, intocados


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensaio", action="store_true", help="nao escreve nada")
    args = ap.parse_args()

    projetos = carregar_projetos()
    if not projetos:
        raise SystemExit("! dados.json vazio; a migracao depende dele para achar a moeda")
    simples, por_emissor = mapa_de_chaves(projetos)

    for caminho in sorted(glob.glob(os.path.join(PASTA, "*.json"))):
        with open(caminho, encoding="utf-8") as f:
            snap = json.load(f)
        novo, apagados, intocados = migrar(snap, simples, por_emissor)
        nome = os.path.basename(caminho)
        print(f"{nome}: {len(snap)} -> {len(novo)} chaves"
              f" | colisao apagada: {len(apagados)}"
              f" | fora do dados.json, mantida: {len(intocados)}")
        for velha, n, quantos in apagados:
            print(f"    apaga {velha[:16]}... ({n!r}, {quantos} moedas no mesmo emissor)")
        if intocados:
            print(f"    mantidas: {', '.join(v[:16] for v in intocados)}")
        if not args.ensaio:
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(novo, f, ensure_ascii=False, indent=1)
    print("ensaio: nada foi escrito." if args.ensaio else "historico/ migrado.")


if __name__ == "__main__":
    main()
