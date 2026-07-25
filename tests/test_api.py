from unittest.mock import AsyncMock

import pytest

from literature_helper import (
    AccountPoints,
    AppConfig,
    FetchQueueResult,
    LiteratureHelper,
    TaskStatus,
)
from literature_helper.api import AcceptAllResult


def test_public_api_exposes_structured_task_access(tmp_path):
    app = LiteratureHelper(config=AppConfig.defaults(tmp_path / "app"))
    task = app.store.create("10.1000/example")

    assert app.list_tasks()[0].id == task.id
    assert app.get_task(task.id).id == task.id
    assert app.task_events(task.id)[0]["status"] == TaskStatus.CREATED.value
    details = app.task_details(task.id)
    assert details["id"] == task.id
    assert details["events"][0]["status"] == TaskStatus.CREATED.value


def test_public_api_deletes_only_the_local_task_record(tmp_path):
    app = LiteratureHelper(config=AppConfig.defaults(tmp_path / "app"))
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    task = app.store.create("10.1000/example")
    task = app.store.update(
        task.id,
        TaskStatus.DOWNLOADED_PENDING_REVIEW,
        download_path=pdf,
    )

    deleted = app.delete_task(task.id)

    assert deleted.id == task.id
    assert pdf.exists()
    with pytest.raises(KeyError):
        app.get_task(task.id)


def test_public_api_exposes_duplicate_and_diagnostic_queries(tmp_path):
    config = AppConfig.defaults(tmp_path / "app")
    app = LiteratureHelper(config=config)

    assert app.has_publish_attempt("10.1000/example") is False
    checks = app.diagnostics()
    assert checks["data_dir"] == str(config.data_dir)
    assert isinstance(app.diagnostics_ok(), bool)


@pytest.mark.asyncio
async def test_public_fetch_delegates_to_workflow(tmp_path):
    app = LiteratureHelper(config=AppConfig.defaults(tmp_path / "app"))
    task = app.store.create("10.1000/example")
    app.workflow.run = AsyncMock(return_value=task)

    result = await app.fetch("10.1000/example", headless=True)

    assert result is task
    app.workflow.run.assert_awaited_once_with(
        "10.1000/example",
        auto_publish=None,
        download_dir=None,
        headless=True,
        allow_repeat=False,
    )


@pytest.mark.asyncio
async def test_public_fetch_many_delegates_to_workflow(tmp_path):
    app = LiteratureHelper(config=AppConfig.defaults(tmp_path / "app"))
    result = FetchQueueResult(queries=["10.1000/one", "10.1000/two"])
    app.workflow.run_many = AsyncMock(return_value=result)

    actual = await app.fetch_many(
        result.queries,
        headless=True,
    )

    assert actual is result
    app.workflow.run_many.assert_awaited_once_with(
        result.queries,
        auto_publish=None,
        download_dir=None,
        headless=True,
        allow_repeat=False,
    )


@pytest.mark.asyncio
async def test_public_account_points_delegates_to_workflow(tmp_path):
    app = LiteratureHelper(config=AppConfig.defaults(tmp_path / "app"))
    points = AccountPoints(total=42)
    app.workflow.account_points = AsyncMock(return_value=points)

    result = await app.account_points(headless=True)

    assert result is points
    app.workflow.account_points.assert_awaited_once_with(headless=True)


@pytest.mark.asyncio
async def test_public_manual_points_actions_delegate_to_workflow(tmp_path):
    app = LiteratureHelper(config=AppConfig.defaults(tmp_path / "app"))
    points = AccountPoints(total=52)
    app.workflow.check_in = AsyncMock(return_value=points)
    app.workflow.recharge_points = AsyncMock(return_value=points)

    assert await app.check_in() is points
    assert await app.recharge_points() is points
    app.workflow.check_in.assert_awaited_once_with()
    app.workflow.recharge_points.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_public_recover_can_be_agent_headless(tmp_path):
    app = LiteratureHelper(config=AppConfig.defaults(tmp_path / "app"))
    task = app.store.create("10.1000/example")
    app.workflow.recover = AsyncMock(return_value=task)

    result = await app.recover(task.id, headless=True)

    assert result is task
    app.workflow.recover.assert_awaited_once_with(
        task.id,
        download_dir=None,
        headless=True,
    )


@pytest.mark.asyncio
async def test_site_actions_follow_configured_headless_default(tmp_path):
    config = AppConfig.defaults(tmp_path / "app")
    config.headless = True
    app = LiteratureHelper(config=config)
    task = app.store.create("10.1000/example")
    app.workflow.recover = AsyncMock(return_value=task)
    app.workflow.confirm = AsyncMock(return_value=task)
    app.workflow.accept_all_pending = AsyncMock(return_value=(1, 1))

    await app.recover(task.id)
    await app.confirm(task.id)
    result = await app.accept_all()

    app.workflow.recover.assert_awaited_once_with(
        task.id,
        download_dir=None,
        headless=True,
    )
    app.workflow.confirm.assert_awaited_once_with(task.id, headless=True)
    app.workflow.accept_all_pending.assert_awaited_once_with(headless=True)
    assert result == AcceptAllResult(website_count=1, local_count=1)


def test_accept_all_result_is_machine_readable():
    result = AcceptAllResult(website_count=2, local_count=3)

    assert result.to_dict() == {
        "website_count": 2,
        "local_count": 3,
    }
