"""Coletor do Novo CAGED — microdados oficiais do PDET/Ministério do Trabalho.

Não existe API REST para o Novo CAGED. A fonte primária são os microdados
mensais publicados em ftp://ftp.mtps.gov.br/pdet/microdados/NOVO CAGED/,
em arquivos .7z contendo texto delimitado por ';' e codificado em UTF-8.

Cada arquivo mensal cobre o país inteiro (dezenas de milhões de linhas), de
modo que o coletor:
  1. lê o cache local dados/caged_serie.csv;
  2. baixa apenas as competências ainda ausentes (normalmente uma por mês);
  3. filtra o município pelo código IBGE de 6 dígitos durante a leitura,
     em blocos, para não carregar o arquivo inteiro em memória;
  4. grava o resultado agregado de volta no cache.

O custo por execução é, portanto, o de um único mês — e o histórico fica
versionado no próprio repositório.
"""
from __future__ import annotations

import csv
import ftplib
import io
import logging
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .comum import COD_IBGE_6, DIR_DADOS, Indicador, ResultadoColeta

log = logging.getLogger("caged")

SERVIDOR = "ftp.mtps.gov.br"
DIRETORIO = "/pdet/microdados/NOVO CAGED"
CACHE = DIR_DADOS / "caged_serie.csv"
MESES_SERIE = 24
TIPOS = ["MOV", "FOR", "EXC"]  # movimentações, fora do prazo, exclusões


@dataclass
class Competencia:
    ano: int
    mes: int

    @property
    def chave(self) -> str:
        return f"{self.ano}{self.mes:02d}"

    def anterior(self) -> "Competencia":
        return (Competencia(self.ano - 1, 12) if self.mes == 1
                else Competencia(self.ano, self.mes - 1))


def _competencias_alvo() -> list[Competencia]:
    """O CAGED de um mês é divulgado cerca de 30 a 45 dias depois; por isso
    a competência mais recente esperada é a de dois meses atrás."""
    hoje = date.today()
    atual = Competencia(hoje.year, hoje.month).anterior().anterior()
    lista = [atual]
    for _ in range(MESES_SERIE - 1):
        lista.append(lista[-1].anterior())
    return list(reversed(lista))


def _ler_cache() -> dict[str, dict]:
    if not CACHE.exists():
        return {}
    with CACHE.open(encoding="utf-8", newline="") as arquivo:
        return {linha["competencia"]: {
            "admissoes": int(linha["admissoes"]),
            "desligamentos": int(linha["desligamentos"]),
            "saldo": int(linha["saldo"]),
        } for linha in csv.DictReader(arquivo)}


