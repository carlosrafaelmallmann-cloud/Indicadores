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
                espera: float = 3.0, timeout: int = 90) -> Any:
    """GET com retentativa exponencial. Levanta exceção após esgotar tentativas."""
    ultimo_erro: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = SESSAO.get(url, params=params, timeout=timeout)
            resposta.raise_for_status()
            return resposta.json()
        except Exception as erro:  # noqa: BLE001
            ultimo_erro = erro
            if tentativa < tentativas:
                pausa = espera * tentativa
                logging.warning("falha em %s (tentativa %d/%d): %s — nova tentativa em %.0fs",
                                url, tentativa, tentativas, erro, pausa)
                time.sleep(pausa)
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
    de indisponibilidade de uma fonte)."""
    if ARQ_INDICADORES.exists():
        try:
            return json.loads(ARQ_INDICADORES.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logging.warning("indicadores.json anterior está corrompido — ignorado")
    return {}
