"""Coletor do IBGE — API de Dados Agregados v3 (SIDRA).

Estratégia: em vez de fixar identificadores de variáveis (que o IBGE altera
entre revisões das pesquisas), o coletor lê os metadados do agregado e
localiza a variável pelo nome. Se o nome mudar, o log mostra as opções
disponíveis, o que torna a manutenção trivial.
"""
from __future__ import annotations

import logging

from .comum import (COD_IBGE, Indicador, ResultadoColeta, buscar_json,
                    normalizar, para_numero)

log = logging.getLogger("ibge")

BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"
LOCALIDADE = f"N6[{COD_IBGE}]"

# agregado, trecho do nome da variável, rótulo no painel, unidade, formato, categoria
ALVOS = [
    (6579, "populacao residente estimada", "População estimada",
     "habitantes", "inteiro", "Demografia"),
    (5938, "produto interno bruto a precos correntes", "PIB a preços correntes",
     "R$ mil", "moeda", "Economia"),
    (5938, "produto interno bruto per capita", "PIB per capita",
     "R$", "moeda", "Economia"),
    (5938, "valor adicionado bruto da industria", "VAB — Indústria",
     "R$ mil", "moeda", "Economia"),
    (5938, "valor adicionado bruto da agropecuaria", "VAB — Agropecuária",
     "R$ mil", "moeda", "Economia"),
    (5938, "valor adicionado bruto dos servicos", "VAB — Serviços",
     "R$ mil", "moeda", "Economia"),
]

PERIODOS = "-12"  # últimos 12 períodos disponíveis, para montar a série


def _variaveis_do_agregado(agregado: int) -> list[dict]:
    dados = buscar_json(f"{BASE}/{agregado}/metadados")
    return dados.get("variaveis", [])


def _localizar(variaveis: list[dict], trecho: str) -> dict | None:
    alvo = normalizar(trecho)
    for var in variaveis:
        if alvo in normalizar(var.get("nome", "")):
            return var
    return None


def _consultar(agregado: int, id_variavel: int) -> list[dict]:
    url = f"{BASE}/{agregado}/periodos/{PERIODOS}/variaveis/{id_variavel}"
    dados = buscar_json(url, params={"localidades": LOCALIDADE})
    if not dados:
        return []
    resultados = dados[0].get("resultados", [])
    if not resultados:
        return []
    series = resultados[0].get("series", [])
    if not series:
        return []
    bruto = series[0].get("serie", {})
    serie = []
    for periodo, valor in sorted(bruto.items()):
        numero = para_numero(valor)
        if numero is not None:
            serie.append({"periodo": periodo, "valor": numero})
    return serie


def coletar() -> ResultadoColeta:
    indicadores: list[Indicador] = []
    falhas: list[str] = []
    cache_metadados: dict[int, list[dict]] = {}

    for agregado, trecho, rotulo, unidade, formato, categoria in ALVOS:
        try:
            if agregado not in cache_metadados:
                cache_metadados[agregado] = _variaveis_do_agregado(agregado)
            variaveis = cache_metadados[agregado]

            variavel = _localizar(variaveis, trecho)
            if variavel is None:
                disponiveis = [v.get("nome") for v in variaveis]
                log.error("variável '%s' não encontrada no agregado %d. Disponíveis: %s",
                          trecho, agregado, disponiveis)
                falhas.append(rotulo)
                continue

            serie = _consultar(agregado, variavel["id"])
            if not serie:
                falhas.append(rotulo)
                log.error("agregado %d / variável %s sem valores para %s",
                          agregado, variavel["id"], COD_IBGE)
                continue

            ultimo = serie[-1]
            indicadores.append(Indicador(
                id=f"ibge_{agregado}_{variavel['id']}",
                categoria=categoria,
                indicador=rotulo,
                valor=ultimo["valor"],
                unidade=variavel.get("unidade") or unidade,
                periodo=ultimo["periodo"],
                fonte="IBGE",
                fonte_detalhe=f"{variavel.get('nome', rotulo)} — agregado {agregado}",
                url=f"https://sidra.ibge.gov.br/tabela/{agregado}",
                formato=formato,
                serie=serie,
            ))
            log.info("%s = %s (%s)", rotulo, ultimo["valor"], ultimo["periodo"])

        except Exception as erro:  # noqa: BLE001
            log.error("erro ao coletar '%s': %s", rotulo, erro)
            falhas.append(rotulo)

    if not indicadores:
        status, mensagem = "falha", "nenhum indicador obtido do IBGE"
    elif falhas:
        status, mensagem = "parcial", "não obtidos: " + ", ".join(falhas)
    else:
        status, mensagem = "ok", f"{len(indicadores)} indicadores"

    return ResultadoColeta(fonte="IBGE", status=status, mensagem=mensagem,
                           indicadores=indicadores)
