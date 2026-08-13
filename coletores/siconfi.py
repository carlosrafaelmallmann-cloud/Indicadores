"""Coletor do SICONFI — API de dados abertos da Secretaria do Tesouro Nacional.

Base: https://apidatalake.tesouro.gov.br/ords/siconfi/tt/
Sem autenticação. Respostas no formato {"items": [...], "hasMore": bool}.

Fontes utilizadas:
  • DCA  (Declaração de Contas Anuais) — receita e despesa executadas do exercício
  • RGF  (Relatório de Gestão Fiscal)  — despesa com pessoal em % da RCL

O parser localiza a linha pelo nome da conta, tolerando variações de grafia
entre exercícios; quando não encontra, registra no log as contas disponíveis.
"""
from __future__ import annotations

import logging
from datetime import date

from .comum import (COD_IBGE, Indicador, ResultadoColeta, buscar_json,
                    normalizar, para_numero)

log = logging.getLogger("siconfi")

BASE = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
ANOS_SERIE = 6  # profundidade da série histórica


def _consultar(recurso: str, params: dict) -> list[dict]:
    dados = buscar_json(f"{BASE}/{recurso}", params=params)
    return dados.get("items", []) if isinstance(dados, dict) else []


def _linha(itens: list[dict], conta_trecho: str, coluna_trecho: str | None = None) -> dict | None:
    alvo_conta = normalizar(conta_trecho)
    alvo_coluna = normalizar(coluna_trecho) if coluna_trecho else None
    for item in itens:
        if alvo_conta not in normalizar(item.get("conta", "")):
            continue
        if alvo_coluna and alvo_coluna not in normalizar(item.get("coluna", "")):
            continue
        return item
    return None


def _serie_dca(anexo: str, conta: str, coluna: str, ate: int) -> list[dict]:
    serie = []
    for ano in range(ate - ANOS_SERIE + 1, ate + 1):
        try:
            itens = _consultar("dca", {
                "an_exercicio": ano,
                "no_anexo": anexo,
                "id_ente": COD_IBGE,
            })
            if not itens:
                continue
            linha = _linha(itens, conta, coluna)
            if linha is None:
                log.warning("DCA %d/%s: conta '%s' não localizada. Amostra: %s",
                            ano, anexo, conta,
                            sorted({i.get("conta", "") for i in itens})[:8])
                continue
            valor = para_numero(linha.get("valor"))
            if valor is not None:
                serie.append({"periodo": str(ano), "valor": valor})
        except Exception as erro:  # noqa: BLE001
            log.warning("DCA %d/%s indisponível: %s", ano, anexo, erro)
    return serie


def _despesa_pessoal(ate: int) -> list[dict]:
    """RGF Anexo 01 — Demonstrativo da Despesa com Pessoal, Poder Executivo,
    3º quadrimestre. Retorna o percentual sobre a Receita Corrente Líquida."""
    serie = []
    for ano in range(ate - ANOS_SERIE + 1, ate + 1):
        try:
            itens = _consultar("rgf", {
                "an_exercicio": ano,
                "nr_periodo": 3,
                "co_tipo_demonstrativo": "RGF",
                "no_anexo": "RGF-Anexo 01",
                "co_poder": "E",
                "id_ente": COD_IBGE,
            })
            if not itens:
                continue
            linha = (_linha(itens, "despesa total com pessoal", "% sobre a rcl")
                     or _linha(itens, "despesa total com pessoal para fins de apuracao", "%"))
            if linha is None:
                log.warning("RGF %d: linha de despesa com pessoal não localizada", ano)
                continue
            valor = para_numero(linha.get("valor"))
            if valor is not None:
                serie.append({"periodo": str(ano), "valor": valor})
        except Exception as erro:  # noqa: BLE001
            log.warning("RGF %d indisponível: %s", ano, erro)
    return serie


def coletar() -> ResultadoColeta:
    # A DCA de um exercício só é homologada no ano seguinte.
    ate = date.today().year - 1
    indicadores: list[Indicador] = []
    falhas: list[str] = []

    blocos = [
        ("siconfi_receita_total", "Receita orçamentária total",
         "DCA-Anexo I-C", "Receitas Correntes", "Receitas Brutas Realizadas",
         "https://siconfi.tesouro.gov.br/siconfi/pages/public/consulta_finbra/finbra_list.jsf"),
        ("siconfi_despesa_total", "Despesa orçamentária empenhada",
         "DCA-Anexo I-D", "Despesas Correntes", "Despesas Empenhadas",
         "https://siconfi.tesouro.gov.br/siconfi/pages/public/consulta_finbra/finbra_list.jsf"),
    ]

    for ident, rotulo, anexo, conta, coluna, url in blocos:
        serie = _serie_dca(anexo, conta, coluna, ate)
        if not serie:
            falhas.append(rotulo)
            continue
        ultimo = serie[-1]
        indicadores.append(Indicador(
            id=ident,
            categoria="Finanças públicas",
            indicador=rotulo,
            valor=ultimo["valor"],
            unidade="R$",
            periodo=ultimo["periodo"],
            fonte="SICONFI / Tesouro Nacional",
            fonte_detalhe=f"{anexo} — {conta} ({coluna})",
            url=url,
            formato="moeda",
            serie=serie,
        ))
        log.info("%s = %s (%s)", rotulo, ultimo["valor"], ultimo["periodo"])

    serie_pessoal = _despesa_pessoal(ate)
    if serie_pessoal:
        ultimo = serie_pessoal[-1]
        indicadores.append(Indicador(
            id="siconfi_despesa_pessoal_rcl",
            categoria="Finanças públicas",
            indicador="Despesa com pessoal sobre a RCL",
            valor=ultimo["valor"],
            unidade="%",
            periodo=ultimo["periodo"],
            fonte="SICONFI / Tesouro Nacional",
            fonte_detalhe="RGF-Anexo 01 — Poder Executivo, 3º quadrimestre",
            url="https://siconfi.tesouro.gov.br/siconfi/pages/public/consulta_rgf/consulta_rgf_list.jsf",
            formato="percentual",
            serie=serie_pessoal,
            observacao="Limite prudencial de 51,30% e limite máximo de 54,00% "
                       "sobre a Receita Corrente Líquida, conforme os artigos 20, "
                       "III, 'b', e 22, parágrafo único, da Lei Complementar "
                       "nº 101/2000 (Lei de Responsabilidade Fiscal).",
        ))
    else:
        falhas.append("Despesa com pessoal sobre a RCL")

    if not indicadores:
        status, mensagem = "falha", "nenhum dado obtido do SICONFI"
    elif falhas:
        status, mensagem = "parcial", "não obtidos: " + ", ".join(falhas)
    else:
        status, mensagem = "ok", f"{len(indicadores)} indicadores"

    return ResultadoColeta(fonte="SICONFI", status=status, mensagem=mensagem,
                           indicadores=indicadores)
