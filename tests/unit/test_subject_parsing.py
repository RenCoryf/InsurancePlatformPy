import pytest

from app.api.deps.subject_auth import Subject, parse_subject_claim


def test_parses_user_subject():
    assert parse_subject_claim("user:42") == Subject(type="user", id=42)


def test_parses_support_subject():
    assert parse_subject_claim("support:7") == Subject(type="support", id=7)


@pytest.mark.parametrize("bad", ["", "user:", ":42", "user:abc", "admin:1", "user:42:extra"])
def test_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_subject_claim(bad)
