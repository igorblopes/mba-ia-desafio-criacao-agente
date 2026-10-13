import pytest
from tests.regulation_assertions import assert_unsupported_answer


def test_explicit_absence_is_accepted():
    assert_unsupported_answer("Não encontrei essa informação no regulamento disponível.")


@pytest.mark.parametrize("claim", [
    "É proibido pousar na piscina.", "É permitido pousar.",
    "Você pode pousar com autorização.", "A multa é de 500 reais.",
])
def test_absence_followed_by_invented_rule_is_rejected(claim):
    with pytest.raises(AssertionError):
        assert_unsupported_answer("Não encontrei essa informação. " + claim)
