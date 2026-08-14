"""Coletor do Novo CAGED — microdados oficiais do PDET/Ministério do Trabalho.

Apura, para o município, a partir de janeiro de 2021:

  • saldo, admissões e desligamentos mensais, por setor produtivo;
  • acumulado do ano corrente, mês a mês;
  • acumulado fechado de cada ano anterior;
  • estoque de vínculos ativos, projetado a partir de uma base da RAIS.

Fonte: ftp://ftp.mtps.gov.br/pdet/microdados/NOVO CAGED/
Arquivos .7z com texto delimitado por ';' e codificado em UTF-8.

Cada arquivo mensal cobre o país inteiro, de modo que o coletor mantém o
apurado em dados/caged_serie.csv e baixa apenas as competências ausentes.
O cache é gravado após cada competência: se a execução for interrompida,
o trabalho já feito não se perde.
"""
from __future__ import annotations

import csv
import ftplib
import logging
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .comum import (COD_IBGE_6, DIR_DADOS, Indicador, ResultadoColeta,
                    normalizar, para_numero)

log = logging.getLogger("caged")

SERVIDOR = "ftp.mtps.gov.br"
DIRETORIO = "/pdet/microdados/NOVO CAGED"
CACHE = DIR_DADOS / "caged_serie.csv"
BASE_ESTOQUE = DIR_DADOS / "estoque_base.csv"
TIPOS = ["MOV", "FOR", "EXC"]          # movimentações, fora do prazo, exclusões
ANO_INICIAL = 2021
TOTAL = "Total"

# Agrupamento por seção da CNAE 2.0, conforme os cinco grandes setores do PDET.
SETORES = ["Agropecuária", "Indústria", "Construção", "Comércio", "Serviços"]
SECAO_PARA_SETOR = {
    "A": "Agropecuária",
    "B": "Indústria", "C": "Indústria", "D": "Indústria", "E": "Indústria",
    "F": "Construção",
    "G": "Comércio",
}
for _letra in "HIJKLMNOPQRSTU":
    SECAO_PARA_SETOR[_letra] = "Serviços"

URL_FONTE = ("https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/"
             "estatisticas-trabalho/microdados-rais-e-caged")


@dataclass(frozen=True)
class Competencia:
    ano: int
    mes: int

    @property
    def chave(self) -> str:
        return f"{self.ano}{self.mes:02d}"

    def anterior(self) -> "Competencia":
        return (Competencia(self.ano - 1, 12) if self.mes == 1
                else Competencia(self.ano, self.mes - 1))

    def proxima(self) -> "Competencia":
        return (Competencia(self.ano + 1, 1) if self.mes == 12
                else Competencia(self.ano, self.mes + 1))


def _competencias_alvo() -> list[Competencia]:
    """De janeiro de 2021 até a competência mais recente esperada. O CAGED de
    um mês é divulgado com 30 a 45 dias de defasagem."""
    hoje = date.today()
    ultima = Competencia(hoje.year, hoje.month).anterior().anterior()
    lista: list[Competencia] = []
    atual = Competencia(ANO_INICIAL, 1)
    while (atual.ano, atual.mes) <= (ultima.ano, ultima.mes):
        lista.append(atual)
        atual = atual.proxima()
    return lista


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def _ler_cache() -> dict[str, dict[str, dict]]:
    if not CACHE.exists():
        return {}
    dados: dict[str, dict[str, dict]] = defaultdict(dict)
    with CACHE.open(encoding="utf-8", newline="") as arquivo:
        for linha in csv.DictReader(arquivo):
            dados[linha["competencia"]][linha["setor"]] = {
                "admissoes": int(linha["admissoes"]),
                "desligamentos": int(linha["desligamentos"]),
                "saldo": int(linha["saldo"]),
            }
    return dict(dados)


