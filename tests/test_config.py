import pytest

from reality_layer.config import Settings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            "postgres://u:p@host:5432/db",
            "postgresql+psycopg://u:p@host:5432/db",
        ),
        (
            "postgresql://u:p@host/db",
            "postgresql+psycopg://u:p@host/db",
        ),
        (
            "postgresql+psycopg://u:p@host/db",
            "postgresql+psycopg://u:p@host/db",
        ),
    ],
)
def test_database_url_is_pinned_to_psycopg_v3(given: str, expected: str) -> None:
    assert Settings(database_url=given).database_url == expected
