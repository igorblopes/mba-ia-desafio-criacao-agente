"""Leitura e parsing de ``dados/regulamento.md`` em trechos (chunks).

Única camada que abre o arquivo do regulamento. Não ranqueia, não normaliza o texto e não
persiste nada: a estrutura parseada fica apenas em memória (cache por instância).

Estrutura real do documento (inspecionada): ``# Título`` e ``## Capítulo ...``; dentro dos
capítulos, artigos iniciados por ``**Art. N.**`` seguidos de parágrafos, incisos (``I.``),
parágrafos numerados (``§ 1º``) e ``Parágrafo único``. Não há ``###``. Por isso:
heading = capítulo, subheading = artigo, content = texto integral do artigo.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

from app.config import DADOS_DIR
from app.domain.errors import RegulationUnavailableError
from app.domain.regulation import RegulationChunk

REGULATION_PATH = DADOS_DIR / "regulamento.md"
# Artigo maior que isso é subdividido, sempre entre unidades atômicas (parágrafo/lista).
MAX_CHUNK_CHARS = 1500

_H2 = re.compile(r"^##\s+(.+?)\s*$")
_H1 = re.compile(r"^#\s+")
_ARTICLE = re.compile(r"^\*\*(Art\.\s*[^*]+?)\.?\*\*")
_LIST_ITEM = re.compile(r"^(?:[IVXLCDM]+\.\s|[a-z]\)\s|[-*]\s|§\s*\d+)")


def _units(lines: list[str]) -> list[str]:
    """Agrupa linhas em unidades atômicas: parágrafo, ou parágrafo introdutório + sua lista."""
    paragraphs: list[str] = []
    buf: list[str] = []
    for line in lines:
        if line.strip():
            buf.append(line)
        elif buf:
            paragraphs.append("\n".join(buf))
            buf = []
    if buf:
        paragraphs.append("\n".join(buf))

    units: list[str] = []
    for para in paragraphs:
        prev = units[-1] if units else None
        # incisos/alíneas seguem o parágrafo que os introduz (terminado em ":" ou outro item)
        if prev is not None and _LIST_ITEM.match(para) and _is_list_context(prev):
            units[-1] = f"{prev}\n\n{para}"
        else:
            units.append(para)
    return units


def _is_list_context(unit: str) -> bool:
    last = unit.rstrip().splitlines()[-1].strip()
    return last.endswith(":") or bool(_LIST_ITEM.match(last))


def _split_long(content: str) -> list[str]:
    if len(content) <= MAX_CHUNK_CHARS:
        return [content]
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for unit in _units(content.split("\n")):
        if current and size + len(unit) + 2 > MAX_CHUNK_CHARS:
            parts.append("\n\n".join(current))
            current, size = [], 0
        current.append(unit)
        size += len(unit) + 2
    if current:
        parts.append("\n\n".join(current))
    return parts


def parse_regulation(text: str) -> tuple[RegulationChunk, ...]:
    """Converte o Markdown em chunks (função pura; usada pelo Repository e pelos testes)."""
    chunks: list[RegulationChunk] = []
    heading: str | None = None
    subheading = ""
    lines: list[str] = []

    def flush() -> None:
        nonlocal lines
        body = "\n".join(lines).strip("\n")
        lines = []
        if heading is None or not body.strip():
            return
        parts = _split_long(body)
        for i, part in enumerate(parts, start=1):
            sub = subheading if len(parts) == 1 else f"{subheading} (parte {i}/{len(parts)})"
            chunks.append(RegulationChunk(heading, sub, part.strip("\n"), len(chunks)))

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        m2 = _H2.match(line)
        if m2:
            flush()
            heading, subheading = m2.group(1), ""
            continue
        if _H1.match(line):  # título do documento
            flush()
            heading, subheading = None, ""
            continue
        art = _ARTICLE.match(line)
        if art and heading is not None:
            flush()
            subheading = art.group(1).strip()
        lines.append(line)
    flush()
    return tuple(chunks)


class RegulationRepository:
    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else REGULATION_PATH
        self._chunks: tuple[RegulationChunk, ...] | None = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def get_chunks(self) -> tuple[RegulationChunk, ...]:
        """Trechos do regulamento em ordem; o arquivo é lido uma vez por instância."""
        if self._chunks is None:
            with self._lock:
                if self._chunks is None:
                    try:
                        # newline=None: CRLF -> LF; nenhum outro caractere é alterado
                        with open(self._path, encoding="utf-8", newline=None) as fh:
                            text = fh.read()
                    except OSError as exc:
                        raise RegulationUnavailableError() from exc
                    self._chunks = parse_regulation(text)
        return self._chunks
