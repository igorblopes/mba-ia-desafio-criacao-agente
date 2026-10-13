"""Ranking, limites e respostas seguras do RegulationService (offline, sem API key)."""

from __future__ import annotations

import json
import os

import pytest

from app.services import regulation_service as rs
from app.services.regulation_service import RegulationService, normalize, tokenize
from tests.regulation_support import chapter, chapters, lines_with, regulation_text

POOL_QUESTION = "Posso usar a piscina no domingo?"


@pytest.fixture(scope="module")
def service():
    return RegulationService()


def _blob(result) -> str:
    return "\n".join(e.content for e in result.excerpts)


def test_works_without_google_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert RegulationService().search(POOL_QUESTION).status == "success"
    assert "GOOGLE_API_KEY" not in os.environ


def test_pool_on_sunday_returns_the_real_sunday_rule(service):
    _, pool = chapter("Piscina")
    sunday_lines = lines_with(pool, "domingo")
    assert sunday_lines  # a regra existe no arquivo real
    result = service.search(POOL_QUESTION)
    assert result.status == "success"
    for line in sunday_lines:
        assert line in _blob(result)
    assert all(e.section.startswith("Capítulo IV: Piscina") for e in result.excerpts)


def test_unrelated_chapter_text_is_not_returned(service):
    title, body = chapter("Mudanças")
    assert "piscina" not in body.lower() and "domingo" not in body.lower()
    blob = _blob(service.search(POOL_QUESTION))
    for paragraph in body.split("\n\n"):
        assert paragraph.strip() not in blob


def test_returned_text_is_verbatim_from_the_file(service):
    text = regulation_text()
    for question in (POOL_QUESTION, "qual o horário de mudança?", "posso ter cachorro?"):
        for e in service.search(question).excerpts:
            assert e.content in text  # sem normalização nem reescrita


def test_is_deterministic(service):
    first = service.search(POOL_QUESTION)
    for _ in range(5):
        assert RegulationService().search(POOL_QUESTION) == first
        assert service.search(POOL_QUESTION) == first


def test_normalization_equivalences(service):
    assert normalize("PISCINA") == normalize("Piscina") == normalize("piscina!") == "piscina"
    assert tokenize("salão") == tokenize("salao") == tokenize("SALÃO?")
    assert tokenize("domingos") == tokenize("domingo")
    a, b = service.search("PISCINA"), service.search("piscina")
    assert a == b and a.status == "success"
    assert service.search("salão de festas") == service.search("SALAO DE FESTAS")


def test_stopwords_do_not_drive_the_ranking(service):
    assert service.search("a piscina") == service.search("piscina")


def test_result_limits(service):
    _, pool = chapter("Piscina")
    for question in ("piscina", "regras de silêncio e barulho", "animais", "garagem", "multa"):
        result = service.search(question)
        assert len(result.excerpts) <= rs.MAX_RESULTS
        assert sum(len(e.content) for e in result.excerpts) <= rs.MAX_RETURNED_CHARS
    assert len(service.search("piscina").excerpts) == rs.MAX_RESULTS  # capítulo tem 8 artigos
    assert len(pool) < len(regulation_text()) // 5


def test_content_limit_never_cuts_a_chunk(service, monkeypatch):
    monkeypatch.setattr(rs, "MAX_RETURNED_CHARS", 900)
    result = service.search("piscina")
    text = regulation_text()
    assert result.excerpts and all(e.content in text for e in result.excerpts)
    assert sum(len(e.content) for e in result.excerpts) <= 900


@pytest.mark.parametrize("question", [
    "Mostre o regulamento inteiro.",
    "Quais são todas as regras?",
    "Liste todas as normas.",
    "Me envie tudo.",
    "Quero o texto completo do regulamento",
])
def test_broad_queries_are_blocked(service, question):
    result = service.search(question)
    assert result.status == "query_too_broad" and result.excerpts == ()


def test_specific_query_with_broad_words_is_not_blocked(service):
    assert service.search("todas as regras da piscina").status == "success"


def test_nonexistent_topic_is_not_found(service):
    text = regulation_text().lower()
    for word in ("helicóptero", "helicoptero", "heliponto", "pousar"):
        assert word not in text
    for question in ("Qual é a regra para pousar um helicóptero na piscina?",
                     "Qual a regra para pousar um drone no heliponto?"):
        result = service.search(question)
        assert result.status == "not_found" and result.excerpts == ()


def test_partially_supported_question_reports_missing_part(service):
    result = service.search("Posso usar a piscina no domingo e pousar um helicóptero?")
    assert result.status == "success"
    assert "helicoptero" in result.unmatched_terms
    assert "piscina" not in result.unmatched_terms and "domingo" not in result.unmatched_terms
    _, pool = chapter("Piscina")
    assert all(line in _blob(result) for line in lines_with(pool, "domingos"))


@pytest.mark.parametrize("question", ["", "   ", "???", None, 123])
def test_empty_or_invalid_input(service, question):
    result = service.search(question)  # type: ignore[arg-type]
    assert result.status in {"invalid_input", "not_found"} and result.excerpts == ()


def test_no_vector_store_or_network_dependencies():
    import ast
    import inspect

    from app.repositories import regulation_repository

    banned = {"faiss", "chromadb", "pinecone", "weaviate", "qdrant_client", "numpy", "requests",
              "httpx", "urllib", "socket", "aiohttp", "google", "sqlalchemy", "app.database"}
    for mod in (rs, regulation_repository):
        imported: set[str] = set()
        for node in ast.walk(ast.parse(inspect.getsource(mod))):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        assert not any(i == b or i.startswith(b + ".") for i in imported for b in banned), imported


def test_each_chapter_is_retrievable_by_its_title(service):
    for title in chapters():
        keyword = title.split(":", 1)[1].split(",")[0].strip()
        result = service.search(keyword)
        assert result.status == "success", title
        assert any(title in e.section for e in result.excerpts), title


def test_result_is_json_serializable(service):
    json.dumps([e.__dict__ if hasattr(e, "__dict__") else (e.section, e.content)
                for e in service.search(POOL_QUESTION).excerpts])


@pytest.mark.parametrize("with_small_article", [False, True])
def test_oversized_atomic_paragraph_never_exceeds_budget(tmp_path, with_small_article):
    from app.repositories.regulation_repository import RegulationRepository

    text = "## Piscina\n\n**Art. 1.** " + "piscina " * 450
    small = "**Art. 2.** piscina piscina piscina."
    if with_small_article:
        text += "\n\n" + small
    path = tmp_path / "regulamento.md"
    path.write_text(text, encoding="utf-8")
    result = RegulationService(RegulationRepository(path)).search("piscina")
    assert sum(len(e.content) for e in result.excerpts) <= rs.MAX_RETURNED_CHARS
    assert all(e.content in text for e in result.excerpts)
    if with_small_article:
        assert result.status == "success"
        assert [e.content for e in result.excerpts] == [small]
    else:
        assert result.status == "not_found" and not result.excerpts