def _gravar_cache(dados: dict[str, dict[str, dict]]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(["competencia", "setor", "admissoes", "desligamentos", "saldo"])
        for chave in sorted(dados):
            for setor in [*SETORES, TOTAL]:
                registro = dados[chave].get(setor)
                if registro:
                    escritor.writerow([chave, setor, registro["admissoes"],
                                       registro["desligamentos"], registro["saldo"]])


# ---------------------------------------------------------------------------
# Leitura dos microdados
# ---------------------------------------------------------------------------
def _baixar(caminho_remoto: str, destino: Path) -> bool:
    try:
        with ftplib.FTP(SERVIDOR, timeout=240) as ftp:
            ftp.login()
            ftp.set_pasv(True)
            with destino.open("wb") as saida:
                ftp.retrbinary(f"RETR {caminho_remoto}", saida.write, blocksize=1 << 20)
        return destino.stat().st_size > 0
    except ftplib.all_errors as erro:
        log.info("indisponível: %s (%s)", caminho_remoto, erro)
        destino.unlink(missing_ok=True)
        return False


def _indice(cabecalho: list[str], *trechos: str) -> int | None:
    for posicao, nome in enumerate(cabecalho):
        rotulo = normalizar(nome.strip().strip('"'))
        if any(trecho in rotulo for trecho in trechos):
            return posicao
    return None


def _apurar(arquivo_7z: Path, acumulador: dict[str, dict[str, int]]) -> None:
    """Soma no acumulador as movimentações do município, por setor.

    'saldomovimentação' vale +1 para admissão e -1 para desligamento; nos
    arquivos de exclusão (EXC) o sinal é invertido.
    """
    import py7zr

    inverter = arquivo_7z.name.upper().startswith("CAGEDEXC")

    with tempfile.TemporaryDirectory() as pasta:
        with py7zr.SevenZipFile(arquivo_7z, mode="r") as pacote:
            pacote.extractall(path=pasta)
        for txt in Path(pasta).rglob("*.txt"):
            with txt.open("r", encoding="utf-8", errors="replace") as fluxo:
                cabecalho = fluxo.readline().rstrip("\n").split(";")
                col_mun = _indice(cabecalho, "munic")
                col_saldo = _indice(cabecalho, "saldo")
                col_secao = _indice(cabecalho, "secao")
                if col_mun is None or col_saldo is None:
                    log.warning("layout inesperado em %s: %s", txt.name, cabecalho[:12])
                    continue
                if col_secao is None:
                    log.warning("coluna de seção CNAE não localizada em %s — "
                                "a abertura setorial ficará incompleta", txt.name)
                for linha in fluxo:
                    campos = linha.split(";")
                    if len(campos) <= max(col_mun, col_saldo):
                        continue
                    if campos[col_mun].strip().strip('"') != COD_IBGE_6:
                        continue
                    try:
                        saldo = int(campos[col_saldo].strip().strip('"'))
                    except ValueError:
                        continue
                    if inverter:
                        saldo = -saldo

                    setor = "Serviços"
                    if col_secao is not None and len(campos) > col_secao:
                        letra = campos[col_secao].strip().strip('"').upper()[:1]
                        setor = SECAO_PARA_SETOR.get(letra, "Serviços")

                    for destino in (setor, TOTAL):
                        registro = acumulador.setdefault(
                            destino, {"admissoes": 0, "desligamentos": 0, "saldo": 0})
                        if saldo > 0:
                            registro["admissoes"] += saldo
                        else:
                            registro["desligamentos"] += -saldo
                        registro["saldo"] += saldo


def _coletar_competencia(comp: Competencia) -> dict[str, dict] | None:
    acumulador: dict[str, dict[str, int]] = {}
    obteve = False
    with tempfile.TemporaryDirectory() as pasta:
        for tipo in TIPOS:
            nome = f"CAGED{tipo}{comp.chave}.7z"
            remoto = f"{DIRETORIO}/{comp.ano}/{comp.chave}/{nome}"
            destino = Path(pasta) / nome
            if not _baixar(remoto, destino):
                continue
            _apurar(destino, acumulador)
            obteve = True
            destino.unlink(missing_ok=True)
    if not obteve:
        return None
    for setor in [*SETORES, TOTAL]:
        acumulador.setdefault(setor, {"admissoes": 0, "desligamentos": 0, "saldo": 0})
    return acumulador


# ---------------------------------------------------------------------------
# Estoque de vínculos
# ---------------------------------------------------------------------------
def _ler_base_estoque() -> tuple[str | None, dict[str, int]]:
    """Lê dados/estoque_base.csv.

    O CAGED registra movimentações, não estoque. A série de estoque é obtida
    ancorando-se numa data-base da RAIS e somando os saldos mensais
    subsequentes — metodologia adotada pelo próprio PDET.
    """
    if not BASE_ESTOQUE.exists():
        return None, {}
    referencia, base = None, {}
    with BASE_ESTOQUE.open(encoding="utf-8-sig", newline="") as arquivo:
        for linha in csv.DictReader(arquivo):
            valor = para_numero(linha.get("estoque"))
            ref = (linha.get("referencia") or "").strip()
            setor = (linha.get("setor") or "").strip()
            if not ref or not setor or valor is None:
                continue
            referencia = ref
            base[setor] = int(valor)
    if not base or not base.get(TOTAL):
        return None, {}
    return referencia, base


def _serie_estoque(cache: dict[str, dict[str, dict]], chaves: list[str]) -> dict:
    referencia, base = _ler_base_estoque()
    if referencia is None:
        return {
            "disponivel": False,
            "observacao": "Para exibir o estoque, informe em dados/estoque_base.csv "
                          "o número de vínculos ativos numa data-base da RAIS. "
                          "O CAGED registra movimentações, não estoque.",
            "pontos": [],
        }

    posteriores = [k for k in chaves if k > referencia]
    corrente = dict(base)
    pontos = []

    for chave in posteriores:
        for setor in [*SETORES, TOTAL]:
            registro = cache[chave].get(setor)
            if registro:
                corrente[setor] = corrente.get(setor, 0) + registro["saldo"]
        if chave.endswith("12"):
            pontos.append({"rotulo": f"Estoque {chave[:4]}",
                           "valor": corrente.get(TOTAL, 0),
                           "setores": {s: corrente.get(s, 0) for s in SETORES}})

    if posteriores and not posteriores[-1].endswith("12"):
        ultimo = posteriores[-1]
        pontos.append({"rotulo": f"Estoque atual ({ultimo[4:]}/{ultimo[:4]})",
                       "valor": corrente.get(TOTAL, 0),
                       "setores": {s: corrente.get(s, 0) for s in SETORES}})

    return {
        "disponivel": bool(pontos),
        "referencia_base": referencia,
        "observacao": f"Vínculos ativos projetados a partir da base declarada em "
                      f"{referencia[4:]}/{referencia[:4]}, acrescida dos saldos "
                      f"mensais do Novo CAGED — metodologia do PDET.",
        "pontos": pontos,
    }


# ---------------------------------------------------------------------------
# Consolidação
# ---------------------------------------------------------------------------
def _consolidar(cache: dict[str, dict[str, dict]], chaves: list[str]) -> dict:
    ano_corrente = int(chaves[-1][:4])
    meses_corrente = [k for k in chaves if k.startswith(str(ano_corrente))]
    anos = sorted({k[:4] for k in chaves})

    linhas_mensais = []
    for setor in [*SETORES, TOTAL]:
        saldos, acumulado, corrida = [], [], 0
        for chave in meses_corrente:
            saldo = cache[chave].get(setor, {}).get("saldo", 0)
            corrida += saldo
            saldos.append(saldo)
            acumulado.append(corrida)
        linhas_mensais.append({"setor": setor, "saldos": saldos,
                               "acumulado": acumulado, "total": corrida})

    linhas_anuais = []
    for setor in [*SETORES, TOTAL]:
        valores = [sum(cache[k].get(setor, {}).get("saldo", 0)
                       for k in chaves if k.startswith(ano)) for ano in anos]
        linhas_anuais.append({"setor": setor, "valores": valores})

    return {
        "atualizado_ate": f"{chaves[-1][4:]}/{chaves[-1][:4]}",
        "setores": [*SETORES, TOTAL],
        "mensal": {"ano": ano_corrente,
                   "meses": [k[4:] for k in meses_corrente],
                   "linhas": linhas_mensais},
        "anual": {"anos": anos, "linhas": linhas_anuais},
        "estoque": _serie_estoque(cache, chaves),
    }


def coletar() -> ResultadoColeta:
    cache = _ler_cache()
    alvos = _competencias_alvo()
    pendentes = [c for c in alvos if c.chave not in cache]

    baixadas, indisponiveis = 0, 0
    for comp in pendentes:
        log.info("buscando competência %s", comp.chave)
        try:
            registro = _coletar_competencia(comp)
        except Exception as erro:  # noqa: BLE001
            log.error("erro na competência %s: %s", comp.chave, erro)
            indisponiveis += 1
            continue
        if registro is None:
            indisponiveis += 1
            continue
        cache[comp.chave] = registro
        baixadas += 1
        _gravar_cache(cache)   # grava a cada mês: interrupção não perde o trabalho
        log.info("%s: saldo total %+d", comp.chave, registro[TOTAL]["saldo"])

    chaves = sorted(cache)
    if not chaves:
        return ResultadoColeta(
            fonte="Novo CAGED", status="falha",
            mensagem="nenhuma competência disponível no servidor do PDET")

    painel = _consolidar(cache, chaves)
    ano = painel["mensal"]["ano"]
    total_mensal = next(l for l in painel["mensal"]["linhas"] if l["setor"] == TOTAL)

    indicadores = [
        Indicador(
            id="caged_saldo_acumulado_ano",
            categoria="Emprego",
            indicador=f"Saldo de empregos acumulado em {ano}",
            valor=total_mensal["total"],
            unidade="vínculos",
            periodo=f"janeiro a {painel['atualizado_ate']}",
            fonte="Novo CAGED / MTE",
            fonte_detalhe="Microdados do PDET — soma dos saldos mensais do exercício",
            url=URL_FONTE,
            formato="inteiro",
            serie=[{"periodo": f"{m}/{ano}", "valor": v}
                   for m, v in zip(painel["mensal"]["meses"], total_mensal["acumulado"])],
            observacao="Acumulado do ano civil, não dos últimos doze meses. Consolida "
                       "movimentações, declarações fora do prazo e exclusões.",
        ),
        Indicador(
            id="caged_saldo_mes",
            categoria="Emprego",
            indicador="Saldo de empregos no mês",
            valor=total_mensal["saldos"][-1],
            unidade="vínculos",
            periodo=painel["atualizado_ate"],
            fonte="Novo CAGED / MTE",
            fonte_detalhe="Microdados do PDET — competência mais recente publicada",
            url=URL_FONTE,
            formato="inteiro",
            serie=[{"periodo": f"{m}/{ano}", "valor": v}
                   for m, v in zip(painel["mensal"]["meses"], total_mensal["saldos"])],
        ),
    ]

    estoque = painel["estoque"]
    if estoque["disponivel"]:
        ultimo = estoque["pontos"][-1]
        indicadores.append(Indicador(
            id="caged_estoque",
            categoria="Emprego",
            indicador="Estoque de vínculos ativos",
            valor=ultimo["valor"],
            unidade="vínculos",
            periodo=ultimo["rotulo"].replace("Estoque ", "").strip("()"),
            fonte="RAIS + Novo CAGED",
            fonte_detalhe="Base da RAIS projetada pelos saldos mensais do CAGED",
            url=URL_FONTE,
            formato="inteiro",
            serie=[{"periodo": p["rotulo"].replace("Estoque ", ""), "valor": p["valor"]}
                   for p in estoque["pontos"]],
            observacao=estoque["observacao"],
        ))

    status = "ok" if not indisponiveis else "parcial"
    mensagem = (f"{len(chaves)} competências apuradas; {baixadas} nova(s) nesta execução"
                + (f"; {indisponiveis} ainda não publicada(s)" if indisponiveis else ""))

    resultado = ResultadoColeta(fonte="Novo CAGED", status=status,
                                mensagem=mensagem, indicadores=indicadores)
    resultado.painel_emprego = painel  # type: ignore[attr-defined]
    return resultado
