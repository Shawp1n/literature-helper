from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import unquote, urljoin, urlparse

from playwright.async_api import (
    BrowserContext,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from .models import AccountPoints, LiteratureMetadata, classify_query


class SiteAdapterError(RuntimeError):
    pass


class LoginRequired(SiteAdapterError):
    pass


class PageStructureChanged(SiteAdapterError):
    pass


class PublishUncertain(SiteAdapterError):
    pass


class PollTimedOut(SiteAdapterError):
    pass


class PendingReviewRequired(SiteAdapterError):
    pass


@dataclass(slots=True)
class SiteSelectors:
    login_email_inputs: list[str] = field(
        default_factory=lambda: [
            "#LAY-user-login-email",
            'input[name="email"]',
            'input[placeholder="邮箱"]',
        ]
    )
    login_password_inputs: list[str] = field(
        default_factory=lambda: [
            "#LAY-user-login-password",
            'input[name="password"]',
            'input[type="password"]',
        ]
    )
    login_remember_inputs: list[str] = field(
        default_factory=lambda: [
            'input[name="remember"]',
        ]
    )
    login_submit_buttons: list[str] = field(
        default_factory=lambda: [
            '#login-form button[type="submit"]',
            '#login-form button:has-text("登 录")',
            'button:has-text("登录")',
        ]
    )
    login_error_markers: list[str] = field(
        default_factory=lambda: [
            '.layui-layer-content',
            '.help-block',
            '.alert-danger',
            'text=/邮箱或密码.*(?:错误|不正确)/',
            'text=/登录失败/',
        ]
    )
    account_points_values: list[str] = field(
        default_factory=lambda: [
            'div:has-text("您当前的总积分为") span.text-bold.text-danger',
            'div:has-text("您当前的总积分为") span',
        ]
    )
    query_inputs: list[str] = field(
        default_factory=lambda: [
            'input[placeholder*="DOI"]',
            'textarea[placeholder*="DOI"]',
            'input[placeholder*="doi"]',
            'textarea[placeholder*="doi"]',
            'input[placeholder*="标题"]',
            'textarea[placeholder*="标题"]',
            'input[name="doi"]',
            'input[name="keyword"]',
            'input[name="query"]',
            'textarea[name="title"]',
        ]
    )
    intelligent_extract_buttons: list[str] = field(
        default_factory=lambda: [
            'button:has-text("智能提取文献信息")',
            'a:has-text("智能提取文献信息")',
            'input[type="button"][value*="智能提取文献信息"]',
            'input[type="submit"][value*="智能提取文献信息"]',
            'text="智能提取文献信息"',
        ]
    )
    extracted_publish_buttons: list[str] = field(
        default_factory=lambda: [
            'button:has-text("信息正确，直接发布")',
            'a:has-text("信息正确，直接发布")',
            'input[type="button"][value*="信息正确，直接发布"]',
            'input[type="submit"][value*="信息正确，直接发布"]',
            'text="信息正确，直接发布"',
        ]
    )
    lookup_buttons: list[str] = field(
        default_factory=lambda: [
            'button:has-text("查询")',
            'button:has-text("智能识别")',
            'button:has-text("开始识别")',
            'button:has-text("搜索")',
            'input[type="button"][value*="查询"]',
        ]
    )
    result_items: list[str] = field(
        default_factory=lambda: [
            '[data-paper-id]',
            ".paper-card",
            ".paper-item",
            ".search-result-item",
            '[role="option"]',
        ]
    )
    confirm_buttons: list[str] = field(
        default_factory=lambda: [
            'button:has-text("确认文献")',
            'button:has-text("确认信息")',
            'button:has-text("使用此文献")',
            'button:has-text("下一步")',
        ]
    )
    publish_buttons: list[str] = field(
        default_factory=lambda: [
            'button:has-text("立即发布")',
            'button:has-text("发布求助")',
            'input[type="submit"][value*="立即发布"]',
            'input[type="submit"][value*="发布求助"]',
        ]
    )
    success_markers: list[str] = field(
        default_factory=lambda: [
            'text="发布成功"',
            'text="等待应助"',
            'text="求助详情"',
            'text="已发布"',
        ]
    )
    post_publish_detail_buttons: list[str] = field(
        default_factory=lambda: [
            'button:has-text("查看求助详情")',
            'a:has-text("查看求助详情")',
            'input[value*="查看求助详情"]',
            'text="查看求助详情"',
        ]
    )
    upload_notice_markers: list[str] = field(
        default_factory=lambda: [
            'text="恭喜您，已经有人上传了文件，请在 48 小时内查看并审核。"',
            'text=/已经有人上传了文件.*48\\s*小时内查看并审核/',
        ]
    )
    upload_notice_confirm_buttons: list[str] = field(
        default_factory=lambda: [
            '.layui-layer:has-text("已经有人上传了文件") .layui-layer-btn0',
            '[role="dialog"]:has-text("已经有人上传了文件") button:has-text("确定")',
            '[role="dialog"]:has-text("已经有人上传了文件") a:has-text("确定")',
            'div:has-text("已经有人上传了文件") button:has-text("确定")',
        ]
    )
    download_links: list[str] = field(
        default_factory=lambda: [
            'a:has-text(".pdf")',
            'a:has-text("下载应助文件")',
            'a:has-text("下载文件")',
            'button:has-text("下载应助文件")',
            'a[href*="/assist/download"]',
            'a[href*="/download/"]',
            'a[href*="/attachment/"]',
            'a[href*=".pdf"]',
            'a[href$=".pdf"]',
        ]
    )
    high_speed_channels: list[str] = field(
        default_factory=lambda: [
            "#download-highspeed-direct",
            "button.download-progress-highspeed-button",
            "button[data-highspeed-action]",
            "#download-switch-vip",
            'button:has-text("高速通道")',
            'a:has-text("高速通道")',
            '[role="button"]:has-text("高速通道")',
            'text=/高速通道/',
            'text="高速通道"',
        ]
    )
    normal_download_channels: list[str] = field(
        default_factory=lambda: [
            'button:has-text("线路")',
            'a:has-text("线路")',
            '[role="button"]:has-text("线路")',
            'text=/^线路\\d+$/',
        ]
    )
    pending_review_markers: list[str] = field(
        default_factory=lambda: [
            'text=/请先.*确认.*求助/',
            'text=/存在.*待确认/',
            'text=/有.*待确认.*求助/',
            'text=/先确认.*才能下载/',
        ]
    )
    pending_review_tabs: list[str] = field(
        default_factory=lambda: [
            'button:has-text("待确认")',
            'a:has-text("待确认")',
            '[role="tab"]:has-text("待确认")',
            'text="待确认"',
        ]
    )
    pending_review_rows: list[str] = field(
        default_factory=lambda: [
            'tbody tr:has-text("待确认")',
            'table tr:has-text("待确认")',
            'tr:has-text("待确认")',
            '[role="row"]:has-text("待确认")',
        ]
    )
    accept_file_buttons: list[str] = field(
        default_factory=lambda: [
            'button:has-text("采纳文件")',
            'a:has-text("采纳文件")',
            'input[value*="采纳文件"]',
            'text="采纳文件"',
        ]
    )
    accept_confirmation_buttons: list[str] = field(
        default_factory=lambda: [
            '.layui-layer:has-text("确认接受应助吗") .layui-layer-btn0',
            '.layui-layer:has-text("接受应助") .layui-layer-btn0',
            '.layui-layer:has-text("确认接受应助吗") a:has-text("确定")',
            '.layui-layer-btn a.layui-layer-btn0',
            '.modal:has-text("确认接受应助吗") button:has-text("确定")',
            '.modal-dialog:has-text("确认接受应助吗") button:has-text("确定")',
            '[role="dialog"]:has-text("确认接受应助吗") button:has-text("确定")',
            '.layui-layer:has-text("采纳") .layui-layer-btn0',
            '[role="dialog"]:has-text("采纳") button:has-text("确定")',
            '[role="dialog"]:has-text("采纳") a:has-text("确定")',
            'button:has-text("确认采纳")',
            'a:has-text("确认采纳")',
            'button:has-text("确定")',
        ]
    )
    accepted_markers: list[str] = field(
        default_factory=lambda: [
            'text="已采纳"',
            'text="已完结"',
            'text="求助已完成"',
            'text="采纳成功"',
        ]
    )
    acceptance_success_markers: list[str] = field(
        default_factory=lambda: [
            'text="操作成功，感谢使用科研通"',
            '.layui-layer:has-text("操作成功，感谢使用科研通")',
        ]
    )
    acceptance_success_buttons: list[str] = field(
        default_factory=lambda: [
            '.layui-layer:has-text("操作成功，感谢使用科研通") .layui-layer-btn0',
            '.layui-layer:has-text("操作成功，感谢使用科研通") a:has-text("确定")',
            '.layui-layer:has-text("操作成功") .layui-layer-btn0',
        ]
    )
    captcha_markers: list[str] = field(
        default_factory=lambda: [
            'iframe[src*="captcha"]',
            'iframe[src*="verify"]',
            '[class*="captcha"]',
            '[id*="captcha"]',
            'input[placeholder*="验证码"]',
            'input[name*="captcha"]',
        ]
    )
    blocked_markers: list[str] = field(
        default_factory=lambda: [
            'text="操作过于频繁"',
            'text="请求过于频繁"',
            'text="账号被封禁"',
            'text="暂时无法发布"',
        ]
    )

    @classmethod
    def load(cls, path: Path | None) -> "SiteSelectors":
        if path is None:
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        allowed = {item.name for item in fields(cls)}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(f"选择器文件包含未知字段: {', '.join(unknown)}")
        for name, value in raw.items():
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"选择器字段 {name} 必须是字符串数组")
        default = cls()
        for name, value in raw.items():
            setattr(default, name, value)
        return default


