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

SITUACOES = {
    "ativo": ("Ativo", "Transacionando na rede agora."),
    "morrendo": ("Morrendo", "Ainda respira, mas o movimento caiu."),
    "parado": ("Parado", "Sem atividade relevante ha meses."),
    "morto": ("Morto", "Sem sinal de vida e sem site no ar."),
    "indeterminado": ("Indeterminado", "Nao foi possivel medir com confianca."),
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
    conta.textContent = visiveis + (visiveis === 1 ? ' projeto' : ' projetos');
  }

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
  --ground:#F1F4F3;--surface:#FFF;--sunken:#E7ECEA;--ink:#121A1C;--muted:#59696B;
  --rule:#D3DBD9;--accent:#0F6E5C;--amber:#96601A;--red:#9B3A2E;--slate:#6B7A7C;
  --violeta:#5B4B8A;
  --serif:"Fraunces",Georgia,serif;--sans:"Source Sans 3",system-ui,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0D1416;--surface:#141D1F;--sunken:#101819;--ink:#E4EBE9;--muted:#93A4A3;
  --rule:#263133;--accent:#58C3A6;--amber:#D6A660;--red:#E0806F;--slate:#8D9C9E;
  --violeta:#A99BD6;
}}
:root[data-theme="dark"]{
  --ground:#0D1416;--surface:#141D1F;--sunken:#101819;--ink:#E4EBE9;--muted:#93A4A3;
  --rule:#263133;--accent:#58C3A6;--amber:#D6A660;--red:#E0806F;--slate:#8D9C9E;
  --violeta:#A99BD6;
}
*{box-sizing:border-box}
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
.selo b{font-weight:600;color:inherit}
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
.ativo .ponto{background:var(--accent)}
.morrendo .ponto{background:var(--amber)}
.parado .ponto{background:var(--slate)}
.morto .ponto{background:var(--red)}
.indeterminado .ponto{background:var(--violeta)}
.linha .motivo{font-size:.83rem;color:var(--muted);grid-column:2}
.linha .id{font-family:var(--mono);font-size:.68rem;color:var(--muted);
  grid-column:1;overflow-wrap:anywhere}
.linha .metricas{font-family:var(--mono);font-size:.7rem;color:var(--muted);
  font-variant-numeric:tabular-nums;display:flex;flex-wrap:wrap;gap:.6rem;grid-column:2}
.cat{font-family:var(--mono);font-size:.62rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:.06em;white-space:nowrap}
.sobe{color:var(--accent)}.desce{color:var(--red)}
.quando{opacity:.7;font-style:italic}
.pedir{margin-left:.5em;font-size:.95em;opacity:.6}
.linha a{color:inherit;text-decoration:none;border-bottom:1px solid var(--rule)}
.linha a:hover{border-bottom-color:currentColor}
a:focus-visible,#busca:focus-visible,.selo:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.vazio{color:var(--muted);font-size:.9rem;padding:.6rem 0}
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


def linha(p: dict) -> str:
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
        ident.append(e(p["emissor"]))
    dominio = (p.get("site") or "").replace("https://", "").replace("http://", "").strip("/")
    if dominio and dominio.lower() not in nome.lower():
        ident.append(e(dominio))

    metricas = []
    if p.get("holders"):
        metricas.append(f'{_fmt(p["holders"])} detentores')
    if p.get("tx_janela") is not None:
        # Com o teto de paginacao a contagem e um piso, nao um total.
        mais = "+" if p.get("tx_truncado") else ""
        metricas.append(f'{_fmt(p["tx_janela"])}{mais} tx/30d')
    dias_quieto = p.get("dias_sem_atividade")
    # "0d parado" num projeto ativo era leitura confusa, e "parado" colide com
    # o nome de uma das situacoes. So vale dizer quando ha silencio de fato.
    if isinstance(dias_quieto, int) and dias_quieto >= 1:
        metricas.append(f'quieto ha {dias_quieto}d')
    v = p.get("variacao_holders")
    if isinstance(v, (int, float)) and abs(v) >= 0.1:
        classe = "sobe" if v >= 0 else "desce"
        metricas.append(f'<span class="{classe}">{v:+.1f}% detentores</span>')

    medido = (p.get("medido_em") or "")[:10]
    if medido:
        try:
            dias = (dt.date.today() - dt.date.fromisoformat(medido)).days
        except ValueError:
            dias = None
        if dias is not None:
            quando = "medido hoje" if dias == 0 else (
                "medido ontem" if dias == 1 else f"medido ha {dias} dias"
            )
            metricas.append(f'<span class="quando">{quando}</span>')

    pedir = ""
    if REPO:
        alvo = urllib.parse.quote(str(p.get("nome", "")))
        pedir = (
            f' <a class="pedir" href="{html.escape(REPO)}/issues/new?'
            f'template=revalidar.yml&title=Revalidar:+{alvo}">medir de novo</a>'
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

    situacao = e(p.get("situacao", "indeterminado"))
    return f"""      <article class="linha {situacao}" data-s="{situacao}" data-b="{e(busca)}">
        <div class="nome"><span class="ponto"></span>{titulo}</div>
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
{chr(10).join(linha(p) for p in do_grupo)}
      </div>
      <p class="vazio" hidden>Nenhum projeto deste grupo bate com a busca.</p>
    </section>"""
        )

    total = dados.get("total", 0)
    lim = dados.get("limiares", {})
    ciclo = dados.get("ciclo_dias", 15)

    # Canal de contestacao. Chamar projeto dos outros de morto sem oferecer
    # como reclamar e o jeito mais rapido de perder a comunidade. Preencha
    # REPO (ou a variavel de ambiente STILLALIVE_REPO) antes de publicar.
    if REPO:
        contestacao = (
            f'<a href="{html.escape(REPO)}/issues/new">Abra uma issue</a> e me diga.'
        )
        contestacao_curta = f'<a href="{html.escape(REPO)}/issues">contestar</a>'
    else:
        contestacao = "Abra uma issue no repositorio."
        contestacao_curta = "sem canal de contestacao configurado"

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Still Alive — quem ainda esta vivo na XRPL</title>
<meta name="description" content="Situacao real dos projetos da XRP Ledger, medida na rede e atualizada todo dia.">
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
    <div class="eyebrow">Atualizado em {html.escape(quando)}</div>
    <h1>Still Alive</h1>
    <p class="sub">Quem ainda esta vivo na XRP Ledger.</p>
    <p class="dek">Diretorio nenhum diz quais projetos morreram. Esta pagina mede
    a atividade real de cada um na rede e mostra a conta. Cada cartao diz de
    quando e a sua medicao.</p>
  </header>

  <div class="barra">
    <div class="placar">{placar}</div>
    <input id="busca" type="search" autocomplete="off" spellcheck="false"
      placeholder="buscar por nome, codigo, endereco do emissor ou dominio">
    <span class="conta" id="conta">{total} projetos</span>
  </div>