def _gravar_cache(dados: dict[str, dict]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(["competencia", "admissoes", "desligamentos", "saldo"])
        for chave in sorted(dados):
            registro = dados[chave]
            escritor.writerow([chave, registro["admissoes"],
                               registro["desligamentos"], registro["saldo"]])


def _baixar(caminho_remoto: str, destino: Path) -> bool:
    try:
        with ftplib.FTP(SERVIDOR, timeout=180) as ftp:
            ftp.login()  # anônimo
            ftp.set_pasv(True)
            with destino.open("wb") as saida:
                ftp.retrbinary(f"RETR {caminho_remoto}", saida.write, blocksize=1 << 20)
        return destino.stat().st_size > 0
    except ftplib.all_errors as erro:
        log.info("indisponível: %s (%s)", caminho_remoto, erro)
        destino.unlink(missing_ok=True)
        return False


def _apurar(arquivo_7z: Path) -> tuple[int, int]:
    """Extrai o .7z e soma o saldo do município. Retorna (admissões, desligamentos).

    No layout do Novo CAGED, 'saldomovimentação' vale +1 para admissão e -1
    para desligamento; nos arquivos EXC (exclusões) o sinal deve ser invertido.
    """
    import py7zr

    inverter = arquivo_7z.name.upper().startswith("CAGEDEXC")
    admissoes = desligamentos = 0

    with tempfile.TemporaryDirectory() as pasta:
        with py7zr.SevenZipFile(arquivo_7z, mode="r") as pacote:
            pacote.extractall(path=pasta)
        for txt in Path(pasta).rglob("*.txt"):
            with txt.open("r", encoding="utf-8", errors="replace") as fluxo:
                cabecalho = fluxo.readline().rstrip("\n").split(";")
                indices = {c.strip().lower().strip('"'): i for i, c in enumerate(cabecalho)}
                col_mun = next((indices[c] for c in indices if "munic" in c), None)
                col_saldo = next((indices[c] for c in indices if "saldo" in c), None)
                if col_mun is None or col_saldo is None:
                    log.warning("layout inesperado em %s: %s", txt.name, cabecalho[:12])
                    continue
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
                    if saldo > 0:
                        admissoes += saldo
                    else:
                        desligamentos += -saldo
    return admissoes, desligamentos


def _coletar_competencia(comp: Competencia) -> dict | None:
    admissoes = desligamentos = 0
    obteve = False
    with tempfile.TemporaryDirectory() as pasta:
        for tipo in TIPOS:
            nome = f"CAGED{tipo}{comp.chave}.7z"
            remoto = f"{DIRETORIO}/{comp.ano}/{comp.chave}/{nome}"
            destino = Path(pasta) / nome
            if not _baixar(remoto, destino):
                continue
            adm, des = _apurar(destino)
            admissoes += adm
            desligamentos += des
            obteve = True
            destino.unlink(missing_ok=True)
    if not obteve:
        return None
    return {"admissoes": admissoes, "desligamentos": desligamentos,
            "saldo": admissoes - desligamentos}


def coletar() -> ResultadoColeta:
    cache = _ler_cache()
    alvos = _competencias_alvo()
    novas = [c for c in alvos if c.chave not in cache]

    baixadas, indisponiveis = 0, 0
    for comp in novas:
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
        log.info("%s: saldo %+d", comp.chave, registro["saldo"])

    if baixadas:
        _gravar_cache(cache)

    chaves = [c.chave for c in alvos if c.chave in cache]
    if not chaves:
        return ResultadoColeta(
            fonte="Novo CAGED", status="falha",
            mensagem="nenhuma competência disponível no servidor do PDET")

    def formatar(chave: str) -> str:
        return f"{chave[4:]}/{chave[:4]}"

    def montar(campo: str, rotulo: str, ident: str, obs: str = "") -> Indicador:
        serie = [{"periodo": formatar(k), "valor": cache[k][campo]} for k in chaves]
        return Indicador(
            id=ident,
            categoria="Emprego",
            indicador=rotulo,
            valor=serie[-1]["valor"],
            unidade="vínculos",
            periodo=serie[-1]["periodo"],
            fonte="Novo CAGED / MTE",
            fonte_detalhe="Microdados do PDET — apuração pelo código de município 430780",
            url="https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/estatisticas-trabalho/microdados-rais-e-caged",
            formato="inteiro",
            serie=serie,
            observacao=obs,
        )

    indicadores = [
        montar("saldo", "Saldo de empregos no mês", "caged_saldo",
               "Diferença entre admissões e desligamentos com carteira assinada, "
               "consolidando movimentações, declarações fora do prazo e exclusões."),
        montar("admissoes", "Admissões no mês", "caged_admissoes"),
        montar("desligamentos", "Desligamentos no mês", "caged_desligamentos"),
    ]

    acumulado = sum(cache[k]["saldo"] for k in chaves[-12:])
    indicadores.append(Indicador(
        id="caged_saldo_12m",
        categoria="Emprego",
        indicador="Saldo acumulado em 12 meses",
        valor=acumulado,
        unidade="vínculos",
        periodo=f"{formatar(chaves[-12] if len(chaves) >= 12 else chaves[0])} a {formatar(chaves[-1])}",
        fonte="Novo CAGED / MTE",
        fonte_detalhe="Soma dos saldos mensais apurados",
        url="https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/estatisticas-trabalho/microdados-rais-e-caged",
        formato="inteiro",
    ))

    status = "ok" if not indisponiveis else "parcial"
    mensagem = (f"{len(chaves)} competências em série; {baixadas} nova(s) nesta execução"
                + (f"; {indisponiveis} ainda não publicada(s)" if indisponiveis else ""))
    return ResultadoColeta(fonte="Novo CAGED", status=status, mensagem=mensagem,
                           indicadores=indicadores)
