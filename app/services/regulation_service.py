"""Busca local, determinística e offline de trechos do regulamento.

Sem embeddings, sem rede, sem LLM: normalização -> tokens -> ranking por IDF -> poucos trechos.
Os limites (quantidade e tamanho) são constantes de código; o modelo não os controla.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from app.domain.regulation import (
    RegulationChunk,
    RegulationExcerpt,
    RegulationSearchResult,
)
from app.repositories.regulation_repository import RegulationRepository

MAX_RESULTS = 3  # artigos curtos (<= ~1,1 mil caracteres): 3 cobrem regra + exceção + vizinho
MAX_RETURNED_CHARS = 3000  # teto do conteúdo somado; o documento tem ~45 mil caracteres
MAX_QUERY_CHARS = 500
MAX_QUERY_TOKENS = 30

HEADING_BOOST = 1.5  # peso extra quando o termo aparece no capítulo (heading)
UNKNOWN_TERM_WEIGHT = 0.5  # termo ausente do documento pesa metade do IDF máximo no denominador
MIN_COVERAGE = 0.5  # fração mínima (por IDF) dos termos da pergunta que o trecho deve cobrir
RELATIVE_SCORE_CUTOFF = 0.6  # descarta trechos bem abaixo do melhor

_STOPWORDS = frozenset(
    """a o as os um uma uns umas de do da dos das dum duma em no na nos nas ao aos à às
    por para pra com sem sob sobre e ou mas que se como qual quais quando onde quem quanto
    quanta quantos quantas é são ser foi era eh há ha tem têm ter posso pode podem podemos
    poder preciso precisa pode usar uso utilizar existe existem sobre me meu minha meus
    minhas eu voce vc seu sua isso isto esse essa este esta mais muito pouco ja já so só
    regra regras norma normas regulamento artigo artigos favor gostaria saber queria""".split()
)

# Vocabulário de pedidos "dê-me tudo": se a pergunta só contém isso, é consulta ampla.
_BROAD_MARKERS = frozenset(
    "tudo todo toda todos todas inteiro inteira completo completa integral integralmente".split()
)
_BROAD_FILLER = frozenset(
    """mostre mostrar mostra liste listar lista envie enviar envia mande mandar manda
    quero desejo ver exiba exibir traga trazer cole colar imprima copie leia ler documento texto
    regulamento regras regra normas norma artigos artigo capitulos capitulo
    condominio residencial aurora geral completo inteiro tudo todas todos""".split()
)


# Sinônimos mínimos e fixos (consulta -> termos do documento). O texto devolvido nunca muda.
_SYNONYMS = {
    "barulho": ("ruido", "silencio"),
    "cachorro": ("animal", "animai"),
    "gato": ("animal", "animai"),
    "pet": ("animal", "animai"),
    "hora": ("horario",),
    "funcionamento": ("horario",),
}
# O documento expressa horários como "8h", "9h30": esses trechos respondem a "horário".
_CLOCK = re.compile(r"\b\d{1,2}h(?:\d{2})?\b")
CLOCK_TOKEN = "horario"


def normalize(text: str) -> str:
    """Minúsculas, sem acentos, sem pontuação, espaços colapsados (apenas para busca)."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


def _stem(token: str) -> str:
    # plural simples: "domingos" == "domingo"; sem biblioteca de stemming
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in normalize(text).split()]


_STOP = frozenset(_stem(normalize(w)) for w in _STOPWORDS)
_BROAD_MARK = frozenset(_stem(w) for w in _BROAD_MARKERS)
_BROAD_FILL = frozenset(_stem(w) for w in _BROAD_FILLER) | _STOP


@dataclass(frozen=True, slots=True)
class _Indexed:
    chunk: RegulationChunk
    heading_tokens: frozenset[str]
    content_counts: Counter


class RegulationService:
    def __init__(self, repository: RegulationRepository | None = None) -> None:
        self._repository = repository or RegulationRepository()
        self._index: tuple[_Indexed, ...] | None = None
        self._df: Counter = Counter()

    # ---------------------------------------------------------------- índice

    def _ensure_index(self) -> tuple[_Indexed, ...]:
        if self._index is None:
            items: list[_Indexed] = []
            df: Counter = Counter()
            for chunk in self._repository.get_chunks():
                heading_tokens = frozenset(tokenize(chunk.heading))
                counts = Counter(tokenize(chunk.content))
                if _CLOCK.search(chunk.content):
                    counts[CLOCK_TOKEN] += 1  # índice apenas; o conteúdo devolvido é o original
                items.append(_Indexed(chunk, heading_tokens, counts))
                df.update(heading_tokens | set(counts))
            self._df = df
            self._index = tuple(items)
        return self._index

    def _idf(self, token: str, n: int) -> float:
        df = self._df.get(token, 0)
        if df == 0:  # termo que não existe no documento
            return UNKNOWN_TERM_WEIGHT * math.log(1 + n)
        return math.log(1 + n / df)

    # ---------------------------------------------------------------- consulta

    def search(self, question: str) -> RegulationSearchResult:
        if not isinstance(question, str) or not question.strip():
            return RegulationSearchResult("invalid_input")
        question = question[:MAX_QUERY_CHARS]
        raw_tokens = tokenize(question)
        if self._is_broad(raw_tokens):
            return RegulationSearchResult("query_too_broad")

        terms = list(dict.fromkeys(t for t in raw_tokens if t not in _STOP))[:MAX_QUERY_TOKENS]
        index = self._ensure_index()
        if not terms or not index:
            return RegulationSearchResult("not_found")

        n = len(index)
        alts = {t: (t, *(_stem(a) for a in _SYNONYMS.get(t, ()))) for t in terms}
        idf = {t: max(self._idf(a, n) for a in alts[t]) for t in terms}
        total = sum(idf.values())

        scored: list[tuple[float, int, _Indexed]] = []
        for item in index:
            score = 0.0
            matched = 0.0
            for t in terms:
                in_head = any(a in item.heading_tokens for a in alts[t])
                tf = sum(item.content_counts.get(a, 0) for a in alts[t])
                if not in_head and tf == 0:
                    continue
                matched += idf[t]
                score += idf[t] * (
                    (HEADING_BOOST if in_head else 0.0)
                    + (1.0 + 0.25 * min(tf - 1, 2) if tf else 0.0)
                )
            if matched / total >= MIN_COVERAGE:
                scored.append((score, item.chunk.order, item))

        if not scored:
            return RegulationSearchResult("not_found")

        scored.sort(key=lambda s: (-s[0], s[1]))  # desempate estável pela ordem do documento
        best = scored[0][0]
        selected: list[RegulationChunk] = []
        used = 0
        for score, _, item in scored:
            if len(selected) >= MAX_RESULTS or score < best * RELATIVE_SCORE_CUTOFF:
                break
            size = len(item.chunk.content)
            if used + size > MAX_RETURNED_CHARS:
                continue  # nunca corta um trecho no meio
            selected.append(item.chunk)
            used += size
        if not selected:
            return RegulationSearchResult("not_found")
        # o contexto é apresentado na ordem do documento
        selected.sort(key=lambda c: c.order)

        unmatched = tuple(t for t in terms if all(self._df.get(a, 0) == 0 for a in alts[t]))
        return RegulationSearchResult(
            "success",
            tuple(RegulationExcerpt(c.section, c.content) for c in selected),
            unmatched,
        )

    @staticmethod
    def _is_broad(tokens: list[str]) -> bool:
        if not tokens or not any(t in _BROAD_MARK for t in tokens):
            return False
        return all(t in _BROAD_FILL for t in tokens)