{chr(10).join(grupos)}

  <section class="grupo">
    <h2>Como isto e medido</h2>
    <div class="metodo">
      <p>Para cada projeto com token, o robo consulta a conta do emissor num no
      publico da XRPL e mede duas coisas: quando foi a ultima transacao e quantas
      aconteceram nos ultimos 30 dias. Junta a isso o numero de detentores e o
      volume negociado, e checa se o site do projeto ainda responde.</p>
      <p>Emissor <code>blackholed</code> — aquele em que ninguem consegue mais
      assinar: chave mestra desabilitada, sem chave regular e sem lista de
      signatarios — nao conta como abandono. E boa pratica de seguranca, e nesse
      caso a vida do projeto e julgada pelo token, detentores e negociacao, nao
      pela conta emissora. Conta com a mestra desabilitada mas ainda operada por
      lista de signatarios <em>nao</em> entra aqui: essa transaciona normalmente
      e e medida como qualquer outra.</p>
      <p>Os cortes usados: morto acima de {lim.get('dias_morto','?')} dias sem
      transacao, parado acima de {lim.get('dias_parado','?')} dias ou menos de
      {lim.get('tx_minimo','?')} transacoes no mes, ativo com pelo menos
      {lim.get('tx_ativo','?')} transacoes no mes e movimento nos ultimos
      {lim.get('dias_ativo','?')} dias. Sao escolhas discutiveis, e de proposito
      estao expostas aqui.</p>
      <p>Cada linha mostra o endereco do emissor, e a busca no alto aceita nome,
      codigo da moeda, endereco ou dominio (a tecla <code>/</code> pula para
      ela). Isso porque metade dos tokens da XRP Ledger nao publica nome nenhum
      e aparece aqui pelo codigo da moeda, que ninguem reconhece - o endereco e
      o unico identificador que nao depende de o projeto ter se cadastrado em
      algum lugar. Os contadores no alto tambem filtram: clique num deles.</p>
      <p>Discorda de alguma classificacao? Cada cartao tem um "medir de novo"
      que roda a medicao na hora e responde com o numero. Ele nao decide se o
      corte e justo - isso e conversa, e da para puxar no mesmo lugar.</p>
      <p>Os projetos mais movimentados sao remedidos todo dia; o restante entra
      num rodizio de {ciclo} dias, porque morte e lenta e medir tudo diariamente
      seria castigar o no publico da rede para descobrir quase nada. Por isso
      cada cartao carrega a data da propria medicao, em vez de a pagina fingir
      que viu tudo hoje.</p>
      <p>A contagem de transacoes tem teto: acima de 2400 no mes ela aparece com
      um <code>+</code>, porque a leitura para ali. E um piso, nao um total.</p>
      <p>Nada disto e conselho de investimento, e um projeto quieto na rede pode
      estar muito vivo fora dela. <strong>Achou um erro? {contestacao}</strong>
      Correcao de projeto vivo marcado como morto entra no mesmo dia.</p>
    </div>
  </section>

  <footer>
    {dados.get('total', 0)} projetos observados · dados brutos em
    <a href="dados.json">dados.json</a> · {contestacao_curta} · feito por um
    humano com um robo
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
