"""Parser do regulamento (offline): estrutura, ordem e fidelidade ao texto original."""

from __future__ import annotations

import re

import pytest

from app.domain.errors import RegulationUnavailableError
from app.repositories.regulation_repository import (
    MAX_CHUNK_CHARS,
    REGULATION_PATH,
    RegulationRepository,
    parse_regulation,
)
from tests.regulation_support import chapters, regulation_text


@pytest.fixture(scope="module")
def chunks():
    return RegulationRepository().get_chunks()


def test_regulation_file_exists():
    assert REGULATION_PATH.is_file() and REGULATION_PATH.name == "regulamento.md"


def test_one_chunk_per_article_and_all_chapters_detected(chunks):
    text = regulation_text()
    articles = re.findall(r"^\*\*(Art\. [^*]+?)\.?\*\*", text, flags=re.M)
    assert len(articles) == 96
    assert [c.subheading for c in chunks] == [a.strip() for a in articles]
    assert len({c.heading for c in chunks}) == len(chapters()) == 14


def test_headings_and_subheadings_are_preserved(chunks):
    pool = [c for c in chunks if c.heading == "Capítulo IV: Piscina"]
    assert [c.subheading for c in pool][:2] == ["Art. 21", "Art. 22"]
    assert pool[1].section == "Capítulo IV: Piscina > Art. 22"
    assert not any(c.heading.startswith("#") for c in chunks)


def test_order_is_document_order(chunks):
    assert [c.order for c in chunks] == list(range(len(chunks)))
    positions = [regulation_text().index(c.content) for c in chunks]
    assert positions == sorted(positions)


def test_content_is_not_modified(chunks):
    text = regulation_text()
    for c in chunks:
        assert c.content in text  # trecho literal do arquivo (somente CRLF -> LF)


def test_no_line_of_the_document_is_lost_or_altered(chunks):
    body_lines = [
        l for l in regulation_text().splitlines()
        if l.strip() and not l.startswith("#")
    ]
    chunk_lines = [l for c in chunks for l in c.content.splitlines() if l.strip()]
    assert chunk_lines == body_lines


def test_chunks_are_bounded_and_never_empty(chunks):
    assert all(c.content.strip() for c in chunks)
    assert all(len(c.content) <= MAX_CHUNK_CHARS for c in chunks)
    assert sum(len(c.content) for c in chunks) < len(regulation_text())


def test_chunks_start_with_their_article_marker(chunks):
    for c in chunks:
        assert c.content.startswith(f"**{c.subheading}")


def test_long_articles_are_split_between_paragraphs_and_lists_stay_together():
    items = "\n\n".join(f"{r}. {'x' * 400};" for r in ("I", "II", "III", "IV"))
    doc = f"# T\n\n## Cap\n\n**Art. 1.** Intro:\n\n{items}\n\n**Art. 2.** Outro."
    chunks = parse_regulation(doc)
    assert [c.subheading for c in chunks] == ["Art. 1", "Art. 2"]  # lista longa fica inteira
    assert chunks[0].content.endswith("x;") and "IV." in chunks[0].content

    long_paragraphs = "\n\n".join("p" * 700 for _ in range(4))
    chunks = parse_regulation(f"## Cap\n\n**Art. 1.** a\n\n{long_paragraphs}")
    assert len(chunks) > 1
    assert all(c.content.count("p" * 700) >= 1 for c in chunks)
    assert "".join(c.content for c in chunks).count("p") == 2800  # nada cortado no meio


def test_text_before_first_article_is_kept():
    [c] = parse_regulation("# T\n\n## Cap\n\nIntrodução do capítulo.")
    assert (c.heading, c.subheading, c.content) == ("Cap", "", "Introdução do capítulo.")
    assert c.section == "Cap"


def test_repository_caches_parsed_structure():
    repo = RegulationRepository()
    assert repo.get_chunks() is repo.get_chunks()


def test_missing_file_raises_domain_error(tmp_path):
    with pytest.raises(RegulationUnavailableError):
        RegulationRepository(tmp_path / "nao-existe.md").get_chunks()


def test_crlf_is_normalized_but_text_is_preserved(tmp_path):
    f = tmp_path / "r.md"
    f.write_bytes("## Cap\r\n\r\n**Art. 1.** Texto com acentuação.\r\n".encode())
    [c] = RegulationRepository(f).get_chunks()
    assert c.content == "**Art. 1.** Texto com acentuação." and "\r" not in c.content
