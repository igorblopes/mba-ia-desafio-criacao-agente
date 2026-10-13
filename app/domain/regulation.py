"""Tipos de domínio da consulta ao regulamento (somente em memória; nada vai ao banco)."""

from __future__ import annotations

from dataclasses import dataclass

SECTION_SEPARATOR = " > "


@dataclass(frozen=True, slots=True)
class RegulationChunk:
    """Trecho do regulamento delimitado pela estrutura Markdown do próprio documento.

    ``content`` é o texto ORIGINAL do arquivo (apenas com quebras de linha normalizadas para
    ``\\n``); a normalização usada na busca nunca é aplicada a ele.
    """

    heading: str  # capítulo (heading de nível 2), sem os "#"
    subheading: str  # artigo, p.ex. "Art. 22"; vazio para texto anterior ao primeiro artigo
    content: str
    order: int  # posição no documento (0, 1, 2, ...)

    @property
    def section(self) -> str:
        if not self.subheading:
            return self.heading
        return f"{self.heading}{SECTION_SEPARATOR}{self.subheading}"


@dataclass(frozen=True, slots=True)
class RegulationExcerpt:
    section: str
    content: str


@dataclass(frozen=True, slots=True)
class RegulationSearchResult:
    status: str  # success | not_found | query_too_broad | invalid_input
    excerpts: tuple[RegulationExcerpt, ...] = ()
    unmatched_terms: tuple[str, ...] = ()
