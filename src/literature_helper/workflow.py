from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from playwright.async_api import BrowserContext, Page, async_playwright

from .adapter import (
    AbleSciAdapter,
    LoginRequired,
    PollTimedOut,
    SiteSelectors,
)
from .config import AppConfig
from .models import LiteratureMetadata, Task, TaskStatus, normalize_query
from .notifier import notify
from .pdfcheck import validate_pdf
from .storage import TaskStore


@dataclass(slots=True)
class WorkflowOptions:
    auto_publish: bool
    download_dir: Path
    headless: bool


class LiteratureWorkflow:
    def __init__(
        self,
        config: AppConfig,
        *,
        output: Callable[[str], None] = print,
        input_func: Callable[[str], str] = input,
    ):
        self.config = config
        self.output = output
        self.input_func = input_func
        self.store = TaskStore(config.database_path)
        self.adapter = AbleSciAdapter(
            selectors=SiteSelectors.load(config.selectors_path),
            assist_url=config.assist_url,
            my_assists_url=config.my_assists_url,
            login_url=config.login_url,
            headless=config.headless,
            debug_dir=config.debug_dir,
            save_debug_artifacts=config.save_debug_artifacts,
            output=output,
            input_func=input_func,
        )

    async def login(
        self,
        *,
        email: str | None = None,
        password: str | None = None,
        headless: bool = True,
    ) -> None:
        if (email is None) != (password is None):
            raise ValueError("email 和 password 必须同时提供")
        self.config.ensure_directories()
        async with async_playwright() as playwright:
            credential_mode = email is not None and password is not None
            self.adapter.headless = headless if credential_mode else False
            context = await self._launch_context(
                playwright,
                headless=headless if credential_mode else False,
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                if credential_mode:
                    await self.adapter.credential_login(
                        page,
                        email=email,
                        password=password,
                    )
                else:
                    await self.adapter.interactive_login(page)
                self.output("登录状态已保存在本地浏览器用户目录。")
            finally:
                await self._safe_close_context(context)

    async def run(
        self,
        query: str,
        *,
        auto_publish: bool | None = None,
        download_dir: Path | None = None,
        headless: bool | None = None,
        allow_repeat: bool = False,
    ) -> Task:
        query = normalize_query(query)
        self.config.ensure_directories()
        active = self.store.active()
        if active:
            identifiers = ", ".join(item.id for item in active)
            raise RuntimeError(
                f"已有未结束任务 ({identifiers})。为避免重复/高频发布，请先处理该任务。"
            )
        pending_reviews = self.store.pending_reviews()
        if pending_reviews and not self.config.auto_accept_historical_pending:
            identifiers = ", ".join(item.id for item in pending_reviews)
            raise RuntimeError(
                f"已有下载后待人工确认的任务 ({identifiers})。"
                "请先检查 PDF 并运行 lithelper confirm TASK_ID，再发布新求助。"
            )
        if not allow_repeat and self.store.publish_attempt_exists(query):
            raise RuntimeError(
                "该 DOI/标题已有发布尝试记录。请先到“我的求助”确认网站状态；"
                "确需再次发布时再显式使用 --allow-repeat-after-checking-site。"
            )

        options = WorkflowOptions(
            auto_publish=self.config.auto_publish if auto_publish is None else auto_publish,
            download_dir=(download_dir or self.config.download_dir).expanduser().resolve(),
            headless=self.config.headless if headless is None else headless,
        )
        self.adapter.headless = options.headless
        task = self.store.create(query)
        self.output(f"任务 {task.id} 已创建（{task.query_type.upper()}）")
        if task.query_type == "title":
            self.output(
                "提示：仅标题求助前请确认标题准确且能唯一对应文献；科研通规则建议优先使用 DOI。"
            )

        page: Page | None = None
        context: BrowserContext | None = None
        try:
            async with async_playwright() as playwright:
                context = await self._launch_context(playwright, headless=options.headless)
                page = context.pages[0] if context.pages else await context.new_page()
                try:
                    await self.adapter.open_assist(page)
                except LoginRequired:
                    self.store.update(
                        task.id,
                        TaskStatus.WAITING_LOGIN,
                        message="等待用户登录",
                    )
                    await self.adapter.interactive_login(page)
                page, accepted_count = await self.adapter.ensure_no_historical_pending(
                    page,
                    auto_accept=self.config.auto_accept_historical_pending,
                )
                if self.config.auto_accept_historical_pending:
                    for pending_task in pending_reviews:
                        self.store.update(
                            pending_task.id,
                            TaskStatus.CONFIRMED,
                            message="已批量同步科研通历史待确认采纳状态",
                            error=None,
                        )
                    if accepted_count:
                        self.output(
                            f"历史待确认处理完成：共自动采纳 {accepted_count} 条。"
                        )

                self.store.update(
                    task.id,
                    TaskStatus.MATCHING,
                    message="正在输入并匹配文献",
                )
                prepared = await self.adapter.prepare_request(page, query)
                self.store.update(
                    task.id,
                    TaskStatus.READY_TO_PUBLISH,
                    message="文献信息已匹配，发布按钮可用",
                    request_url=page.url,
                    literature=prepared.literature,
                )

                if not options.auto_publish:
                    self.output("已停在发布前确认页面；请检查信息。")
                    if options.headless:
                        raise RuntimeError("无头模式不能使用人工发布确认")
                    await asyncio.to_thread(
                        self.input_func,
                        "确认无误后请在浏览器中手动发布，并点击“查看求助详情”，"
                        "进入详情后按 Enter… ",
                    )
                    if context.pages:
                        page = context.pages[-1]
                    request_url = page.url
                else:
                    # The state is advanced before the single click. Even if navigation
                    # becomes uncertain, this workflow will never retry and duplicate a post.
                    self.store.update(
                        task.id,
                        TaskStatus.PUBLISHED,
                        message="准备单次点击发布；之后不会自动重试",
                        request_url=page.url,
                    )
                    outcome = await self.adapter.click_publish_once(
                        page,
                        prepared.publish_button,
                    )
                    page = outcome.page
                    request_url = outcome.request_url
                    if not outcome.verified:
                        self.output(
                            "未从页面标记确认发布结果；为避免重复发帖，不会再次点击，将继续观察当前求助页。"
                        )

                literature = prepared.literature
                try:
                    detail_literature = (
                        await self.adapter.extract_literature_metadata(page, query)
                    )
                    literature = _merge_literature(
                        prepared.literature,
                        detail_literature,
                    )
                except Exception as exc:
                    self.output(
                        "求助详情中的文献信息补全未完成，"
                        f"将保留发布前结果（{type(exc).__name__}）。"
                    )

                self.store.update(
                    task.id,
                    TaskStatus.WAITING_FILE,
                    message="求助已发布，开始等待应助文件",
                    request_url=request_url,
                    literature=literature,
                )
                self.output(
                    f"已发布，{self.config.initial_poll_delay_seconds:g} 秒后开始检查应助状态。"
                )

                async def on_poll(count: int) -> None:
                    self.output(f"第 {count} 次检查：尚未发现下载入口")

                link = await self.adapter.wait_for_download(
                    page,
                    initial_delay_seconds=self.config.initial_poll_delay_seconds,
                    interval_seconds=self.config.poll_interval_seconds,
                    timeout_seconds=self.config.poll_timeout_seconds,
                    on_poll=on_poll,
                )
                return await self._download_and_validate(
                    task,
                    page,
                    link,
                    download_dir=options.download_dir,
                )
        except asyncio.CancelledError:
            self.store.update(
                task.id,
                TaskStatus.CANCELLED,
                message="用户中止了本地工作流；程序未关闭网站上的求助",
                request_url=page.url if page else None,
            )
            raise
        except PollTimedOut as exc:
            task = self.store.update(
                task.id,
                TaskStatus.TIMED_OUT,
                message=str(exc),
                request_url=page.url if page else None,
                error=str(exc),
            )
            notify("科研通求助仍在等待", f"任务 {task.id} 暂未收到文件。")
            if page is not None:
                await self._capture_and_report(page, task.id)
            return task
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            task = self.store.update(
                task.id,
                TaskStatus.FAILED,
                message="工作流执行失败",
                request_url=page.url if page else None,
                error=error,
            )
            if page is not None:
                await self._capture_and_report(page, task.id)
            notify("科研通工作流失败", f"任务 {task.id}: {str(exc)[:120]}")
            raise
        finally:
            if context is not None:
                await self._safe_close_context(context)

    async def recover(
        self,
        task_id: str | None = None,
        *,
        download_dir: Path | None = None,
        headless: bool = False,
    ) -> Task:
        self.config.ensure_directories()
        self.adapter.headless = headless
        task = self.store.get(task_id) if task_id else None
        if task is not None and task.status == TaskStatus.DOWNLOADED_PENDING_REVIEW:
            raise ValueError(
                f"任务 {task.id} 已下载完成，无需恢复；"
                "下次 fetch 会自动处理，也可运行 lithelper accept-all"
            )
        if task is not None and task.status in {
            TaskStatus.CONFIRMED,
            TaskStatus.REJECTED,
        }:
            raise ValueError(f"任务 {task.id} 已结束，不能恢复")

        target_dir = (download_dir or self.config.download_dir).expanduser().resolve()
        page: Page | None = None
        context: BrowserContext | None = None
        try:
            async with async_playwright() as playwright:
                context = await self._launch_context(playwright, headless=headless)
                page = context.pages[0] if context.pages else await context.new_page()
                try:
                    detail_page, row_text = await self.adapter.open_pending_request(
                        page,
                        preferred_query=task.query if task else None,
                    )
                except LoginRequired:
                    await self.adapter.interactive_login(page)
                    detail_page, row_text = await self.adapter.open_pending_request(
                        page,
                        preferred_query=task.query if task else None,
                    )
                page = detail_page

                if task is None:
                    task = self.store.create(row_text[:1_000])
                    self.output(f"已为网站历史求助创建恢复任务：{task.id}")
                recovered_literature = (
                    await self.adapter.extract_literature_metadata(
                        page,
                        task.query,
                    )
                )
                task = self.store.update(
                    task.id,
                    TaskStatus.WAITING_FILE,
                    message="已从科研通待确认列表恢复既有求助；不会再次发布",
                    request_url=page.url,
                    literature=_merge_literature(
                        task.literature,
                        recovered_literature,
                    ),
                    error=None,
                )
                link = await self.adapter.wait_for_download(
                    page,
                    initial_delay_seconds=0,
                    interval_seconds=self.config.poll_interval_seconds,
                    timeout_seconds=min(self.config.poll_timeout_seconds, 60),
                )
                return await self._download_and_validate(
                    task,
                    page,
                    link,
                    download_dir=target_dir,
                )
        except Exception as exc:
            if task is not None:
                task = self.store.update(
                    task.id,
                    TaskStatus.FAILED,
                    message="恢复既有求助失败；未发布新求助",
                    request_url=page.url if page else None,
                    error=f"{type(exc).__name__}: {exc}",
                )
                if page is not None:
                    await self._capture_and_report(page, task.id)
            raise
        finally:
            if context is not None:
                await self._safe_close_context(context)

    async def confirm(self, task_id: str, *, headless: bool = False) -> Task:
        self.config.ensure_directories()
        self.adapter.headless = headless
        task = self.store.get(task_id)
        if task.status != TaskStatus.DOWNLOADED_PENDING_REVIEW:
            raise ValueError(
                f"任务状态为 {task.status.value}，只有 downloaded_pending_review 可确认"
            )
        if task.download_path is None or not task.download_path.is_file():
            raise ValueError("本地 PDF 不存在，不能执行网站采纳")
        if not task.request_url:
            raise ValueError("任务没有记录求助详情地址，不能自动采纳")

        page: Page | None = None
        context: BrowserContext | None = None
        try:
            async with async_playwright() as playwright:
                context = await self._launch_context(playwright, headless=headless)
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(
                    task.request_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                if await self.adapter.is_login_page(page):
                    await self.adapter.interactive_login(page)
                    await page.goto(
                        task.request_url,
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                await self.adapter.accept_uploaded_file(page)
                return self.store.update(
                    task.id,
                    TaskStatus.CONFIRMED,
                    message="已同步点击网站“采纳文件”",
                    request_url=page.url,
                )
        except Exception as exc:
            if page is not None:
                await self._capture_and_report(page, task.id)
            self.store.update(
                task.id,
                TaskStatus.DOWNLOADED_PENDING_REVIEW,
                message="同步网站采纳失败，保留待确认状态",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        finally:
            if context is not None:
                await self._safe_close_context(context)

    async def accept_all_pending(self, *, headless: bool = False) -> tuple[int, int]:
        self.config.ensure_directories()
        self.adapter.headless = headless
        local_pending = self.store.pending_reviews()
        context: BrowserContext | None = None
        page: Page | None = None
        try:
            async with async_playwright() as playwright:
                context = await self._launch_context(playwright, headless=headless)
                page = context.pages[0] if context.pages else await context.new_page()
                try:
                    page, website_count = (
                        await self.adapter.ensure_no_historical_pending(
                            page,
                            auto_accept=True,
                        )
                    )
                except LoginRequired:
                    await self.adapter.interactive_login(page)
                    page, website_count = (
                        await self.adapter.ensure_no_historical_pending(
                            page,
                            auto_accept=True,
                        )
                    )
                for task in local_pending:
                    self.store.update(
                        task.id,
                        TaskStatus.CONFIRMED,
                        message="已批量同步科研通历史待确认采纳状态",
                        error=None,
                    )
                return website_count, len(local_pending)
        except Exception:
            if page is not None:
                paths = await self.adapter.capture_debug(page, "accept-all")
                if paths:
                    self.output(
                        "已保存批量采纳诊断文件："
                        + "，".join(str(path) for path in paths)
                    )
            raise
        finally:
            if context is not None:
                await self._safe_close_context(context)

    async def _download_and_validate(
        self,
        task: Task,
        page: Page,
        link,
        *,
        download_dir: Path,
    ) -> Task:
        task = self.store.update(
            task.id,
            TaskStatus.DOWNLOADING,
            message="发现应助文件，开始下载",
            request_url=page.url,
        )
        path = await self.adapter.download(
            page,
            link,
            download_dir=download_dir,
            filename_hint=_filename_hint(task.query),
            prefer_high_speed=self.config.prefer_high_speed_download,
            download_timeout_seconds=self.config.download_timeout_seconds,
        )
        report = validate_pdf(
            path,
            minimum_bytes=self.config.minimum_pdf_bytes,
        )
        status = (
            TaskStatus.DOWNLOADED_PENDING_REVIEW
            if report.ok
            else TaskStatus.FAILED
        )
        message = (
            "PDF 基础检查通过；本次保留待确认，下次 fetch 前自动批量采纳"
            if report.ok
            else "下载完成，但 PDF 基础检查未通过"
        )
        task = self.store.update(
            task.id,
            status,
            message=message,
            download_path=path,
            validation=report.to_dict(),
            error=report.error if not report.ok else None,
        )
        if report.ok:
            self.output(f"PDF 已下载并通过基础检查：{path}")
            if self.config.auto_accept_after_validation:
                try:
                    if page.is_closed():
                        raise RuntimeError("下载完成后浏览器页面已关闭")
                    if not task.request_url:
                        raise RuntimeError("任务缺少求助详情地址")
                    await page.goto(
                        task.request_url,
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                    await self.adapter.accept_uploaded_file(page)
                    task = self.store.update(
                        task.id,
                        TaskStatus.CONFIRMED,
                        message="PDF 基础检查通过，已自动同步网站采纳",
                        request_url=page.url,
                        error=None,
                    )
                    notify(
                        "科研通文献已下载并采纳",
                        f"{path.name}（{report.page_count} 页）",
                    )
                    self.output("PDF 基础检查通过，已自动点击网站“采纳文件”。")
                except Exception as exc:
                    task = self.store.update(
                        task.id,
                        TaskStatus.DOWNLOADED_PENDING_REVIEW,
                        message="PDF 已下载，但自动采纳失败",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    notify(
                        "科研通文献已下载",
                        f"{path.name} 已保存，但自动采纳失败。",
                    )
                    self.output(
                        f"自动采纳失败，文件不受影响；可稍后运行 "
                        f"lithelper confirm {task.id}。"
                    )
            else:
                notify(
                    "科研通文献已下载",
                    f"{path.name}（{report.page_count} 页）；下次求助前将自动采纳。",
                )
                self.output(
                    "本次不立即采纳；下次运行 fetch 时会先批量采纳历史待确认，"
                    "也可随时运行 lithelper accept-all。"
                )
        else:
            notify("科研通文件检查失败", f"{path.name} 需要人工检查。")
            self.output(f"文件已保留，但基础检查失败：{path}")
        return task

    async def _safe_close_context(self, context: BrowserContext) -> None:
        try:
            await context.close()
        except Exception as exc:
            message = str(exc).casefold()
            if "closed" in message or "target page" in message:
                return
            self.output(f"浏览器清理未完成，但任务结果已保留：{exc}")

    async def _capture_and_report(self, page: Page, task_id: str) -> None:
        paths = await self.adapter.capture_debug(page, task_id)
        if paths:
            self.output("已保存本地诊断文件：" + "，".join(str(path) for path in paths))

    async def _launch_context(self, playwright, *, headless: bool | None = None):
        kwargs = {
            "user_data_dir": str(self.config.profile_dir),
            "headless": self.config.headless if headless is None else headless,
            "accept_downloads": True,
            "slow_mo": self.config.slow_mo_ms,
            "viewport": {"width": 1360, "height": 900},
        }
        if self.config.browser_channel:
            kwargs["channel"] = self.config.browser_channel
        return await playwright.chromium.launch_persistent_context(**kwargs)


def _filename_hint(query: str) -> str:
    cleaned = query.replace("/", "_").replace("\\", "_")
    cleaned = " ".join(cleaned.split()).strip(" .")
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip()
    return f"{cleaned or 'paper'}.pdf"


def _merge_literature(
    earlier: LiteratureMetadata | None,
    later: LiteratureMetadata | None,
) -> LiteratureMetadata | None:
    """Prefer stable detail-page fields while retaining earlier extraction."""
    if earlier is None:
        return later
    if later is None:
        return earlier
    return LiteratureMetadata(
        title=later.title or earlier.title,
        doi=later.doi or earlier.doi,
        url=later.url or earlier.url,
        journal=later.journal or earlier.journal,
        authors=later.authors or earlier.authors,
        publication_date=later.publication_date or earlier.publication_date,
        source=later.source or earlier.source,
        extracted_at=later.extracted_at or earlier.extracted_at,
    )
