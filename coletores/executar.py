"""Orquestrador da coleta.

Executa todos os coletores, mescla o resultado com a publicação anterior
(preservando o último valor válido quando uma fonte está fora do ar) e grava
dados/indicadores.json.

Uso:
    python -m coletores.executar              # todas as fontes
    python -m coletores.executar ibge siconfi # apenas as indicadas

O processo termina com código 0 se ao menos uma fonte respondeu, para que a
publicação não seja interrompida pela indisponibilidade de um órgão. Código 1
apenas quando nenhuma fonte respondeu.
"""
from __future__ import annotations

import json
import logging
import sys

from . import caged, ibge, inep, manuais, siconfi
from .comum import (ARQ_INDICADORES, COD_IBGE, DIR_DADOS, NOME_MUNICIPIO, UF,
                    agora_iso, carregar_anterior)

log = logging.getLogger("executar")

FONTES = {
    "ibge": ibge.coletar,
    "siconfi": siconfi.coletar,
    "caged": caged.coletar,
    "inep": inep.coletar,
    "manuais": manuais.coletar,
}

ORDEM_CATEGORIAS = ["Demografia", "Economia", "Emprego", "Finanças públicas",
                    "Educação", "Saúde", "Segurança", "Infraestrutura", "Outros"]


def principal(selecionadas: list[str]) -> int:
    escolhidas = selecionadas or list(FONTES)
    anterior = carregar_anterior()
    preexistentes = {i["id"]: i for i in anterior.get("indicadores", [])}

    indicadores: dict[str, dict] = {}
    coletas: list[dict] = []
    painel_emprego = anterior.get("emprego")
    painel_educacao = anterior.get("educacao")
    sucessos = 0

    for nome in escolhidas:
        funcao = FONTES.get(nome)
        if funcao is None:
            log.error("fonte desconhecida: %s", nome)
            continue
        log.info("--- coletando: %s ---", nome)
        try:
            resultado = funcao()
        except Exception as erro:  # noqa: BLE001
            log.exception("falha não tratada em %s", nome)
            coletas.append({"fonte": nome, "status": "falha",
                            "mensagem": str(erro), "executado_em": agora_iso()})
            continue

        if resultado.status in {"ok", "parcial"}:
            sucessos += 1
        if getattr(resultado, "painel_emprego", None):
            painel_emprego = resultado.painel_emprego
        if getattr(resultado, "painel_educacao", None):
            painel_educacao = resultado.painel_educacao
        for indicador in resultado.indicadores:
            indicadores[indicador.id] = indicador.dict()
        coletas.append({"fonte": resultado.fonte, "status": resultado.status,
                        "mensagem": resultado.mensagem,
                        "executado_em": resultado.executado_em,
                        "quantidade": len(resultado.indicadores)})
        log.info("%s: %s — %s", resultado.fonte, resultado.status.upper(),
                 resultado.mensagem)

    # Preserva indicadores que existiam e não vieram nesta execução.
    conservados = 0
    for ident, antigo in preexistentes.items():
        if ident not in indicadores:
            antigo["conservado"] = True
            indicadores[ident] = antigo
            conservados += 1
    if conservados:
        log.info("%d indicador(es) preservados da execução anterior", conservados)

    def chave(item: dict) -> tuple:
        categoria = item.get("categoria", "Outros")
        posicao = (ORDEM_CATEGORIAS.index(categoria)
                   if categoria in ORDEM_CATEGORIAS else len(ORDEM_CATEGORIAS))
        return (posicao, item.get("indicador", ""))

    saida = {
        "municipio": {"nome": NOME_MUNICIPIO, "uf": UF, "codigo_ibge": COD_IBGE},
        "gerado_em": agora_iso(),
        "coletas": coletas,
        "emprego": painel_emprego,
        "educacao": painel_educacao,
        "indicadores": sorted(indicadores.values(), key=chave),
    }

    DIR_DADOS.mkdir(parents=True, exist_ok=True)
    ARQ_INDICADORES.write_text(
        json.dumps(saida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info("gravado %s com %d indicadores", ARQ_INDICADORES, len(indicadores))

    return 0 if sucessos else 1


if __name__ == "__main__":
    sys.exit(principal([a.lower() for a in sys.argv[1:]]))
