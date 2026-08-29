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

SITUACOES = {
    "ativo": ("Ativo", "Transacionando na rede agora."),
    "morrendo": ("Morrendo", "Ainda respira, mas o movimento caiu."),
    "parado": ("Parado", "Sem atividade relevante ha meses."),
    "morto": ("Morto", "Sem sinal de vida e sem site no ar."),
    "indeterminado": ("Indeterminado", "Nao foi possivel medir com confianca."),
}

CSS = """
:root{
  --ground:#F1F4F3;--surface:#FFF;--sunken:#E7ECEA;--ink:#121A1C;--muted:#59696B;
  --rule:#D3DBD9;--accent:#0F6E5C;--amber:#96601A;--red:#9B3A2E;--slate:#6B7A7C;
  --serif:"Fraunces",Georgia,serif;--sans:"Source Sans 3",system-ui,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0D1416;--surface:#141D1F;--sunken:#101819;--ink:#E4EBE9;--muted:#93A4A3;
  --rule:#263133;--accent:#58C3A6;--amber:#D6A660;--red:#E0806F;--slate:#8D9C9E;
}}
:root[data-theme="dark"]{
  --ground:#0D1416;--surface:#141D1F;--sunken:#101819;--ink:#E4EBE9;--muted:#93A4A3;
  --rule:#263133;--accent:#58C3A6;--amber:#D6A660;--red:#E0806F;--slate:#8D9C9E;
}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);font-family:var(--sans);
  font-size:17px;line-height:1.6;margin:0;-webkit-font-smoothing:antialiased}
.page{max-width:56rem;margin:0 auto;padding:clamp(2rem,5vw,4rem) clamp(1rem,4vw,2rem) 5rem;
  display:flex;flex-direction:column;gap:2.5rem}
.eyebrow{font-family:var(--mono);font-size:.7rem;letter-spacing:.13em;
  text-transform:uppercase;color:var(--muted)}
h1{font-family:var(--serif);font-weight:600;font-size:clamp(2rem,5vw,2.9rem);
  line-height:1.1;letter-spacing:-.015em;margin:.6rem 0 0;text-wrap:balance}
.dek{color:var(--muted);max-width:34rem;margin:.8rem 0 0;font-size:1.1rem}
h2{font-family:var(--serif);font-weight:600;font-size:1.4rem;margin:0;
  padding-top:1.2rem;border-top:1px solid var(--rule)}
.placar{display:flex;flex-wrap:wrap;gap:.5rem}
.selo{font-family:var(--mono);font-size:.75rem;padding:.35rem .7rem;border-radius:2px;
  border:1px solid var(--rule);background:var(--surface)}
.selo b{font-weight:500}
.grupo{display:flex;flex-direction:column;gap:1rem}
.cabeca{display:flex;align-items:baseline;gap:.7rem;flex-wrap:wrap}
.cabeca p{margin:0;color:var(--muted);font-size:.92rem}
.lista{display:grid;gap:.6rem;grid-template-columns:repeat(auto-fill,minmax(19rem,1fr))}
.card{background:var(--surface);border:1px solid var(--rule);border-left:3px solid var(--slate);
  border-radius:3px;padding:.9rem 1rem;display:flex;flex-direction:column;gap:.3rem}
.card.ativo{border-left-color:var(--accent)}
.card.morrendo{border-left-color:var(--amber)}
.card.parado{border-left-color:var(--slate)}
.card.morto{border-left-color:var(--red)}
.nome{font-weight:600;display:flex;justify-content:space-between;gap:.6rem;align-items:baseline}
.cat{font-family:var(--mono);font-size:.68rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:.06em;white-space:nowrap}
.motivo{font-size:.88rem;color:var(--muted)}
.metricas{font-family:var(--mono);font-size:.74rem;color:var(--muted);
  font-variant-numeric:tabular-nums;display:flex;flex-wrap:wrap;gap:.7rem;margin-top:.15rem}
.sobe{color:var(--accent)}.desce{color:var(--red)}
.card a{color:inherit;text-decoration:none;border-bottom:1px solid var(--rule)}
.card a:hover{border-bottom-color:currentColor}
a:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.metodo{background:var(--surface);border:1px solid var(--rule);border-radius:3px;
  padding:1.2rem 1.4rem;font-size:.93rem}
.metodo p{margin:0 0 .7rem;color:var(--muted);max-width:44rem}
.metodo p:last-child{margin-bottom:0}
.metodo code{font-family:var(--mono);font-size:.85em;background:var(--sunken);
  padding:.1em .35em;border-radius:2px}
footer{border-top:1px solid var(--rule);padding-top:1.2rem;font-size:.85rem;color:var(--muted)}
"""


def _fmt(n) -> str:
    if not isinstance(n, (int, float)):
        return "-"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(int(n))


