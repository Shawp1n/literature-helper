import pytest

from literature_helper.models import (
    MAX_FETCH_QUEUE_ITEMS,
    FetchQueueResult,
    LiteratureMetadata,
    classify_query,
    normalize_queries,
    normalize_query,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10.1038/s41586-024-00001-x", "doi"),
        ("https://doi.org/10.1000/ABC.123", "doi"),
        ("doi.org/10.1000/ABC.123", "doi"),
        ("http://dx.doi.org/10.1000/ABC.123", "doi"),
        ("A precise paper title", "title"),
    ],
)
def test_classify_query(value, expected):
    assert classify_query(normalize_query(value)) == expected


def test_normalize_query_whitespace():
    assert normalize_query("  A   paper\n title  ") == "A paper title"
    assert normalize_query(" doi.org/10.1000/EXAMPLE ") == "10.1000/EXAMPLE"


def test_empty_query_rejected():
    with pytest.raises(ValueError):
        normalize_query("   ")


def test_fetch_queue_normalizes_items_and_rejects_duplicates():
    assert normalize_queries(
        [" 10.1000/ONE ", "A   precise title"]
    ) == ["10.1000/ONE", "A precise title"]

    with pytest.raises(ValueError, match="重复项"):
        normalize_queries(["10.1000/ONE", "10.1000/one"])


def test_fetch_queue_has_a_small_hard_limit():
    with pytest.raises(ValueError, match=str(MAX_FETCH_QUEUE_ITEMS)):
        normalize_queries(
            [f"10.1000/example-{index}" for index in range(MAX_FETCH_QUEUE_ITEMS + 1)]
        )


def test_empty_fetch_queue_rejected():
    with pytest.raises(ValueError, match="不能为空"):
        normalize_queries([])


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


def test_fetch_queue_result_is_machine_readable(tmp_path):
    from literature_helper.config import AppConfig
    from literature_helper.storage import TaskStore

    store = TaskStore(AppConfig.defaults(tmp_path / "app").database_path)
    task = store.create("10.1000/example")
    task.status = task.status.DOWNLOADED_PENDING_REVIEW
    result = FetchQueueResult(
        queries=[task.query],
        tasks=[task],
    )

    payload = result.to_dict()

    assert payload["completed"] is True
    assert payload["successful_count"] == 1
    assert payload["tasks"][0]["id"] == task.id
