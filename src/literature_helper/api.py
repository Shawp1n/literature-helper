"""Stable Python API for embedding the workflow in other applications."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig
from .diagnostics import collect_diagnostics, diagnostics_ok
from .models import AccountPoints, FetchQueueResult, Task, TaskStatus
from .storage import TaskStore
from .workflow import LiteratureWorkflow


__all__ = [
    "AcceptAllResult",
    "AccountPoints",
    "FetchQueueResult",
    "LiteratureHelper",
]


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
        self.config_path = config_path
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

    async def fetch_many(
        self,
        queries: list[str],
        *,
        auto_publish: bool | None = None,
        download_dir: Path | None = None,
        headless: bool | None = None,
        allow_repeat: bool = False,
    ) -> FetchQueueResult:
        """Fetch up to ten items strictly sequentially, stopping on failure."""
        return await self.workflow.run_many(
            queries,
            auto_publish=auto_publish,
            download_dir=download_dir,
            headless=headless,
            allow_repeat=allow_repeat,
        )

    async def account_points(
        self,
        *,
        headless: bool | None = None,
    ) -> AccountPoints:
        """Return the current points for the saved AbleSci login session."""
        return await self.workflow.account_points(headless=headless)

    async def check_in(self) -> AccountPoints:
        """Open AbleSci for a manual daily check-in and return refreshed points."""
        return await self.workflow.check_in()

    async def recharge_points(self) -> AccountPoints:
        """Open AbleSci's official recharge page and return refreshed points."""
        return await self.workflow.recharge_points()

    async def recover(
        self,
        task_id: str | None = None,
        *,
        download_dir: Path | None = None,
        headless: bool | None = None,
    ) -> Task:
        """Resume a request already present on the site's pending list."""
        return await self.workflow.recover(
            task_id,
            download_dir=download_dir,
            headless=self.config.headless if headless is None else headless,
        )

    async def confirm(
        self,
        task_id: str,
        *,
        headless: bool | None = None,
    ) -> Task:
        """Accept one previously downloaded file on the site."""
        return await self.workflow.confirm(
            task_id,
            headless=self.config.headless if headless is None else headless,
        )

    async def accept_all(
        self,
        *,
        headless: bool | None = None,
    ) -> AcceptAllResult:
        """Accept all historical pending files before a later fetch."""
        website_count, local_count = await self.workflow.accept_all_pending(
            headless=self.config.headless if headless is None else headless,
        )
        return AcceptAllResult(
            website_count=website_count,
            local_count=local_count,
        )

    def list_tasks(self, *, limit: int = 20) -> list[Task]:
        """Return recent local task records."""
        return self.store.list(limit=max(1, min(limit, 200)))

    def get_task(self, task_id: str) -> Task:
        """Return one local task as a typed object."""
        return self.store.get(task_id)

    def task_events(self, task_id: str) -> list[dict[str, Any]]:
        """Return the ordered event history for one task."""
        return self.store.events(task_id)

    def task_details(self, task_id: str) -> dict[str, Any]:
        """Return one task and its ordered event history."""
        payload = self.get_task(task_id).to_dict()
        payload["events"] = self.task_events(task_id)
        return payload

    def delete_task(self, task_id: str) -> Task:
        """Delete one local history record without deleting its PDF or site request."""
        return self.store.delete(task_id)

    def has_publish_attempt(self, query: str) -> bool:
        """Return whether this DOI/title has already reached publish boundary."""
        return self.store.publish_attempt_exists(query)

    def diagnostics(self) -> dict[str, Any]:
        """Return deterministic local environment diagnostics."""
        return collect_diagnostics(self.config, config_path=self.config_path)

    def diagnostics_ok(self) -> bool:
        """Return whether the required local runtime dependencies are present."""
        return diagnostics_ok(self.diagnostics())

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
