"""Leitura INDEPENDENTE de ``dados/regulamento.md`` para derivar expectativas dos testes.

Não usa o parser da aplicação: as expectativas vêm do texto real do arquivo.
"""

from __future__ import annotations

from app.config import DADOS_DIR

REGULATION_PATH = DADOS_DIR / "regulamento.md"


def regulation_text() -> str:
    return REGULATION_PATH.read_text(encoding="utf-8")  # newline universal: CRLF -> LF


def chapters() -> dict[str, str]:
    """título do capítulo (sem '## ') -> texto do capítulo (sem a linha de título)."""
    result: dict[str, str] = {}
    for block in regulation_text().split("\n## ")[1:]:
        title, _, body = block.partition("\n")
        result[title.strip()] = body.strip()
    return result


def chapter(keyword: str) -> tuple[str, str]:
    [(title, body)] = [(t, b) for t, b in chapters().items() if keyword.lower() in t.lower()]
    return title, body


def paragraphs(body: str) -> list[str]:
    return [p.strip() for p in body.split("\n\n") if p.strip()]


def lines_with(body: str, word: str) -> list[str]:
    return [l.strip() for l in body.splitlines() if word.lower() in l.lower()]
