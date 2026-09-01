#!/usr/bin/env python3
"""
Gera a pagina estatica a partir do dados.json produzido pelo coletor.

Sem framework, sem build, sem dependencia: um arquivo HTML que o GitHub Pages
serve de graca. O robo roda, o arquivo muda, a pagina se atualiza sozinha.

Uso:
    python gerar_site.py            # le dados.json, escreve site/index.html
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import sys
import unicodedata
import urllib.parse

# Endereco do repositorio, usado no canal de contestacao da pagina.
REPO = os.environ.get("STILLALIVE_REPO", "")

# Explorador para onde os enderecos apontam. O da XRPL Foundation e o unico
# neutro: os outros grandes sao projetos que esta pagina classifica.
EXPLORADOR = "https://livenet.xrpl.org/accounts/"

SITUACOES = {
    "ativo": ("Alive", "Transacting on the ledger right now."),
    "morrendo": ("Fading", "Still breathing, but the movement dropped off."),
    "parado": ("Dormant", "No meaningful activity for months."),
    "morto": ("Dead", "No sign of life and no website up."),
    "indeterminado": ("Unknown", "Could not be measured with confidence."),
}

JS = """
<script>
// Busca e filtro no proprio navegador. Nao ha servidor para consultar, e a
// pagina inteira ja esta aqui - filtrar e esconder linha, nao pedir dados.
(function(){
  var busca = document.getElementById('busca');
  var conta = document.getElementById('conta');
  var linhas = Array.prototype.slice.call(document.querySelectorAll('.linha'));
  var selos = Array.prototype.slice.call(document.querySelectorAll('.selo'));
  var grupos = Array.prototype.slice.call(document.querySelectorAll('.grupo'));
  var filtros = {};

  function aplicar(){
    var termo = (busca.value || '').trim().toLowerCase();
    var algumFiltro = Object.keys(filtros).some(function(k){ return filtros[k]; });
    var visiveis = 0;
    linhas.forEach(function(el){
      var passaTermo = !termo || el.dataset.b.indexOf(termo) !== -1;
      var passaFiltro = !algumFiltro || filtros[el.dataset.s];
      var mostra = passaTermo && passaFiltro;
      el.hidden = !mostra;
      if (mostra) visiveis++;
    });
    grupos.forEach(function(g){
      var doGrupo = g.querySelectorAll('.linha');
      var n = 0;
      Array.prototype.forEach.call(doGrupo, function(el){ if (!el.hidden) n++; });
      var rotulo = g.querySelector('[data-conta]');
      if (rotulo) rotulo.textContent = '(' + n + ')';
      var vazio = g.querySelector('.vazio');
      // O grupo inteiro sai de cena quando nenhum item dele sobrou, para a
      // pagina nao virar uma sequencia de cabecalhos vazios.
      g.hidden = (n === 0 && (termo || algumFiltro));
      if (vazio) vazio.hidden = true;
    });
    conta.textContent = visiveis + (visiveis === 1 ? ' project' : ' projects');
  }

  // Toque nao tem hover: um toque na linha abre o motivo. Clique em link
  // dentro dela segue sendo clique no link.
  linhas.forEach(function(el){
    el.addEventListener('click', function(ev){
      if (ev.target.closest('a')) return;
      el.classList.toggle('aberta');
    });
  });

  busca.addEventListener('input', aplicar);
  busca.addEventListener('search', aplicar);
  selos.forEach(function(b){
    b.addEventListener('click', function(){
      var k = b.dataset.f;
      filtros[k] = !filtros[k];
      b.setAttribute('aria-pressed', filtros[k] ? 'true' : 'false');
      aplicar();
    });
  });
  // "/" cai na busca, como em quase todo lugar que tem lista longa.
  document.addEventListener('keydown', function(ev){
    if (ev.key === '/' && document.activeElement !== busca){
      ev.preventDefault(); busca.focus();
    }
    if (ev.key === 'Escape' && document.activeElement === busca){
      busca.value = ''; aplicar(); busca.blur();
    }
  });
})();
</script>
"""


CSS = """
:root{
  /* Escuro sempre. Quem olha esta pagina olha terminal e explorador de blocos
     o dia inteiro, e e onde as cinco cores de situacao ficam mais separadas.
     color-scheme:dark faz o navegador desenhar o campo de busca e a barra de
     rolagem escuros tambem - sem isso o input sai branco no meio da barra. */
  color-scheme:dark;
  --ground:#0B1113;--surface:#131B1D;--sunken:#0E1517;--ink:#E6EDEB;--muted:#93A4A3;
  --rule:#25302F;--accent:#5CC9AA;--amber:#DCA65C;--red:#E58472;--slate:#8D9C9E;
  --violeta:#AC9DDB;
  --serif:"Fraunces",Georgia,serif;--sans:"Source Sans 3",system-ui,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
}
/* Sem variante clara: antes havia um @media prefers-color-scheme:light que
   sobrescrevia tudo, e em sistema no modo claro - a maioria - a pagina saia
   clara. A pagina e escura, ponto. */
