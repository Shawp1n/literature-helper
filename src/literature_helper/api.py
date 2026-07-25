"""Stable Python API for embedding the workflow in other applications."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig
from .models import Task, TaskStatus
from .storage import TaskStore
from .workflow import LiteratureWorkflow


__all__ = ["AcceptAllResult", "LiteratureHelper", "Keyantong"]


@dataclass(frozen=True, slots=True)
class AcceptAllResult:
    website_count: int
    local_count: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class LiteratureHelper:
    """Small application facade shared by the CLI and programmatic callers."""

    def __init__(
        self,
        config: AppConfig | None = None,
        *,
        config_path: Path | None = None,
        output: Callable[[str], None] | None = None,
        input_func: Callable[[str], str] = input,
    ):
        if config is not None and config_path is not None:
            raise ValueError("config 和 config_path 不能同时提供")
        self.config = config or AppConfig.load(config_path)
        self.output = output or (lambda _message: None)
        self.workflow = LiteratureWorkflow(
            self.config,
            output=self.output,
            input_func=input_func,
        )
        self.store: TaskStore = self.workflow.store

    async def login(
        self,
        *,
        email: str | None = None,
        password: str | None = None,
        headless: bool = True,
    ) -> None:
        """Create a reusable site session without retaining the password."""
        await self.workflow.login(
            email=email,
            password=password,
            headless=headless,
        )

    async def fetch(
        self,
        query: str,
        *,
        auto_publish: bool | None = None,
        download_dir: Path | None = None,
        headless: bool | None = None,
        allow_repeat: bool = False,
    ) -> Task:
        """Publish one request, wait for an upload, and return its task record."""
        return await self.workflow.run(
            query,
            auto_publish=auto_publish,
            download_dir=download_dir,
            headless=headless,
            allow_repeat=allow_repeat,
        )

    async def recover(
        self,
        task_id: str | None = None,
        *,
        download_dir: Path | None = None,
        headless: bool = False,
    ) -> Task:
        """Resume a request already present on the site's pending list."""
        return await self.workflow.recover(
            task_id,
            download_dir=download_dir,
            headless=headless,
        )

    async def confirm(self, task_id: str, *, headless: bool = False) -> Task:
        """Accept one previously downloaded file on the site."""
        return await self.workflow.confirm(task_id, headless=headless)

    async def accept_all(self, *, headless: bool = False) -> AcceptAllResult:
        """Accept all historical pending files before a later fetch."""
        website_count, local_count = await self.workflow.accept_all_pending(
            headless=headless,
        )
        return AcceptAllResult(
            website_count=website_count,
            local_count=local_count,
        )

    def list_tasks(self, *, limit: int = 20) -> list[Task]:
        """Return recent local task records."""
        return self.store.list(limit=max(1, min(limit, 200)))

    def task_details(self, task_id: str) -> dict[str, Any]:
        """Return one task and its ordered event history."""
        payload = self.store.get(task_id).to_dict()
        payload["events"] = self.store.events(task_id)
        return payload

    def reject(self, task_id: str, *, reason: str) -> Task:
        """Mark a local download as rejected without changing the website."""
        task = self.store.get(task_id)
        if task.status != TaskStatus.DOWNLOADED_PENDING_REVIEW:
            raise ValueError(
                f"任务状态为 {task.status.value}，"
                "只有 downloaded_pending_review 可标记有误"
            )
        return self.store.update(
            task.id,
            TaskStatus.REJECTED,
            message="用户将本地文件标记为有误；未自动操作网站",
            error=reason,
        )

    def cancel(self, task_id: str) -> Task:
        """Release a local active-task lock without changing the website."""
        task = self.store.get(task_id)
        if task.status not in {
            TaskStatus.CREATED,
            TaskStatus.WAITING_LOGIN,
            TaskStatus.MATCHING,
            TaskStatus.READY_TO_PUBLISH,
            TaskStatus.PUBLISHED,
            TaskStatus.WAITING_FILE,
            TaskStatus.DOWNLOADING,
        }:
            raise ValueError(f"任务状态为 {task.status.value}，不是活动任务")
        return self.store.update(
            task.id,
            TaskStatus.CANCELLED,
            message="用户取消了本地任务；未自动关闭科研通网站上的求助",
        )


# 0.x compatibility for callers using the former public class name.
Keyantong = LiteratureHelper
