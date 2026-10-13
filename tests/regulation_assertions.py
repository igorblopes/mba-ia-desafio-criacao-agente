"""Asserções conservadoras de fundamentação; não substituem avaliação semântica."""
import re


def assert_unsupported_answer(text: str) -> None:
    assert re.search(r"n[ãa]o (?:encontr|localiz)|n[ãa]o (?:há|ha|consta)", text, re.I), text
    # Reconhecer ausência não pode anular a detecção de uma regra inventada depois.
    assert not re.search(
        r"\b(?:permitid\w*|proibid\w*|autorizad\w*|vedad\w*|"
        r"pode(?:m)?|deve(?:m)?|precisa\w*|obrigat[oó]ri\w*|multa\w*)\b|\d",
        text, re.I,
    ), text