*{box-sizing:border-box}
/* SEM ISTO A BUSCA NAO ESCONDE NADA: .linha usa display:grid e .grupo usa
   display:flex, e regra de classe ganha do [hidden] da folha do navegador.
   O JS marcava el.hidden e a linha continuava na tela. */
[hidden]{display:none!important}
body{background:var(--ground);color:var(--ink);font-family:var(--sans);
  font-size:16px;line-height:1.5;margin:0;-webkit-font-smoothing:antialiased}
.page{max-width:72rem;margin:0 auto;padding:clamp(1.5rem,4vw,3rem) clamp(.7rem,3vw,1.5rem) 4rem;
  display:flex;flex-direction:column;gap:1.5rem}
.eyebrow{font-family:var(--mono);font-size:.68rem;letter-spacing:.13em;
  text-transform:uppercase;color:var(--muted)}
h1{font-family:var(--serif);font-weight:600;font-size:clamp(1.7rem,4vw,2.3rem);
  line-height:1.1;letter-spacing:-.015em;margin:.4rem 0 0}
header .sub{margin:.15rem 0 0;font-size:1rem;color:var(--muted)}
.dek{color:var(--muted);max-width:38rem;margin:.5rem 0 0;font-size:.95rem}
.experimento{color:var(--muted);max-width:44rem;margin:.8rem 0 0;font-size:.88rem;
  border-left:2px solid var(--rule);padding-left:.8rem}
.experimento b{color:var(--ink);font-weight:600}
.escopo{color:var(--muted);max-width:44rem;margin:.7rem 0 0;font-size:.85rem;
  border-left:2px solid var(--rule);padding-left:.8rem}
.escopo b{color:var(--ink);font-weight:600}
h2{font-family:var(--serif);font-weight:600;font-size:1.15rem;margin:0}

/* Barra que acompanha a rolagem: contadores e busca sempre a mao. Numa lista
   de centenas de linhas, procurar um nome e a acao mais comum. */
.barra{position:sticky;top:0;z-index:5;background:var(--ground);
  border-bottom:1px solid var(--rule);padding:.6rem 0;margin-bottom:-.5rem;
  display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}
.placar{display:flex;flex-wrap:wrap;gap:.35rem}
.selo{font-family:var(--mono);font-size:.72rem;padding:.3rem .55rem;border-radius:2px;
  border:1px solid var(--rule);background:var(--surface);color:var(--muted);
  cursor:pointer;user-select:none}
.selo:hover{border-color:var(--muted)}
.selo[aria-pressed="true"]{background:var(--ink);color:var(--ground);border-color:var(--ink)}
.selo b{font-weight:600;color:inherit;font-variant-numeric:tabular-nums}
.selo[aria-pressed="true"] .ponto{box-shadow:0 0 0 1px var(--ground)}
.selo .ponto{display:inline-block;width:.5em;height:.5em;border-radius:50%;
  margin-right:.4em;vertical-align:.05em}
#busca{flex:1;min-width:12rem;font-family:var(--mono);font-size:.8rem;
  padding:.35rem .6rem;border:1px solid var(--rule);border-radius:2px;
  background:var(--surface);color:var(--ink)}
#busca::placeholder{color:var(--muted)}
.conta{font-family:var(--mono);font-size:.72rem;color:var(--muted);white-space:nowrap}

