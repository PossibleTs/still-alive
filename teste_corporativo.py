#!/usr/bin/env python3
"""
Teste da classificacao de projetos sem token, sem tocar na rede.
Numeros e estados aqui sao INVENTADOS - servem para exercitar a logica.

    python teste_corporativo.py
"""

from descoberta import classificar_corporativo

CASOS = [
    ("infra com identidade verificada", {
        "nome": "Provedor de oraculo", "categoria": "Infraestrutura",
        "tem_toml": True, "toml_vencido": False, "verificacao": "mao dupla",
        "papeis": ["Provedor de oraculo"], "site_ok": True}),
    ("emissor institucional de MPT", {
        "nome": "Gestora tokenizada", "categoria": "RWA",
        "tem_toml": True, "toml_vencido": False, "verificacao": "mao dupla",
        "papeis": ["Emissor de MPT / RWA", "Cofre tokenizado"], "site_ok": True}),
    ("toml vencido", {
        "nome": "Empresa desatenta", "categoria": "Infraestrutura",
        "tem_toml": True, "toml_vencido": True, "verificacao": "mao dupla",
        "papeis": [], "site_ok": True}),
    ("toml sem confirmacao da conta", {
        "nome": "So promessa", "categoria": "Pagamentos",
        "tem_toml": True, "toml_vencido": False, "verificacao": "so o dominio afirma",
        "papeis": [], "site_ok": True}),
    ("sem toml mas operando ponte", {
        "nome": "Ponte discreta", "categoria": "Interoperabilidade",
        "tem_toml": False, "papeis": ["Operador de ponte"], "site_ok": True}),
    ("no publico respondendo", {
        "nome": "Operador de no", "categoria": "Infraestrutura",
        "tem_toml": False, "papeis": [], "servidor_publico_ok": True, "site_ok": True}),
    ("biblioteca arquivada", {
        "nome": "SDK abandonado", "categoria": "Ferramenta",
        "tem_toml": False, "papeis": [], "site_ok": True,
        "github": {"arquivado": True, "ultimo_push": "2023-02-11T00:00:00Z"}}),
    ("site no ar e nada mais", {
        "nome": "Landing page eterna", "categoria": "Pagamentos",
        "tem_toml": False, "papeis": [], "site_ok": True}),
    ("sumiu de vez", {
        "nome": "Startup encerrada", "categoria": "Pagamentos",
        "tem_toml": False, "papeis": [], "site_ok": False}),
]


def main() -> None:
    print("Classificacao de projetos sem token:\n")
    larguras = max(len(d) for d, _ in CASOS)
    for descricao, p in CASOS:
        situacao, motivo = classificar_corporativo(p)
        print(f"  {situacao:14} <- {descricao:{larguras}}")
        print(f"                  {motivo}\n")


if __name__ == "__main__":
    main()
