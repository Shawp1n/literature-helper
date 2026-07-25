import pytest

from literature_helper.models import (
    LiteratureMetadata,
    classify_query,
    normalize_query,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10.1038/s41586-024-00001-x", "doi"),
        ("https://doi.org/10.1000/ABC.123", "doi"),
        ("A precise paper title", "title"),
    ],
)
def test_classify_query(value, expected):
    assert classify_query(normalize_query(value)) == expected


def test_normalize_query_whitespace():
    assert normalize_query("  A   paper\n title  ") == "A paper title"


def test_empty_query_rejected():
    with pytest.raises(ValueError):
        normalize_query("   ")


def test_literature_metadata_serializes_for_external_callers():
    literature = LiteratureMetadata(
        title="Example",
        authors=["Author One"],
        publication_date="2023-05-12",
    )

    payload = literature.to_dict()

    assert payload["title"] == "Example"
    assert payload["authors"] == ["Author One"]
    assert payload["publication_year"] == 2023


def test_legacy_internal_enum_is_sanitized_on_read():
    literature = LiteratureMetadata.from_dict(
        {
            "doi": "10.1000/example",
            "journal": "1",
        }
    )

    assert literature.journal is None