.grupo{display:flex;flex-direction:column;gap:.15rem}
.cabeca{display:flex;align-items:baseline;gap:.6rem;flex-wrap:wrap;
  padding-top:.9rem;border-top:1px solid var(--rule);margin-bottom:.3rem}
.cabeca p{margin:0;color:var(--muted);font-size:.85rem}

/* Uma linha por projeto. Cartao gastava tres vezes a altura para dizer o
   mesmo, e a pagina inteira nao cabia em rolagem nenhuma. */
.linha{background:var(--surface);border:1px solid var(--rule);border-left:3px solid var(--slate);
  border-radius:2px;padding:.4rem .7rem;display:grid;gap:.1rem .8rem;
  grid-template-columns:minmax(9rem,14rem) 1fr}
.linha.ativo{border-left-color:var(--accent)}
.linha.morrendo{border-left-color:var(--amber)}
.linha.parado{border-left-color:var(--slate)}
.linha.morto{border-left-color:var(--red)}
.linha.indeterminado{border-left-color:var(--violeta)}
.linha .nome{font-weight:600;font-size:.95rem;display:flex;align-items:baseline;gap:.4rem}
.linha .nome .ponto{flex:none;width:.5em;height:.5em;border-radius:50%}
/* Duas formas de marcar a cor: na linha o ponto herda do <article class="linha
   ativo"> (descendente); no contador do topo a propria bolinha carrega a classe
   (.ponto.ativo). So o descendente estava escrito, e por isso as bolinhas dos
   contadores saiam sem cor nenhuma - um vao em branco antes do numero. */
.ativo .ponto,.ponto.ativo{background:var(--accent)}
.morrendo .ponto,.ponto.morrendo{background:var(--amber)}
.parado .ponto,.ponto.parado{background:var(--slate)}
.morto .ponto,.ponto.morto{background:var(--red)}
.indeterminado .ponto,.ponto.indeterminado{background:var(--violeta)}
/* O motivo sai da linha e aparece no hover, no foco do teclado ou no toque.
   A pagina fica com um terco da altura; a prova continua a um gesto. */
.linha .motivo{font-size:.83rem;color:var(--muted);grid-column:1/-1;
  display:none;padding-top:.15rem;border-top:1px dashed var(--rule);margin-top:.2rem}
.linha:hover .motivo,.linha:focus-within .motivo,.linha.aberta .motivo{display:block}
.linha{cursor:default}
.linha:hover{border-color:var(--muted)}
.linha .id{font-family:var(--mono);font-size:.68rem;color:var(--muted);
  grid-column:1;overflow-wrap:anywhere}
.linha .metricas{font-family:var(--mono);font-size:.7rem;color:var(--muted);
  font-variant-numeric:tabular-nums;display:flex;flex-wrap:wrap;gap:.6rem;grid-column:2}
.colisao{font-family:var(--mono);font-size:.6rem;text-transform:uppercase;
  letter-spacing:.06em;color:var(--amber);border:1px solid var(--amber);
  border-radius:2px;padding:0 .3em;white-space:nowrap;cursor:help}
.cat{font-family:var(--mono);font-size:.62rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:.06em;white-space:nowrap}
.sobe{color:var(--accent)}.desce{color:var(--red)}
.quando{opacity:.7;font-style:italic}
.pedir{margin-left:.5em;font-size:.95em;opacity:.6}
.linha a{color:inherit;text-decoration:none;border-bottom:1px solid var(--rule)}
.linha a:hover{border-bottom-color:currentColor}
a:focus-visible,#busca:focus-visible,.selo:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.vazio{color:var(--muted);font-size:.9rem;padding:.6rem 0}
.aviso{background:var(--sunken);border:1px solid var(--rule);
  border-left:3px solid var(--amber);border-radius:3px;
  padding:1.1rem 1.3rem;font-size:.86rem}
.aviso p{margin:0 0 .6rem;color:var(--muted);max-width:44rem}
.aviso p:last-child{margin-bottom:0}
.aviso b{color:var(--ink);font-weight:600}
.metodo{background:var(--surface);border:1px solid var(--rule);border-radius:3px;
  padding:1.1rem 1.3rem;font-size:.9rem}
