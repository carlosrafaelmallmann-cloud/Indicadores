"""Indicadores sem API pública, mantidos em dados/manuais.csv.

O arquivo é editável pela interface web do GitHub: cada alteração vira um
commit assinado, datado e reversível — o que substitui, com vantagem, um
painel administrativo protegido por senha.

Séries históricas: basta repetir o mesmo `id` com períodos diferentes. O
registro de período mais recente vira o valor em destaque; os demais compõem
a série do gráfico.
"""
from __future__ import annotations

import csv
import logging

from .comum import DIR_DADOS, Indicador, ResultadoColeta, para_numero

log = logging.getLogger("manuais")

ARQUIVO = DIR_DADOS / "manuais.csv"
COLUNAS = ["id", "categoria", "indicador", "valor", "unidade", "periodo",
           "fonte", "fonte_detalhe", "url", "formato", "observacao"]


def coletar() -> ResultadoColeta:
    if not ARQUIVO.exists():
        return ResultadoColeta(fonte="Entrada manual", status="falha",
                               mensagem="dados/manuais.csv não encontrado")

    agrupados: dict[str, list[dict]] = {}
    descartadas = 0

    with ARQUIVO.open(encoding="utf-8-sig", newline="") as arquivo:
        for numero, linha in enumerate(csv.DictReader(arquivo), start=2):
            ident = (linha.get("id") or "").strip()
            valor = para_numero(linha.get("valor"))
            if not ident or valor is None:
                if any((linha.get(c) or "").strip() for c in COLUNAS):
                    log.warning("linha %d ignorada (id ou valor ausente)", numero)
                    descartadas += 1
                continue
            linha["_valor"] = valor
            agrupados.setdefault(ident, []).append(linha)

    indicadores: list[Indicador] = []
    for ident, linhas in agrupados.items():
        linhas.sort(key=lambda l: str(l.get("periodo", "")))
        serie = [{"periodo": str(l.get("periodo", "")), "valor": l["_valor"]}
                 for l in linhas]
        atual = linhas[-1]
        indicadores.append(Indicador(
            id=ident,
            categoria=(atual.get("categoria") or "Outros").strip(),
            indicador=(atual.get("indicador") or ident).strip(),
            valor=atual["_valor"],
            unidade=(atual.get("unidade") or "").strip(),
            periodo=str(atual.get("periodo", "")).strip(),
            fonte=(atual.get("fonte") or "Entrada manual").strip(),
            fonte_detalhe=(atual.get("fonte_detalhe") or "").strip(),
            url=(atual.get("url") or "").strip(),
            origem="manual",
            formato=(atual.get("formato") or "numero").strip(),
            serie=serie if len(serie) > 1 else [],
            observacao=(atual.get("observacao") or "").strip(),
        ))

    if not indicadores:
        return ResultadoColeta(fonte="Entrada manual", status="falha",
                               mensagem="nenhuma linha válida em manuais.csv")

    mensagem = f"{len(indicadores)} indicadores"
    if descartadas:
        mensagem += f"; {descartadas} linha(s) descartada(s)"
    return ResultadoColeta(fonte="Entrada manual", status="ok",
                           mensagem=mensagem, indicadores=indicadores)
