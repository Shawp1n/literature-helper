from unittest.mock import AsyncMock

import pytest

from literature_helper import AppConfig, LiteratureHelper, TaskStatus
from literature_helper.api import AcceptAllResult


def test_public_api_exposes_structured_task_access(tmp_path):
    app = LiteratureHelper(config=AppConfig.defaults(tmp_path / "app"))
    task = app.store.create("10.1000/example")

    assert app.list_tasks()[0].id == task.id
    details = app.task_details(task.id)
    assert details["id"] == task.id
    assert details["events"][0]["status"] == TaskStatus.CREATED.value


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


def test_accept_all_result_is_machine_readable():
    result = AcceptAllResult(website_count=2, local_count=3)

    assert result.to_dict() == {
        "website_count": 2,
        "local_count": 3,
    }


def test_legacy_python_name_remains_compatible():
    from keyantong_helper import Keyantong
    from keyantong_helper.models import TaskStatus as LegacyTaskStatus

    assert Keyantong is LiteratureHelper
    assert LegacyTaskStatus is TaskStatus