.metodo p{margin:0 0 .6rem;color:var(--muted);max-width:44rem}
.metodo p:last-child{margin-bottom:0}
.metodo code{font-family:var(--mono);font-size:.85em;background:var(--sunken);
  padding:.1em .35em;border-radius:2px}
footer{border-top:1px solid var(--rule);padding-top:1rem;font-size:.82rem;color:var(--muted)}
@media (max-width:38rem){
  .linha{grid-template-columns:1fr}
  .linha .motivo,.linha .metricas,.linha .id{grid-column:1}
}
"""


def _fmt(n) -> str:
    if not isinstance(n, (int, float)):
        return "-"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(int(n))


def _chave_alfabetica(nome) -> tuple:
    """Ordena como um humano procura: sem caixa, sem acento e ignorando
    pontuacao inicial ($TOKEN fica junto de TOKEN)."""
    texto = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore")
    limpo = texto.decode().lower().lstrip("$#@._- ")
    # Nome que comeca com digito vai para o fim, como em indice de livro.
    return (1 if limpo[:1].isdigit() else 0, limpo)


def codigos_repetidos(projetos: list[dict]) -> set:
    """Codigos de moeda usados por MAIS DE UM emissor.

    Isto e uma questao de seguranca, nao de estetica. Ha dois RLUSD nesta
    lista: o da Ripple, com 72 mil detentores, e outro com 241, de emissor
    diferente. Uma pagina que diz "alive" ao lado de um nome desses pode ser
    lida como aval - e emprestar credibilidade a uma imitacao de stablecoin
    machuca quem le, nao o projeto listado.
    """
    por_codigo = {}
    for p in projetos:
        codigo = (p.get("moeda") or "").upper()
        if not codigo or not p.get("emissor"):
            continue
        por_codigo.setdefault(codigo, set()).add(p["emissor"])
    return {c for c, emissores in por_codigo.items() if len(emissores) > 1}


def linha(p: dict, repetidos: set = frozenset()) -> str:
    e = html.escape
    nome = e(str(p.get("nome", "?")))
    site = p.get("site") or ""
    if site and not site.startswith("http"):
        site = "https://" + site
    titulo = f'<a href="{e(site)}" rel="nofollow noopener">{nome}</a>' if site else nome

    # Identificacao. O endereco do emissor e o unico nome que nao mente: metade
    # dos tokens da XRPL nao publica nome nenhum e aparece aqui pelo codigo da
    # moeda, que ninguem reconhece. Quem procura o proprio projeto procura pelo
    # endereco.
    ident = []
    if p.get("emissor"):
        # O endereco vira link para o explorador da propria XRPL Foundation.
        # Escolha deliberada: Bithomp e XRPSCAN sao os exploradores mais usados,
        # mas os dois ESTAO nesta lista sendo julgados - mandar trafego para um
        # deles pareceria favor, e favor de quem julga e pior que jargao.
        ident.append(
            f'<a href="{EXPLORADOR}{e(p["emissor"])}" rel="nofollow noopener" '
            f'title="Open this account on the XRPL Foundation explorer">'
            f'{e(p["emissor"])}</a>'
        )
    dominio = (p.get("site") or "").replace("https://", "").replace("http://", "").strip("/")
    if dominio and dominio.lower() not in nome.lower():
        ident.append(e(dominio))

    # X: link direto quando o projeto publicou o perfil no proprio cadastro da
    # rede; busca quando nao publicou. Nunca um palpite de handle - perfil
    # errado ao lado de um projeto marcado como morto e pior que nenhum.
    perfil = p.get("x") or ""
    if perfil:
        arroba = perfil.rstrip("/").rsplit("/", 1)[-1]
        ident.append(
            f'<a href="{e(perfil)}" rel="nofollow noopener" '
            f'title="Profile the project itself published">@{e(arroba)}</a>'
        )
    else:
        termo = urllib.parse.quote(f'{p.get("nome","")} XRPL')
        ident.append(
            f'<a href="https://x.com/search?q={termo}" rel="nofollow noopener" '
            f'title="No profile published - search X for this name">search X</a>'
        )

    metricas = []
    if p.get("holders"):
        metricas.append(f'{_fmt(p["holders"])} holders')
    if p.get("tx_janela") is not None:
        # Com o teto de paginacao a contagem e um piso, nao um total.
        mais = "+" if p.get("tx_truncado") else ""
        metricas.append(f'{_fmt(p["tx_janela"])}{mais} tx/30d')
    dias_quieto = p.get("dias_sem_atividade")
    # "0d parado" num projeto ativo era leitura confusa, e "parado" colide com
    # o nome de uma das situacoes. So vale dizer quando ha silencio de fato.
    if isinstance(dias_quieto, int) and dias_quieto >= 1:
        metricas.append(f'quiet {dias_quieto}d')
    v = p.get("variacao_holders")
    if isinstance(v, (int, float)) and abs(v) >= 0.1:
        classe = "sobe" if v >= 0 else "desce"
        janela = p.get("dias_variacao")
        # A janela vai no proprio texto, nao so no title: um numero sem ela e
        # enganoso quando dois projetos de cadencia diferente aparecem lado a
        # lado (topo medido todo dia, cauda a cada 15) - sem isso, +18% de um
        # projeto quieto ha duas semanas parece o mesmo tipo de movimento que
        # +2% de um projeto medido ontem.
        sufixo = f' over {janela}d' if isinstance(janela, int) else ''
        metricas.append(
            f'<span class="{classe}" title="Change in holders since this '
            f'project\'s own previous measurement, not a fixed calendar week">'
            f'{v:+.1f}% holders{sufixo}</span>'
        )

    medido = (p.get("medido_em") or "")[:10]
    if medido:
        try:
            dias = (dt.date.today() - dt.date.fromisoformat(medido)).days
        except ValueError:
            dias = None
        if dias is not None:
            quando = "measured today" if dias == 0 else (
                "measured yesterday" if dias == 1 else f"measured {dias}d ago"
            )
            metricas.append(f'<span class="quando">{quando}</span>')

    pedir = ""
    if REPO:
        alvo = urllib.parse.quote(str(p.get("nome", "")))
        pedir = (
            f' <a class="pedir" href="{html.escape(REPO)}/issues/new?'
            f'template=revalidar.yml&title=Recheck:+{alvo}">recheck</a>'
        )

    # Tudo que a busca deve encontrar, num atributo so: nome, codigo, endereco,
    # dominio e categoria.
    busca = " ".join(
        str(x).lower()
        for x in (
            p.get("nome"), p.get("moeda"), p.get("moeda_hex"), p.get("emissor"),
            dominio, p.get("categoria"),
        )
        if x
    )

    codigo = (p.get("moeda") or "").upper()
    aviso = ""
    if codigo in repetidos:
        aviso = (
            f' <span class="colisao" title="More than one issuer uses the code '
            f'{e(codigo)}. Check the address before trusting the name.">'
            f'shared code</span>'
        )

    situacao = e(p.get("situacao", "indeterminado"))
    return f"""      <article class="linha {situacao}" data-s="{situacao}" data-b="{e(busca)}">
        <div class="nome"><span class="ponto"></span>{titulo}{aviso}</div>
        <div class="motivo">{e(str(p.get('motivo','')))}{pedir}</div>
        <div class="id">{' · '.join(ident) if ident else '&nbsp;'}</div>
        <div class="metricas">{' · '.join(metricas) if metricas else '&nbsp;'}<span class="cat">{e(str(p.get('categoria','')))}</span></div>
      </article>"""


def gerar(dados: dict) -> str:
    gerado = dados.get("gerado_em", "")
    try:
        quando = dt.datetime.fromisoformat(gerado).strftime("%d/%m/%Y as %H:%M UTC")
    except (ValueError, TypeError):
        quando = gerado or "-"

    contagem = dados.get("contagem", {})
    placar = "".join(
        f'<button class="selo" data-f="{k}" aria-pressed="false">'
        f'<span class="ponto {k}"></span><b>{contagem.get(k,0)}</b> '
        f'{SITUACOES[k][0].lower()}</button>'
        for k in ("ativo", "morrendo", "parado", "morto", "indeterminado")
        if contagem.get(k)
    )

    repetidos = codigos_repetidos(dados["projetos"])

    grupos = []
    for chave in ("ativo", "morrendo", "parado", "morto", "indeterminado"):
        do_grupo = [p for p in dados["projetos"] if p.get("situacao") == chave]
        if not do_grupo:
            continue
        # Alfabetica, nao por detentores: quem abre a pagina esta procurando um
        # nome, nao conferindo um ranking. Sem acento e sem caixa para o "$" e o
        # "x" minusculo nao caIrem longe de onde o olho procura.
        do_grupo.sort(key=lambda p: _chave_alfabetica(p.get("nome")))
        titulo, sub = SITUACOES[chave]
        grupos.append(
            f"""    <section class="grupo" data-grupo="{chave}">
      <div class="cabeca"><h2>{titulo} <span class="conta" data-conta="{chave}">({len(do_grupo)})</span></h2><p>{sub}</p></div>
      <div class="lista">
{chr(10).join(linha(p, repetidos) for p in do_grupo)}
      </div>
      <p class="vazio" hidden>No project in this group matches the search.</p>
    </section>"""
        )

    total = dados.get("total", 0)

    # O escopo sai do proprio dado, nunca de um numero escrito a mao: enquanto o
    # rodizio nao cobre a cauda inteira, o piso real e mais alto que a meta, e
    # anunciar a meta como se fosse o presente seria prometer cobertura que a
    # pagina nao tem. Quem procura um projeto e nao acha precisa saber se ele
    # esta fora do recorte ou se o robo nao chegou nele ainda.
    detentores = [
        p["holders"] for p in dados["projetos"]
        if p.get("categoria") == "Token" and isinstance(p.get("holders"), int)
    ]
    piso_real = min(detentores) if detentores else 0
    meta = dados.get("piso_pretendido", 100)
    sem_token = sum(1 for p in dados["projetos"] if p.get("categoria") != "Token")
    escopo = (
        f"Scope: the {len(detentores)} XRP Ledger tokens with the most holders — "
        f"today everything above <b>{piso_real:,} holders</b>"
    )
    if piso_real > meta:
        escopo += (
            f", on the way to <b>{meta}</b> as the rotation reaches further down "
            "the catalogue"
        )
    escopo += (
        f" — plus {sem_token} wallets, explorers and tools that issue no token. "
        "Below a hundred holders the catalogue is mostly dust and abandoned "
        "tests that were never anyone's project, and calling those dead informs "
        "nobody. Institutional real-world-asset tokens — tokenized funds, "
        "private credit, securitized debt — are excluded for a different "
        "reason: most exist for a handful of counterparties by design, not by "
        "neglect, so a holder-count floor will never reach them, and a "
        "redemption-promise rubric does not fit them either. "
        "<b>A project missing from this list is not a project we called "
        "dead.</b>"
    )

    lim = dados.get("limiares", {})
    ciclo = dados.get("ciclo_dias", 15)

    # Canal de contestacao. Chamar projeto dos outros de morto sem oferecer
    # como reclamar e o jeito mais rapido de perder a comunidade. Preencha
    # REPO (ou a variavel de ambiente STILLALIVE_REPO) antes de publicar.
    if REPO:
        contestacao = (
            f'<a href="{html.escape(REPO)}/issues/new">Open an issue</a> and tell me.'
        )
        contestacao_curta = f'<a href="{html.escape(REPO)}/issues">dispute a call</a>'
    else:
        contestacao = "Open an issue in the repository."
        contestacao_curta = "no dispute channel configured"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Still Alive — which XRPL projects are still running</title>
<meta name="description" content="The real state of XRP Ledger projects, measured on-ledger and updated daily.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=IBM+Plex+Mono:wght@400;500&family=Source+Sans+3:wght@400;600&display=swap">
<style>{CSS}
.quando{{opacity:.65;font-style:italic}}
.pedir{{margin-left:.5em;font-size:.85em;opacity:.6}}
header .sub{{margin:.15em 0 0;font-size:1.05rem;opacity:.75}}</style>
</head>
<body>
<div class="page">
  <header>
    <div class="eyebrow">Updated {html.escape(quando)}</div>
    <h1>Still Alive</h1>
    <p class="sub">Which projects on the XRP Ledger are still running.</p>
    <p class="dek">No directory tells you which projects died. This page measures
    each one's real activity on the ledger and shows the arithmetic. Every row
    carries the date of its own measurement.</p>
    <p class="experimento"><b>This is an experiment.</b> One person and a robot,
    measuring the ledger every day. The method is open and the arithmetic is
    printed next to every call — <a href="#method">read how it works</a> before
    you trust a label. Nobody reviews these rows by hand, there is no promise
    that this keeps running, and a wrong call is a bug, not a verdict:
    {contestacao_curta} and it gets fixed.</p>
    <p class="escopo">{escopo}</p>
  </header>

  <div class="barra">
    <div class="placar">{placar}</div>
    <input id="busca" type="search" autocomplete="off" spellcheck="false"
      placeholder="search by name, currency code, issuer address or domain">
    <span class="conta" id="conta">{total} projects</span>
  </div>

{chr(10).join(grupos)}

  <section class="grupo" id="method">
    <h2>How this is measured</h2>
    <div class="metodo">
      <p>For every project with a token, the robot queries the issuer account on
      a public XRPL node and measures two things: when the last transaction
      happened, and how many happened in the last 30 days. It adds the holder
      count and traded volume, and checks whether the project's website still
      answers.</p>
      <p><strong>Two different questions.</strong> A node returns every
      transaction that <em>touches</em> an account, and most of them are
      strangers: someone opening a trust line, a bot sending dust, an offer
      crossing the book. So we count them separately. The total answers "is the
      token still circulating?"; the subset actually <em>signed by the issuer</em>
      answers "is the team still there?". An abandoned project keeps receiving
      visitors, and the visits are not its own pulse.</p>
      <p><strong>What <code>blackholed</code> means.</strong> An issuer account
      nobody can sign for any more: the master key is disabled, there is no
      regular key, and there is no signer list. On the XRP Ledger this is good
      security practice, not abandonment — it is how an issuer proves it can
      never mint more of the token. So it never counts as death: for these, life
      is judged by the token itself, holders and trading, not by the account.
      An account with the master key disabled but still operated through a
      signer list is <em>not</em> blackholed — it transacts normally and is
      measured like any other.</p>
      <p><strong>What <code>% holders</code> means.</strong> The change in the
      number of holders since this project's own previous measurement — never
      a fixed calendar window shared with other rows. That distinction matters
      because coverage runs on two different clocks: the busiest projects are
      re-measured daily, the rest on a {ciclo}-day rotation. A dormant project
      can sit unchanged in the data for two weeks and then show its whole
      accumulated drift the day its turn comes up — printed here as
      "over 14d", not a sudden weekly move. Always read the window before the
      percentage. It is the only trend line here, and it only exists from a
      project's second measurement onwards. Below 0.1% we do not show it: that
      is noise, not a trend.</p>
      <p><strong>The cut-offs.</strong> Dead above {lim.get('dias_morto','?')}
      days with no transaction; dormant above {lim.get('dias_parado','?')} days
      or fewer than {lim.get('tx_minimo','?')} transactions in the month; alive
      with at least {lim.get('tx_ativo','?')} transactions in the month and
      movement in the last {lim.get('dias_ativo','?')} days. Accusing a project
      of being quiet takes a whole week without trading, never a single quiet
      day. These are arguable choices, and they are printed here on purpose.</p>
      <p><strong>Checking it yourself.</strong> Every issuer address links to
      that account on <code>livenet.xrpl.org</code>, the XRPL Foundation's
      explorer, where you can see the same transactions this page counted. The
      choice of explorer is deliberate: the most popular ones are also
      <em>in this list being judged</em>, and sending them traffic would look
      like a favour from the referee.</p>
      <p><strong>The X link.</strong> When a project published its own X profile
      in its ledger metadata, the row links straight to it. When it did not, the
      row offers a search instead. We never guess a handle: the wrong profile
      next to a project marked dead is worse than no profile at all. Note that
      what happens on X is not measured here and never changes a
      classification — this page only counts what the ledger can prove.</p>
      <p><strong>Finding a project.</strong> Every row shows the issuer address,
      and the search box takes a name, a currency code, an address or a domain
      (press <code>/</code> to jump to it). Half the tokens on the XRP Ledger
      publish no name at all and show up here by their currency code, which
      nobody recognises — the address is the only identifier that does not
      depend on the project having registered somewhere. The counters at the top
      are filters too: click one. Hover a row, or tap it, to see the reasoning.</p>
      <p><strong>Disagree?</strong> Every row has a "recheck" link that runs the
      measurement right now and answers with the numbers. It does not decide
      whether the cut-off is fair — that is a conversation, and you can start it
      in the same place.</p>
      <p>The busiest projects are re-measured every day; the rest rotate on a
      {ciclo}-day cycle, because death is slow and measuring everything daily
      would punish the network's public node to discover almost nothing. That is
      why each row carries the date of its own measurement, instead of the page
      pretending it saw everything today.</p>
      <p>The transaction count has a ceiling: above 2400 in the month it shows a
      <code>+</code>, because the reading stops there. It is a floor, not a
      total.</p>
      <p>A project that is quiet on the ledger may be very much alive off it.
      <strong>Found a mistake? {contestacao}</strong> A live project marked dead
      gets fixed the same day.</p>
    </div>
  </section>

  <section class="grupo" id="disclaimer">
    <h2>Disclaimer</h2>
    <div class="aviso">
      <p><b>This is not financial advice, and it is not an endorsement.</b>
      Nothing here is a recommendation to buy, sell or hold anything.</p>
      <p><b>"Alive" is not a seal of approval.</b> It means one thing only:
      transactions were happening on the ledger within the measured window. It
      says nothing about whether a project is legitimate, competent, solvent,
      compliant or safe. A token can be busily traded and still be a scam — an
      active market is exactly what a pump needs. Read "alive" as a pulse, never
      as a reference.</p>
      <p><b>"Dead" is a statement about measurements, not about people.</b> It
      means the ledger showed no meaningful activity and the website did not
      answer, on the date printed on that row. Teams change direction, migrate
      chains, hand a token over, or deliberately stop issuing — none of that is
      wrongdoing, and none of it is implied here.</p>
      <p><b>Names can be copied; addresses cannot.</b> Anyone may issue a token
      with any three-letter code or label, including one that impersonates a
      well-known one. Where more than one issuer uses the same code, the row is
      marked <span class="colisao">shared code</span> — but the only thing that
      identifies an issuer is its address, which is why every row shows it.
      Never trust a name on this page, or anywhere else, without checking the
      address.</p>
      <p><b>Absence is not an accusation.</b> The scope is stated at the top; a
      project that is not on this list simply was not measured.</p>
      <p>The data comes from public sources that can be wrong, stale or briefly
      unreachable, and the cut-offs are one person's editorial judgement, printed
      above so you can disagree with them. Verify anything that matters to you
      on the ledger yourself — every address here links to an explorer for
      exactly that reason. Do your own research.</p>
    </div>
  </section>

  <footer>
    Not financial advice · not an endorsement · "alive" measures on-ledger
    activity only<br>
    {dados.get('total', 0)} projects observed · <a href="#method">method</a> ·
    <a href="#disclaimer">disclaimer</a> · raw data in
    <a href="dados.json">dados.json</a> · {contestacao_curta} · made by a human
    with a robot
  </footer>
</div>
{JS}
</body>
</html>
"""


def main() -> None:
    if not REPO:
        print(
            "! REPO vazio: a pagina sai sem canal de contestacao. Defina REPO em "
            "gerar_site.py ou STILLALIVE_REPO no ambiente antes de publicar.",
            file=sys.stderr,
        )
    # Argumento opcional para inspecionar dados de teste sem tocar na coleta real.
    origem = sys.argv[1] if len(sys.argv) > 1 else "dados.json"
    with open(origem, encoding="utf-8") as f:
        dados = json.load(f)
    os.makedirs("site", exist_ok=True)
    with open("site/index.html", "w", encoding="utf-8") as f:
        f.write(gerar(dados))
    with open("site/dados.json", "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    print(f"site/index.html escrito a partir de {origem} ({dados.get('total', 0)} projetos).")


if __name__ == "__main__":
    main()
