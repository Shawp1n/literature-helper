import sqlite3

from literature_helper.models import LiteratureMetadata, TaskStatus
from literature_helper.storage import TaskStore


def test_task_lifecycle(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("10.1000/example")
    assert task.status == TaskStatus.CREATED
    assert store.active()[0].id == task.id

    updated = store.update(
        task.id,
        TaskStatus.WAITING_FILE,
        message="published",
        request_url="https://www.ablesci.com/assist/detail?id=test",
    )
    assert updated.request_url.endswith("id=test")
    assert len(store.events(task.id)) == 2
    assert not store.publish_attempt_exists(task.query)

    store.update(task.id, TaskStatus.PUBLISHED, message="one shot")
    assert store.publish_attempt_exists(task.query)

    store.update(task.id, TaskStatus.TIMED_OUT, message="timeout")
    assert store.active() == []


def test_validation_json_roundtrip(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("Paper title")
    updated = store.update(
        task.id,
        TaskStatus.DOWNLOADED_PENDING_REVIEW,
        validation={"ok": True, "page_count": 2},
    )
    assert updated.validation == {"ok": True, "page_count": 2}
    assert [item.id for item in store.pending_reviews()] == [task.id]

    store.update(task.id, TaskStatus.CONFIRMED, message="accepted")
    assert store.pending_reviews() == []


def test_literature_metadata_roundtrip(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("10.1000/example")
    literature = LiteratureMetadata(
        title="A structured paper title",
        doi="10.1000/example",
        journal="Journal of Examples",
        authors=["Ada Lovelace", "Alan Turing"],
        publication_date="2024-10-01",
    )

    updated = store.update(
        task.id,
        TaskStatus.READY_TO_PUBLISH,
        literature=literature,
    )

    assert updated.literature is not None
    assert updated.literature.title == "A structured paper title"
    assert updated.literature.authors == ["Ada Lovelace", "Alan Turing"]
    assert updated.to_dict()["literature"]["publication_year"] == 2024


def test_existing_database_is_migrated_for_literature_metadata(tmp_path):
    database = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                query_type TEXT NOT NULL,
                status TEXT NOT NULL,
                request_url TEXT,
                download_path TEXT,
                validation_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    store = TaskStore(database)
    task = store.create("10.1000/migrated")

    assert store.get(task.id).literature is None
    with sqlite3.connect(database) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
    assert "literature_json" in columns


def test_explicit_none_clears_previous_error(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("Recovered paper")
    store.update(task.id, TaskStatus.FAILED, error="old failure")
    recovered = store.update(
        task.id,
        TaskStatus.WAITING_FILE,
        error=None,
    )
    assert recovered.error is None