@dataclass(slots=True)
class PublishOutcome:
    verified: bool
    request_url: str
    page: Page


@dataclass(slots=True)
class PreparedRequest:
    publish_button: Locator
    literature: LiteratureMetadata


class AbleSciAdapter:
    def __init__(
        self,
        *,
        selectors: SiteSelectors,
        assist_url: str,
        my_assists_url: str,
        points_url: str,
        login_url: str,
        headless: bool,
        debug_dir: Path,
        save_debug_artifacts: bool = True,
        output: Callable[[str], None] = print,
        input_func: Callable[[str], str] = input,
    ):
        self.selectors = selectors
        self.assist_url = assist_url
        self.my_assists_url = my_assists_url
        self.points_url = points_url
        self.login_url = login_url
        self.headless = headless
        self.debug_dir = debug_dir
        self.save_debug_artifacts = save_debug_artifacts
        self.output = output
        self.input_func = input_func

    async def open_assist(self, page: Page) -> None:
        await page.goto(self.assist_url, wait_until="domcontentloaded", timeout=60_000)
        if await self.is_login_page(page):
            raise LoginRequired("科研通登录状态已失效")
        if "/my/assist-my" in page.url:
            raise PendingReviewRequired(
                "科研通把发布页重定向到了“我的求助”；请先处理历史待确认文件"
            )
        if "/assist/create" not in page.url:
            raise PageStructureChanged(f"未能进入一键求助页面，当前地址: {page.url}")

    async def is_login_page(self, page: Page) -> bool:
        if "/site/login" in page.url:
            return True
        password = page.locator('input[type="password"]').first
        try:
            return await password.is_visible(timeout=500)
        except PlaywrightTimeoutError:
            return False

    async def account_points(self, page: Page) -> AccountPoints:
        await page.goto(
            self.points_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        if await self.is_login_page(page):
            raise LoginRequired("科研通登录状态已失效，请先登录账号")
        if "/my/point" not in page.url:
            raise PageStructureChanged(
                f"未能进入科研通积分详情页，当前地址: {page.url}"
            )

        value = await self._first_visible(
            page,
            self.selectors.account_points_values,
            3_000,
        )
        if value is None:
            raise PageStructureChanged("科研通积分详情页中没有找到总积分")
        text = " ".join((await value.inner_text()).split())
        match = re.search(r"-?\d[\d,，]*", text)
        if match is None:
            raise PageStructureChanged(f"科研通总积分无法识别: {text!r}")
        return AccountPoints(
            total=int(match.group().replace(",", "").replace("，", ""))
        )

    async def open_check_in_page(self, page: Page) -> None:
        """Open the official page where the user can check in manually."""
        await page.goto(
            urljoin(self.points_url, "/"),
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        if await self.is_login_page(page):
            raise LoginRequired("科研通登录状态已失效，请先登录账号")
        if urlparse(page.url).path not in ("", "/"):
            raise PageStructureChanged(
                f"未能进入科研通签到页面，当前地址: {page.url}"
            )

    async def open_points_recharge_page(self, page: Page) -> None:
        """Open AbleSci's official points donation page without submitting it."""
        await page.goto(
            urljoin(self.points_url, "/my/point-donate"),
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        if await self.is_login_page(page):
            raise LoginRequired("科研通登录状态已失效，请先登录账号")
        if "/my/point-donate" not in page.url:
            raise PageStructureChanged(
                f"未能进入科研通积分充值页面，当前地址: {page.url}"
            )

    async def interactive_login(self, page: Page) -> None:
        if self.headless:
            raise LoginRequired("无头模式无法完成人工登录；请先运行 lithelper login")
        await page.goto(self.login_url, wait_until="domcontentloaded", timeout=60_000)
        self.output("请在打开的浏览器中登录科研通。账号密码仅由网站处理，不会写入任务数据库。")
        await asyncio.to_thread(
            self.input_func,
            "登录完成后回到终端按 Enter（如有验证码请一并完成）… ",
        )
        await page.goto(self.assist_url, wait_until="domcontentloaded", timeout=60_000)
        if await self.is_login_page(page):
            raise LoginRequired("仍停留在登录页，请确认登录是否成功")

    async def credential_login(
        self,
        page: Page,
        *,
        email: str,
        password: str,
    ) -> None:
        if not email.strip() or not password:
            raise ValueError("科研通邮箱和密码不能为空")

        await page.goto(
            self.login_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        email_input = await self._first_visible(
            page,
            self.selectors.login_email_inputs,
            3_000,
        )
        password_input = await self._first_visible(
            page,
            self.selectors.login_password_inputs,
            3_000,
        )
        submit = await self._first_visible(
            page,
            self.selectors.login_submit_buttons,
            3_000,
        )
        if email_input is None or password_input is None or submit is None:
            raise PageStructureChanged("科研通登录表单结构已变化")

        await email_input.fill(email.strip())
        await password_input.fill(password)
        remember = await self._first_visible(
            page,
            self.selectors.login_remember_inputs,
            500,
        )
        if remember is not None:
            await remember.check(force=True)

        await submit.click(timeout=10_000)
        await self._settle(page, 1_000)
        if await self._captcha_visible(page):
            raise LoginRequired(
                "科研通要求验证码；终端登录不会绕过验证，"
                "请运行 lithelper login --manual-browser 完成一次可视登录"
            )
        if await self.is_login_page(page):
            marker = await self._first_visible(
                page,
                self.selectors.login_error_markers,
                1_000,
            )
            detail = ""
            if marker is not None:
                detail = " ".join((await marker.inner_text()).split())
            suffix = f"：{detail}" if detail else ""
            raise LoginRequired(f"科研通账号或密码未能通过验证{suffix}")

        await page.goto(
            self.assist_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        if await self.is_login_page(page):
            raise LoginRequired("登录会话未能保存，请重试")

    async def ensure_no_historical_pending(
        self,
        page: Page,
        *,
        auto_accept: bool = False,
    ) -> tuple[Page, int]:
        await page.goto(
            self.my_assists_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        if await self.is_login_page(page):
            raise LoginRequired("检查历史待确认时登录状态已失效")

        pending_tab = await self._first_visible(
            page,
            self.selectors.pending_review_tabs,
            2_000,
        )
        if pending_tab is not None:
            await pending_tab.click()
            await self._settle(page, 800)

        pending_row = await self._first_visible(
            page,
            self.selectors.pending_review_rows,
            1_500,
        )
        if pending_row is not None:
            if auto_accept:
                accepted_count = 0
                while accepted_count < 100:
                    try:
                        detail_page, _ = await self.open_pending_request(
                            page,
                            select_first=True,
                        )
                    except PageStructureChanged as exc:
                        if "没有可恢复的记录" in str(exc):
                            break
                        raise
                    await self.accept_uploaded_file(detail_page)
                    accepted_count += 1
                    self.output(
                        f"已自动采纳 {accepted_count} 条历史待确认求助。"
                    )
                    page = detail_page
                if accepted_count >= 100:
                    raise SiteAdapterError("历史待确认求助超过 100 条，已停止批量采纳")
                await self.open_assist(page)
                return page, accepted_count

            await self._wait_for_human(
                page,
                "检测到科研通历史“待确认”求助。请在当前浏览器中逐篇打开文件、"
                "检查并选择采纳或驳回；全部处理完成后按 Enter… ",
            )
            await page.goto(
                self.my_assists_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            pending_tab = await self._first_visible(
                page,
                self.selectors.pending_review_tabs,
                2_000,
            )
            if pending_tab is not None:
                await pending_tab.click()
                await self._settle(page, 800)
            pending_row = await self._first_visible(
                page,
                self.selectors.pending_review_rows,
                1_000,
            )
            if pending_row is not None:
                raise SiteAdapterError("仍存在历史待确认求助，已停止发布新求助")

        try:
            await self.open_assist(page)
        except PendingReviewRequired as exc:
            raise PendingReviewRequired(
                "历史待确认求助尚未全部处理，科研通拒绝进入新求助页面"
            ) from exc
        return page, 0

    async def open_pending_request(
        self,
        page: Page,
        *,
        preferred_query: str | None = None,
        select_first: bool = False,
    ) -> tuple[Page, str]:
        pending_url = f"{self.my_assists_url}?status=uploaded"
        await page.goto(
            pending_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        if await self.is_login_page(page):
            raise LoginRequired("打开历史待确认列表时登录状态已失效")

        pending_tab = await self._first_visible(
            page,
            self.selectors.pending_review_tabs,
            1_500,
        )
        if pending_tab is not None:
            await pending_tab.click()
            await self._settle(page, 700)

        rows = await self._visible_items(
            page,
            self.selectors.pending_review_rows,
            limit=50,
        )
        if not rows:
            raise PageStructureChanged("“我的求助 → 待确认”中没有可恢复的记录")

        selected: Locator | None = None
        if preferred_query:
            normalized = preferred_query.casefold()
            for row in rows:
                text = " ".join((await row.inner_text()).split()).casefold()
                if normalized in text:
                    selected = row
                    break
        if selected is None and select_first:
            selected = rows[0]
        if selected is None:
            selected = rows[0] if len(rows) == 1 else await self._choose_result(rows)

        row_text = " ".join((await selected.inner_text()).split())
        links = selected.locator("a")
        visible_links: list[tuple[Locator, str]] = []
        for index in range(await links.count()):
            candidate = links.nth(index)
            try:
                if await candidate.is_visible():
                    visible_links.append(
                        (candidate, (await candidate.get_attribute("href")) or "")
                    )
            except Exception:
                continue
        link = next(
            (
                candidate
                for candidate, href in visible_links
                if "/assist/" in href
            ),
            visible_links[0][0] if visible_links else None,
        )
        if link is None:
            raise PageStructureChanged("待确认记录中找不到求助详情链接")

        pages_before = set(page.context.pages)
        before_url = page.url
        await link.click()
        await self._settle(page, 1_000)
        new_pages = [item for item in page.context.pages if item not in pages_before]
        detail_page = new_pages[-1] if new_pages else page
        try:
            await detail_page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except PlaywrightTimeoutError:
            pass
        if detail_page.url == before_url:
            href = await link.get_attribute("href")
            if href and not href.lower().startswith(("javascript:", "#")):
                await detail_page.goto(
                    urljoin(before_url, href),
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
        if "/my/assist-my" in detail_page.url:
            raise PageStructureChanged("点击待确认记录后没有进入求助详情")
        return detail_page, row_text

    async def prepare_request(self, page: Page, query: str) -> PreparedRequest:
        query_input = await self._first_visible(page, self.selectors.query_inputs, 12_000)
        if query_input is None:
            raise PageStructureChanged("找不到 DOI/标题输入框")

        await query_input.click()
        await query_input.fill(query)

        intelligent_extract = await self._first_visible(
            page,
            self.selectors.intelligent_extract_buttons,
            2_500,
        )
        if intelligent_extract is not None and await intelligent_extract.is_enabled():
            self.output("正在智能提取文献信息…")
            await intelligent_extract.click()
            await self._settle(page, 2_000)
            await self._raise_if_blocked(page)
            if await self._captcha_visible(page):
                await self._wait_for_human(
                    page,
                    "智能提取需要验证码/人机验证，请完成后按 Enter… ",
                )

            extracted_publish = await self._first_visible(
                page,
                self.selectors.extracted_publish_buttons,
                15_000,
            )
            if extracted_publish is None:
                raise PageStructureChanged(
                    "已点击“智能提取文献信息”，但没有出现“信息正确，直接发布”。"
                    "请检查 DOI/标题是否正确，或根据诊断截图校准选择器"
                )
            literature = await self.extract_literature_metadata(page, query)
            self.output("文献信息已提取，等待“信息正确，直接发布”。")
            return PreparedRequest(
                publish_button=extracted_publish,
                literature=literature,
            )

        lookup = await self._first_visible(page, self.selectors.lookup_buttons, 1_200)
        if lookup is not None and await lookup.is_enabled():
            await lookup.click()

        await self._settle(page, 2_000)
        await self._raise_if_blocked(page)
        if await self._captcha_visible(page):
            await self._wait_for_human(
                page,
                "页面要求验证码/人机验证，请在浏览器中完成后按 Enter… ",
            )

        publish = await self.find_publish_button(page, timeout_ms=4_000)
        if publish is not None:
            return PreparedRequest(
                publish_button=publish,
                literature=await self.extract_literature_metadata(page, query),
            )

        results = await self._visible_result_items(page)
        if results:
            selected = await self._choose_result(results)
            await selected.click()
            await self._settle(page, 1_500)

        confirm = await self._first_visible(page, self.selectors.confirm_buttons, 1_500)
        if confirm is not None and await confirm.is_enabled():
            await confirm.click()
            await self._settle(page, 1_500)

        publish = await self.find_publish_button(page, timeout_ms=8_000)
        if publish is None:
            raise PageStructureChanged(
                "网站没有出现“立即发布/发布求助”按钮；可能未匹配到文献或页面结构已变化"
            )
        return PreparedRequest(
            publish_button=publish,
            literature=await self.extract_literature_metadata(page, query),
        )

    async def extract_literature_metadata(
        self,
        page: Page,
        query: str,
    ) -> LiteratureMetadata:
        """Read the fields populated by AbleSci without calling another service."""
        try:
            snapshot = await page.evaluate(_METADATA_SNAPSHOT_SCRIPT)
        except Exception as exc:
            self.output(
                "智能提取已完成，但页面字段读取不完整；"
                f"将保留可确认的输入信息（{type(exc).__name__}）。"
            )
            snapshot = {}

        literature = _metadata_from_snapshot(snapshot, query)
        summary = literature.title or literature.doi
        if summary:
            self.output(f"已读取文献信息：{summary}")
        else:
            self.output("智能提取已完成，但页面中没有可识别的文献信息字段。")
        return literature

    async def find_publish_button(
        self, page: Page, *, timeout_ms: int = 2_000
    ) -> Locator | None:
        extracted = await self._first_visible(
            page,
            self.selectors.extracted_publish_buttons,
            min(timeout_ms, 1_000),
        )
        if extracted is not None:
            return extracted
        return await self._first_visible(page, self.selectors.publish_buttons, timeout_ms)

    async def click_publish_once(self, page: Page, publish_button: Locator) -> PublishOutcome:
        if await self._captcha_visible(page):
            await self._wait_for_human(
                page,
                "发布前需要验证码/人机验证，请完成后按 Enter… ",
            )
        if not await publish_button.is_enabled():
            await self._wait_for_human(
                page,
                "发布按钮尚不可用。请在浏览器中检查必填项或勾选规则确认，完成后按 Enter… ",
            )
            publish_button = await self.find_publish_button(page, timeout_ms=3_000)
            if publish_button is None or not await publish_button.is_enabled():
                raise PublishUncertain("发布按钮仍不可用，未执行点击")

        before_url = page.url
        try:
            await publish_button.click(timeout=10_000)
        except Exception as exc:
            raise PublishUncertain(
                f"发布按钮只尝试了一次，但无法确认点击是否生效: {type(exc).__name__}: {exc}"
            ) from exc

        await self._settle(page, 2_000)
        if await self._captcha_visible(page):
            await self._wait_for_human(
                page,
                "发布动作触发了验证码。请完成验证及页面上的发布动作，然后按 Enter… ",
            )
        await self._raise_if_blocked(page)

        detail = await self._first_visible(
            page,
            self.selectors.post_publish_detail_buttons,
            8_000,
        )
        if detail is not None:
            self.output("求助发布成功，正在进入求助详情…")
            pages_before = set(page.context.pages) if hasattr(page, "context") else set()
            await detail.click()
            await self._settle(page, 1_500)
            new_pages = (
                [item for item in page.context.pages if item not in pages_before]
                if hasattr(page, "context")
                else []
            )
            detail_page = new_pages[-1] if new_pages else page
            try:
                await detail_page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=15_000,
                )
            except (AttributeError, PlaywrightTimeoutError):
                pass
            return PublishOutcome(
                verified=True,
                request_url=detail_page.url,
                page=detail_page,
            )

        verified = page.url != before_url
        marker = None
        if not verified:
            marker = await self._first_visible(page, self.selectors.success_markers, 2_000)
            verified = marker is not None
        if marker is not None:
            await self._wait_for_human(
                page,
                "已检测到发布成功，但未定位到“查看求助详情”。"
                "请在浏览器中手动点击该按钮，进入详情后按 Enter… ",
            )
        return PublishOutcome(verified=verified, request_url=page.url, page=page)

    async def wait_for_download(
        self,
        page: Page,
        *,
        initial_delay_seconds: float,
        interval_seconds: float,
        timeout_seconds: float,
        on_poll: Callable[[int], Awaitable[None]] | None = None,
    ) -> Locator:
        await asyncio.sleep(initial_delay_seconds)
        deadline = time.monotonic() + timeout_seconds
        poll_count = 0

        while time.monotonic() < deadline:
            poll_count += 1
            await self._raise_if_blocked(page)
            if await self.is_login_page(page):
                raise LoginRequired("轮询期间登录状态失效")

            await self.dismiss_upload_notice(page)
            download = await self._first_visible(page, self.selectors.download_links, 700)
            if download is not None:
                return download

            if on_poll is not None:
                await on_poll(poll_count)
            await asyncio.sleep(interval_seconds)
            try:
                await page.reload(wait_until="domcontentloaded", timeout=30_000)
            except PlaywrightTimeoutError:
                self.output("页面刷新超时，将继续检查当前页面…")

        raise PollTimedOut(f"在 {timeout_seconds:g} 秒内未发现应助文件")

    async def download(
        self,
        page: Page,
        link: Locator,
        *,
        download_dir: Path,
        filename_hint: str,
        prefer_high_speed: bool = True,
        download_timeout_seconds: float = 180.0,
    ) -> Path:
        download_dir.mkdir(parents=True, exist_ok=True)
        download_page = await self._open_download_page(page, link)
        if await self._pending_review_visible(download_page):
            await self._wait_for_pending_review(download_page)
            await download_page.reload(wait_until="domcontentloaded", timeout=30_000)

        channel = await self._find_download_channel(
            download_page,
            prefer_high_speed=prefer_high_speed,
        )
        return await self._download_from_channel(
            download_page,
            channel,
            download_dir=download_dir,
            filename_hint=filename_hint,
            prefer_high_speed=prefer_high_speed,
            download_timeout_seconds=download_timeout_seconds,
        )

    async def dismiss_upload_notice(self, page: Page) -> bool:
        marker = await self._first_visible(
            page,
            self.selectors.upload_notice_markers,
            300,
        )
        if marker is None:
            return False
        confirm = await self._first_visible(
            page,
            self.selectors.upload_notice_confirm_buttons,
            2_000,
        )
        if confirm is None:
            await self._wait_for_human(
                page,
                "检测到“已经有人上传了文件”提示，请在浏览器中点击“确定”后按 Enter… ",
            )
        else:
            self.output("检测到应助上传提示，正在点击“确定”…")
            await confirm.click()
            await self._settle(page, 500)
        return True

    async def accept_uploaded_file(self, page: Page) -> None:
        await self.dismiss_upload_notice(page)
        already_accepted = await self._first_visible(
            page,
            self.selectors.accepted_markers,
            800,
        )
        if already_accepted is not None:
            return

        accept = await self._first_visible(
            page,
            self.selectors.accept_file_buttons,
            10_000,
        )
        if accept is None:
            raise PageStructureChanged("求助详情页中找不到“采纳文件”按钮")

        self.output("正在把人工确认结果同步到科研通：采纳文件…")
        dialog_tasks: list[asyncio.Task] = []

        def accept_native_dialog(dialog) -> None:
            dialog_tasks.append(asyncio.create_task(dialog.accept()))

        page.on("dialog", accept_native_dialog)
        try:
            await accept.click()
            await self._settle(page, 700)
            confirmation = await self._first_visible(
                page,
                self.selectors.accept_confirmation_buttons,
                2_500,
            )
            if confirmation is not None:
                await confirmation.click()
                await self._settle(page, 1_000)
            if dialog_tasks:
                await asyncio.gather(*dialog_tasks)
                await self._settle(page, 700)
        finally:
            page.remove_listener("dialog", accept_native_dialog)

        accepted = await self._first_visible(
            page,
            self.selectors.accepted_markers,
            5_000,
        )
        if accepted is None:
            success = await self._first_visible(
                page,
                self.selectors.acceptance_success_markers,
                2_000,
            )
            if success is not None:
                success_confirmation = await self._first_visible(
                    page,
                    self.selectors.acceptance_success_buttons,
                    1_500,
                )
                if success_confirmation is not None:
                    await success_confirmation.click()
                    await self._settle(page, 700)
                return
        accept_still_visible = await self._first_visible(
            page,
            self.selectors.accept_file_buttons,
            500,
        )
        if accepted is None and accept_still_visible is not None:
            paths = await self.capture_debug(page, "accept-failed")
            if paths:
                self.output(
                    "已保存采纳失败现场："
                    + "，".join(str(path) for path in paths)
                )
            raise PublishUncertain(
                "已单次点击“采纳文件”，但页面未显示采纳成功；请人工检查求助详情"
            )

    async def _open_download_page(
        self,
        page: Page,
        file_link: Locator,
        *,
        pending_retry_remaining: int = 1,
    ) -> Page:
        pages_before = set(page.context.pages)
        before_url = page.url
        href = await file_link.get_attribute("href")
        await file_link.click(timeout=10_000)
        await self._settle(page, 1_200)

        new_pages = [item for item in page.context.pages if item not in pages_before]
        download_page = new_pages[-1] if new_pages else page
        try:
            await download_page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except PlaywrightTimeoutError:
            pass

        if download_page.url == before_url and href and not href.lower().startswith(
            ("javascript:", "#")
        ):
            await download_page.goto(
                urljoin(before_url, href),
                wait_until="domcontentloaded",
                timeout=30_000,
            )

        if await self._pending_review_visible(download_page):
            await self._wait_for_pending_review(download_page)
            if await self._pending_review_visible(download_page):
                raise SiteAdapterError("历史待确认求助尚未处理，已停止当前下载")
            if download_page.url == before_url:
                if pending_retry_remaining <= 0:
                    raise SiteAdapterError("处理历史待确认后仍无法进入当前文件下载页")
                refreshed_link = await self._first_visible(
                    download_page,
                    self.selectors.download_links,
                    3_000,
                )
                if refreshed_link is None:
                    raise PageStructureChanged("处理历史待确认后，找不到当前 PDF 文件入口")
                return await self._open_download_page(
                    download_page,
                    refreshed_link,
                    pending_retry_remaining=pending_retry_remaining - 1,
                )
        return download_page

    async def _find_download_channel(
        self,
        page: Page,
        *,
        prefer_high_speed: bool,
    ) -> Locator:
        if prefer_high_speed:
            high_speed = await self._first_visible(
                page,
                self.selectors.high_speed_channels,
                10_000,
            )
            if high_speed is not None:
                self.output("已进入下载页，将使用高速通道下载。")
                return high_speed
            self.output("下载页未发现高速通道，将回退到普通线路。")

        normal = await self._first_visible(
            page,
            self.selectors.normal_download_channels,
            5_000,
        )
        if normal is None:
            raise PageStructureChanged("下载页中找不到高速通道或普通线路")
        return normal

    async def _download_from_channel(
        self,
        page: Page,
        channel: Locator,
        *,
        download_dir: Path,
        filename_hint: str,
        prefer_high_speed: bool,
        download_timeout_seconds: float,
        pending_retry_remaining: int = 1,
    ) -> Path:
        pages_before = set(page.context.pages)
        before_url = page.url
        download_wait = asyncio.create_task(
            page.wait_for_event(
                "download",
                timeout=download_timeout_seconds * 1_000,
            )
        )
        try:
            await channel.click()
            deadline = time.monotonic() + download_timeout_seconds
            while not download_wait.done() and time.monotonic() < deadline:
                if await self._pending_review_visible(page):
                    download_wait.cancel()
                    await asyncio.gather(download_wait, return_exceptions=True)
                    await self._wait_for_pending_review(page)
                    if await self._pending_review_visible(page):
                        raise SiteAdapterError("历史待确认求助尚未处理，已停止当前下载")
                    if pending_retry_remaining <= 0:
                        raise SiteAdapterError("处理历史待确认后仍无法开始下载")
                    await page.goto(
                        before_url,
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    refreshed_channel = await self._find_download_channel(
                        page,
                        prefer_high_speed=prefer_high_speed,
                    )
                    return await self._download_from_channel(
                        page,
                        refreshed_channel,
                        download_dir=download_dir,
                        filename_hint=filename_hint,
                        prefer_high_speed=prefer_high_speed,
                        download_timeout_seconds=download_timeout_seconds,
                        pending_retry_remaining=pending_retry_remaining - 1,
                    )
                await asyncio.sleep(0.25)

            item = await download_wait
            filename = _safe_filename(item.suggested_filename or filename_hint, ".pdf")
            destination = _unique_path(download_dir / filename)
            await item.save_as(destination)
            return destination
        except PlaywrightTimeoutError:
            new_pages = [item for item in page.context.pages if item not in pages_before]
            candidate = new_pages[-1] if new_pages else page
            if candidate.url and candidate.url not in ("about:blank", before_url):
                return await self._download_with_session(
                    page.context,
                    candidate.url,
                    download_dir=download_dir,
                    filename_hint=filename_hint,
                )
            raise SiteAdapterError("点击下载后既未收到文件，也未打开可下载的新页面")
        finally:
            if not download_wait.done():
                download_wait.cancel()
                await asyncio.gather(download_wait, return_exceptions=True)

    async def _pending_review_visible(self, page: Page) -> bool:
        return (
            await self._first_visible(
                page,
                self.selectors.pending_review_markers,
                500,
            )
            is not None
        )

    async def _wait_for_pending_review(self, page: Page) -> None:
        await self._wait_for_human(
            page,
            "科研通提示存在历史“待确认”求助。请先在浏览器中逐篇查看并决定采纳或驳回，"
            "处理完成后返回当前文献页面，再按 Enter 继续… ",
        )

    async def _download_with_session(
        self,
        context: BrowserContext,
        url: str,
        *,
        download_dir: Path,
        filename_hint: str,
    ) -> Path:
        response = await context.request.get(url, timeout=60_000)
        if not response.ok:
            raise SiteAdapterError(f"下载请求失败: HTTP {response.status}")

        content_disposition = response.headers.get("content-disposition", "")
        server_name = _filename_from_disposition(content_disposition)
        url_name = Path(unquote(urlparse(url).path)).name
        filename = _safe_filename(server_name or url_name or filename_hint, ".pdf")
        destination = _unique_path(download_dir / filename)
        temporary = destination.with_name(destination.name + ".part")
        temporary.write_bytes(await response.body())
        temporary.replace(destination)
        return destination

    async def capture_debug(self, page: Page, task_id: str) -> list[Path]:
        if not self.save_debug_artifacts:
            return []
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        base = self.debug_dir / f"{task_id}-{timestamp}"
        artifacts: list[Path] = []
        try:
            screenshot = base.with_suffix(".png")
            await page.screenshot(path=str(screenshot), full_page=True)
            artifacts.append(screenshot)
        except Exception:
            pass
        try:
            text_path = base.with_suffix(".txt")
            body_text = await page.locator("body").inner_text(timeout=3_000)
            text_path.write_text(
                f"URL: {page.url}\n\n{body_text[:200_000]}\n",
                encoding="utf-8",
            )
            artifacts.append(text_path)
        except Exception:
            pass
        return artifacts

    async def _choose_result(self, results: list[Locator]) -> Locator:
        if len(results) == 1:
            return results[0]
        if self.headless:
            raise PageStructureChanged("匹配到多篇文献，无头模式下无法人工选择")
        self.output("匹配到多篇文献，请人工确认：")
        for index, locator in enumerate(results[:10], start=1):
            text = " ".join((await locator.inner_text()).split())
            self.output(f"  {index}. {text[:180]}")
        while True:
            answer = await asyncio.to_thread(
                self.input_func,
                f"请选择 1-{min(len(results), 10)}（输入 q 取消）: ",
            )
            if answer.strip().lower() == "q":
                raise PageStructureChanged("用户取消了文献匹配")
            try:
                index = int(answer) - 1
            except ValueError:
                continue
            if 0 <= index < min(len(results), 10):
                return results[index]

    async def _visible_result_items(self, page: Page) -> list[Locator]:
        return await self._visible_items(
            page,
            self.selectors.result_items,
            limit=10,
        )

    @staticmethod
    async def _visible_items(
        page: Page,
        selectors: list[str],
        *,
        limit: int,
    ) -> list[Locator]:
        found: list[Locator] = []
        for selector in selectors:
            locator = page.locator(selector)
            count = min(await locator.count(), limit)
            for index in range(count):
                item = locator.nth(index)
                try:
                    if await item.is_visible():
                        found.append(item)
                except Exception:
                    continue
            if found:
                break
        return found

    async def _captcha_visible(self, page: Page) -> bool:
        return (
            await self._first_visible(page, self.selectors.captcha_markers, 350)
            is not None
        )

    async def _raise_if_blocked(self, page: Page) -> None:
        marker = await self._first_visible(page, self.selectors.blocked_markers, 250)
        if marker is not None:
            text = " ".join((await marker.inner_text()).split())
            raise SiteAdapterError(f"网站拒绝了当前操作: {text}")

    async def _wait_for_human(self, page: Page, prompt: str) -> None:
        if self.headless:
            raise SiteAdapterError("页面需要人工处理，但当前运行在无头模式")
        await asyncio.to_thread(self.input_func, prompt)

    @staticmethod
    async def _settle(page: Page, minimum_ms: int) -> None:
        await page.wait_for_timeout(minimum_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=3_000)
        except PlaywrightTimeoutError:
            pass

    @staticmethod
    async def _first_visible(
        page: Page, selectors: list[str], timeout_ms: int
    ) -> Locator | None:
        deadline = time.monotonic() + timeout_ms / 1_000
        while True:
            for selector in selectors:
                try:
                    locator = page.locator(selector)
                    count = await locator.count()
                    for index in range(count):
                        candidate = locator.nth(index)
                        if await candidate.is_visible():
                            return candidate
                except Exception:
                    continue
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.1)


def _filename_from_disposition(value: str) -> str | None:
    encoded = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", value, re.IGNORECASE)
    if encoded:
        return unquote(encoded.group(1).strip().strip('"'))
    plain = re.search(r'filename\s*=\s*"([^"]+)"', value, re.IGNORECASE)
    if plain:
        return plain.group(1)
    plain = re.search(r"filename\s*=\s*([^;]+)", value, re.IGNORECASE)
    return plain.group(1).strip() if plain else None


def _safe_filename(value: str, default_suffix: str) -> str:
    value = Path(value).name.strip()
    value = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        value = "paper"
    if not Path(value).suffix:
        value += default_suffix
    return value[:220]


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法为下载文件生成唯一名称: {path}")


_METADATA_SNAPSHOT_SCRIPT = """
() => {
  const clean = (value) => (value || "").replace(/\\s+/g, " ").trim();
  const scope = document;

  const fields = [];
  for (const element of scope.querySelectorAll("input, textarea, select")) {
    const type = (element.getAttribute("type") || "").toLowerCase();
    if (["password", "button", "submit", "reset", "file"].includes(type)) {
      continue;
    }
    const value = clean(element.value);
    if (!value) {
      continue;
    }
    const labels = element.labels
      ? Array.from(element.labels).map((label) => clean(label.innerText))
      : [];
    const container = element.closest(
      "tr, .form-group, .layui-form-item, .form-row, .row"
    );
    fields.push({
      value,
      label: clean(labels.join(" ")),
      name: clean(element.getAttribute("name")),
      id: clean(element.id),
      placeholder: clean(element.getAttribute("placeholder")),
      aria_label: clean(element.getAttribute("aria-label")),
      context: container ? clean(container.innerText).slice(0, 1000) : "",
    });
  }

  return {
    fields,
    text: (
      (document.body && document.body.innerText)
      || (document.documentElement && document.documentElement.innerText)
      || ""
    ).slice(0, 20000),
  };
}
"""

_DOI_IN_TEXT = re.compile(r"10\.\d{4,9}/[^\s<>\"']+", re.IGNORECASE)


def _metadata_from_snapshot(
    snapshot: object,
    query: str,
) -> LiteratureMetadata:
    data = snapshot if isinstance(snapshot, dict) else {}
    raw_fields = data.get("fields", [])
    fields = [item for item in raw_fields if isinstance(item, dict)]
    page_text = data.get("text") if isinstance(data.get("text"), str) else ""
    metadata_text = "\n".join(
        [
            page_text,
            *[
                value
                for item in fields
                if (value := _clean_metadata_value(item.get("value")))
            ],
        ]
    )

    title = _pick_metadata_field(
        fields,
        r"(?:^|[^a-z])(title|article.?title)(?:[^a-z]|$)|标题|题名",
        reject=_contains_doi,
    )
    doi_value = _pick_metadata_field(
        fields,
        r"(?:^|[^a-z])doi(?:[^a-z]|$)",
    )
    url = _pick_metadata_field(
        fields,
        r"(?:^|[^a-z])(url|link)(?:[^a-z]|$)|网址|链接",
    )
    journal = _pick_metadata_field(
        fields,
        r"(?:^|[^a-z])journal(?:[^a-z]|$)|期刊|刊名",
        reject=_is_internal_enum,
    )
    authors_value = _pick_metadata_field(
        fields,
        r"(?:^|[^a-z])authors?(?:[^a-z]|$)|作者",
    )
    publication_date = _pick_metadata_field(
        fields,
        r"publish(?:ed|ing)?.?date|publication.?date|出版日期|发表日期|出版年|年份",
    )

    if title is None:
        title = _value_after_label(metadata_text, ("标题", "题名"))
        if title and _contains_doi(title):
            title = None

    doi = _normalize_doi(doi_value or metadata_text)
    if doi is None and classify_query(query) == "doi":
        doi = _normalize_doi(query)

    if url:
        match = re.search(r"https?://\S+", url)
        url = match.group().rstrip(".,;，。") if match else None
    if url is None:
        candidate = _value_after_label(metadata_text, ("网址", "链接", "URL"))
        match = re.search(r"https?://\S+", candidate or "")
        url = match.group().rstrip(".,;，。") if match else None
    if url is None:
        match = re.search(
            r"https?://(?:dx\.)?doi\.org/10\.\d{4,9}/\S+",
            metadata_text,
            re.IGNORECASE,
        )
        url = match.group().rstrip(".,;，。") if match else None

    journal = journal or _value_after_prefixed_label(
        metadata_text,
        ("期刊", "刊名", "Journal"),
    )
    authors_value = authors_value or _value_after_prefixed_label(
        metadata_text,
        ("作者", "Authors", "Author"),
    )
    publication_date = publication_date or _value_after_prefixed_label(
        metadata_text,
        ("出版日期", "发表日期", "Publication date", "Published"),
    )

    if title is None and classify_query(query) == "title":
        title = query

    return LiteratureMetadata(
        title=_clean_metadata_value(title),
        doi=doi,
        url=_clean_metadata_value(url),
        journal=_clean_metadata_value(journal),
        authors=_split_authors(authors_value),
        publication_date=_clean_metadata_value(publication_date),
    )


def _pick_metadata_field(
    fields: list[dict],
    pattern: str,
    *,
    reject: Callable[[str], bool] | None = None,
) -> str | None:
    matcher = re.compile(pattern, re.IGNORECASE)
    matches: list[tuple[int, str]] = []
    for item in fields:
        value = _clean_metadata_value(item.get("value"))
        if not value or (reject is not None and reject(value)):
            continue
        score = 0
        for key, weight in (
            ("label", 8),
            ("name", 7),
            ("id", 6),
            ("aria_label", 5),
            ("placeholder", 3),
            ("context", 1),
        ):
            descriptor = _clean_metadata_value(item.get(key))
            if descriptor and matcher.search(descriptor):
                score = max(score, weight)
        if score:
            matches.append((score, value))
    return max(matches, default=(0, None), key=lambda item: item[0])[1]


def _value_after_label(text: str, labels: tuple[str, ...]) -> str | None:
    lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
    normalized_labels = {label.casefold() for label in labels}
    for index, line in enumerate(lines):
        folded = line.rstrip(":：").strip().casefold()
        if folded in normalized_labels and index + 1 < len(lines):
            return lines[index + 1]
        for label in labels:
            match = re.match(
                rf"^{re.escape(label)}\s*[:：]\s*(.+)$",
                line,
                re.IGNORECASE,
            )
            if match:
                return match.group(1)
    return None


def _value_after_prefixed_label(
    text: str,
    labels: tuple[str, ...],
) -> str | None:
    for label in labels:
        line_match = re.search(
            rf"(?:^|[\r\n])\s*{re.escape(label)}\s*[:：]\s*([^\r\n]+)",
            text,
            re.IGNORECASE,
        )
        if line_match:
            return line_match.group(1).strip()
        match = re.search(
            rf"(?:^|\s){re.escape(label)}\s*[:：]\s*"
            r"(.+?)(?=\s+(?:期刊|刊名|作者|出版日期|发表日期|Journal|Authors?)\s*[:：]|$)",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
    return None


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    match = _DOI_IN_TEXT.search(value)
    if not match:
        return None
    return match.group().rstrip(".,;，。")


def _contains_doi(value: str) -> bool:
    return _DOI_IN_TEXT.search(value) is not None


def _is_internal_enum(value: str) -> bool:
    return re.fullmatch(r"[\d._-]+", value.strip()) is not None


def _split_authors(value: str | None) -> list[str]:
    cleaned = _clean_metadata_value(value)
    if not cleaned:
        return []
    if re.search(r"[;；]", cleaned):
        return [
            author.strip()
            for author in re.split(r"\s*[;；]\s*", cleaned)
            if author.strip()
        ]
    return [cleaned]


def _clean_metadata_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None