def card(p: dict) -> str:
    e = html.escape
    nome = e(str(p.get("nome", "?")))
    site = p.get("site") or ""
    if site and not site.startswith("http"):
        site = "https://" + site
    titulo = f'<a href="{e(site)}" rel="nofollow noopener">{nome}</a>' if site else nome

    metricas = []
    if p.get("holders"):
        metricas.append(f'{_fmt(p["holders"])} detentores')
    if p.get("tx_janela") is not None:
        metricas.append(f'{_fmt(p["tx_janela"])} tx/30d')
    if isinstance(p.get("dias_sem_atividade"), int):
        metricas.append(f'{p["dias_sem_atividade"]}d parado')
    v = p.get("variacao_holders")
    if isinstance(v, (int, float)):
        classe = "sobe" if v >= 0 else "desce"
        metricas.append(f'<span class="{classe}">{v:+.1f}% detentores</span>')

    return f"""      <article class="card {e(p.get('situacao','indeterminado'))}">
        <div class="nome">{titulo}<span class="cat">{e(str(p.get('categoria','')))}</span></div>
        <div class="motivo">{e(str(p.get('motivo','')))}</div>
        <div class="metricas">{' · '.join(metricas) if metricas else '&nbsp;'}</div>
      </article>"""


def gerar(dados: dict) -> str:
    gerado = dados.get("gerado_em", "")
    try:
        quando = dt.datetime.fromisoformat(gerado).strftime("%d/%m/%Y as %H:%M UTC")
    except (ValueError, TypeError):
        quando = gerado or "-"

    contagem = dados.get("contagem", {})
    placar = "".join(
        f'<span class="selo"><b>{contagem.get(k,0)}</b> {SITUACOES[k][0].lower()}</span>'
        for k in ("ativo", "morrendo", "parado", "morto", "indeterminado")
        if contagem.get(k)
    )

    grupos = []
    for chave in ("ativo", "morrendo", "parado", "morto", "indeterminado"):
        do_grupo = [p for p in dados["projetos"] if p.get("situacao") == chave]
        if not do_grupo:
            continue
        titulo, sub = SITUACOES[chave]
        grupos.append(
            f"""    <section class="grupo">
      <div class="cabeca"><h2>{titulo} ({len(do_grupo)})</h2><p>{sub}</p></div>
      <div class="lista">
{chr(10).join(card(p) for p in do_grupo)}
      </div>
    </section>"""
        )

    lim = dados.get("limiares", {})

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quem ainda esta vivo na XRPL</title>
<meta name="description" content="Situacao real dos projetos da XRP Ledger, medida na rede e atualizada todo dia.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=IBM+Plex+Mono:wght@400;500&family=Source+Sans+3:wght@400;600&display=swap">
<style>{CSS}</style>
</head>
<body>
<div class="page">
  <header>
    <div class="eyebrow">Atualizado em {html.escape(quando)}</div>
    <h1>Quem ainda esta vivo na XRPL</h1>
    <p class="dek">Diretorio nenhum diz quais projetos morreram. Esta pagina mede
    a atividade real de cada um na rede, todo dia, e mostra a conta.</p>
  </header>

  <div class="placar">{placar}</div>

{chr(10).join(grupos)}

  <section class="grupo">
    <h2>Como isto e medido</h2>
    <div class="metodo">
      <p>Para cada projeto com token, o robo consulta a conta do emissor num no
      publico da XRPL e mede duas coisas: quando foi a ultima transacao e quantas
      aconteceram nos ultimos 30 dias. Junta a isso o numero de detentores e o
      volume negociado, e checa se o site do projeto ainda responde.</p>
      <p>Emissor com a chave mestra desabilitada (<code>blackholed</code>) nao conta
      como abandono: e boa pratica de seguranca, e nesse caso a vida do projeto e
      julgada pelo token — detentores e negociacao — e nao pela conta emissora.</p>
      <p>Os cortes usados: morto acima de {lim.get('dias_morto','?')} dias sem
      transacao, parado acima de {lim.get('dias_parado','?')} dias ou menos de
      {lim.get('tx_minimo','?')} transacoes no mes, ativo com pelo menos
      {lim.get('tx_ativo','?')} transacoes no mes e movimento nos ultimos
      {lim.get('dias_ativo','?')} dias. Sao escolhas discutiveis, e de proposito
      estao expostas aqui.</p>
      <p>Nada disto e conselho de investimento, e um projeto quieto na rede pode
      estar muito vivo fora dela. Achou um erro? Abra uma issue no repositorio.</p>
    </div>
  </section>

  <footer>
    {dados.get('total', 0)} projetos observados · dados brutos em
    <a href="dados.json">dados.json</a> · feito por um humano com um robo
  </footer>
</div>
</body>
</html>
"""


def main() -> None:
    with open("dados.json", encoding="utf-8") as f:
        dados = json.load(f)
    os.makedirs("site", exist_ok=True)
    with open("site/index.html", "w", encoding="utf-8") as f:
        f.write(gerar(dados))
    with open("site/dados.json", "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    print(f"site/index.html escrito ({dados.get('total', 0)} projetos).")


if __name__ == "__main__":
    main()
