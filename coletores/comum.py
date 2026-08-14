"""Utilidades compartilhadas pelos coletores."""
from __future__ import annotations

import json
import logging
import time
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Identificação do município
# ---------------------------------------------------------------------------
COD_IBGE = "4307807"          # Estrela/RS — código de 7 dígitos
COD_IBGE_6 = COD_IBGE[:6]     # 430780 — usado pelo CAGED/RAIS
NOME_MUNICIPIO = "Estrela"
UF = "RS"

RAIZ = Path(__file__).resolve().parent.parent
DIR_DADOS = RAIZ / "dados"
ARQ_INDICADORES = DIR_DADOS / "indicadores.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)-10s | %(message)s",
    datefmt="%H:%M:%S",
)


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hoje() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos — para comparar rótulos de fontes oficiais."""
    if texto is None:
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def para_numero(valor: Any) -> float | None:
    """Converte valores das APIs em número. Marcadores do IBGE ('-', '..',
    '...', 'X') e strings vazias retornam None."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace(".", "").replace(",", ".")
    if texto in {"", "-", "..", "...", "X", "x"}:
        return None
    try:
        return float(texto)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# HTTP resiliente
# ---------------------------------------------------------------------------
SESSAO = requests.Session()
SESSAO.headers.update(
    {"User-Agent": "painel-indicadores-estrela/1.0 (dados públicos municipais)"}
)


def buscar_json(url: str, params: dict | None = None, tentativas: int = 4,
                espera: float = 8.0, timeout: int = 90) -> Any:
    """GET com retentativa exponencial. Levanta exceção após esgotar tentativas.

    Em caso de erro HTTP, registra um trecho do corpo da resposta — útil para
    diagnosticar bloqueios por WAF/limitação de taxa, que costumam trazer a
    razão do bloqueio no corpo, diferente de uma falha de rede comum.
    """
    ultimo_erro: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = SESSAO.get(url, params=params, timeout=timeout)
            resposta.raise_for_status()
            return resposta.json()
        except Exception as erro:  # noqa: BLE001
            ultimo_erro = erro
            corpo = ""
            resposta_erro = getattr(erro, "response", None)
            if resposta_erro is not None:
                corpo = (resposta_erro.text or "")[:300].replace("\n", " ")
            if tentativa < tentativas:
                pausa = espera * tentativa
                logging.warning("falha em %s (tentativa %d/%d): %s%s — nova tentativa em %.0fs",
                                url, tentativa, tentativas, erro,
                                f" | corpo: {corpo}" if corpo else "", pausa)
                time.sleep(pausa)
            else:
                logging.warning("última tentativa falhou em %s: %s%s",
                                url, erro, f" | corpo: {corpo}" if corpo else "")
    raise RuntimeError(f"não foi possível obter {url}: {ultimo_erro}")


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------
@dataclass
class Indicador:
    id: str
    categoria: str
    indicador: str
    valor: float | None
    unidade: str
    periodo: str
    fonte: str
    fonte_detalhe: str = ""
    url: str = ""
    origem: str = "automatico"          # automatico | manual
    formato: str = "numero"             # numero | moeda | percentual | inteiro
    coletado_em: str = field(default_factory=hoje)
    serie: list[dict] = field(default_factory=list)
    observacao: str = ""

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class ResultadoColeta:
    fonte: str
    status: str                          # ok | parcial | falha
    mensagem: str = ""
    executado_em: str = field(default_factory=agora_iso)
    indicadores: list[Indicador] = field(default_factory=list)
    # Bloco livre para painéis que não cabem no formato de cartão
    # (ex.: a matriz setor × mês do CAGED). Ignorado quando vazio.
    painel_emprego: dict | None = None
    painel_educacao: dict | None = None


def carregar_anterior() -> dict:
    """Lê o JSON publicado na execução anterior (para preservar dados em caso
    de indisponibilidade de uma fonte).

    Se o arquivo estiver corrompido, uma cópia é preservada com carimbo de
    tempo antes de recomeçar do zero — evita perder silenciosamente todos os
    indicadores conservados de fontes que não rodaram nesta execução."""
    if ARQ_INDICADORES.exists():
        texto = ARQ_INDICADORES.read_text(encoding="utf-8")
        try:
            return json.loads(texto)
        except json.JSONDecodeError as erro:
            copia = ARQ_INDICADORES.with_name(
                f"indicadores.corrompido.{hoje()}.json")
            copia.write_text(texto, encoding="utf-8")
            logging.error(
                "indicadores.json anterior está corrompido (%s) — cópia salva em "
                "%s; todos os indicadores conservados desta execução serão perdidos "
                "até a próxima coleta completa", erro, copia)
    return {}
