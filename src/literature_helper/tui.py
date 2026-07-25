from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
from types import MethodType
from typing import Any, Callable
import unicodedata

import questionary
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import Window
from questionary import Choice, Style
from questionary.prompts.common import InquirerControl

from . import __version__
from .api import LiteratureHelper
from .config import AppConfig, default_home
from .models import (
    MAX_FETCH_QUEUE_ITEMS,
    FetchQueueResult,
    Task,
    TaskStatus,
    normalize_queries,
    normalize_query,
)


LOGO = r"""
┃  ┛━┏┛┃ ┃┏━┛┃  ┏━┃┏━┛┏━┃
┃  ┃ ┃ ┏━┃┏━┛┃  ┏━┛┏━┛┏┏┛
━━┛┛ ┛ ┛ ┛━━┛━━┛┛  ━━┛┛ ┛
""".strip("\n")

TUI_STYLE = Style(
    [
        ("qmark", "fg:#00afff bold"),
        ("question", "fg:#00afff bold"),
        ("answer", "fg:#ffd75f bold"),
        ("pointer", "fg:#ffd75f bold"),
        ("highlighted", "fg:#ffd75f bold"),
        ("selected", "fg:#5fd75f"),
        ("separator", "fg:#6c6c6c"),
        ("instruction", "fg:#6c6c6c"),
    ]
)

_FRAME_STYLE = "fg:#ffffff"
_LOGO_STYLE = "fg:#ffd75f bold"
_INFO_STYLE = "fg:#8a8a8a"

_BACK = "__back__"
_SITE_PENDING = "__site_pending__"

_STATUS_LABELS = {
    TaskStatus.CREATED: "已创建",
    TaskStatus.WAITING_LOGIN: "等待登录",
    TaskStatus.MATCHING: "提取信息",
    TaskStatus.READY_TO_PUBLISH: "等待发布",
    TaskStatus.PUBLISHED: "已发布",
    TaskStatus.WAITING_FILE: "等待应助",
    TaskStatus.DOWNLOADING: "下载中",
    TaskStatus.DOWNLOADED_PENDING_REVIEW: "已下载·待采纳",
    TaskStatus.CONFIRMED: "已完成",
    TaskStatus.REJECTED: "已标记有误",
    TaskStatus.FAILED: "失败",
    TaskStatus.TIMED_OUT: "等待超时",
    TaskStatus.CANCELLED: "已取消",
}


class LiteratureHelperTUI:
    """Thin human interface over the same public API used by scripts."""

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        output: Callable[[str], None] = print,
    ):
        self.config_path = config_path
        self.output = output
        self._uses_terminal_output = output is print

    @property
    def resolved_config_path(self) -> Path:
        return self.config_path or (default_home() / "config.json")

    def run(self) -> int:
        result = self._run()
        if result == 0:
            self.output("已退出 Literature Helper。")
        return result

    def _run(self) -> int:
        if not self.resolved_config_path.exists():
            self._redraw()
            proceed = questionary.confirm(
                "检测到首次使用，是否现在完成基础设置？",
                default=True,
                style=TUI_STYLE,
            ).ask()
            if proceed:
                self._setup()

        while True:
            self._redraw()
            action = self._select(
                "主菜单",
                choices=[
                    Choice("账号管理", "account"),
                    Choice("下载文献", "fetch"),
                    Choice("历史记录", "history"),
                    Choice("设置", "settings"),
                    Choice("退出", "exit"),
                ],
            )
            if action in (None, "exit"):
                return 0

            handlers = {
                "account": self._account_management,
                "fetch": self._fetch,
                "history": self._history,
                "settings": self._settings,
            }
            try:
                handlers[action]()
            except KeyboardInterrupt:
                self._write("\n操作已取消。")
                self._pause()
            except Exception as exc:
                self._write(f"\n操作失败：{type(exc).__name__}: {exc}")
                self._pause()

    def _show_header(self) -> None:
        config = AppConfig.load(self.config_path)
        download_dir = str(config.download_dir)
        home = str(Path.home())
        if download_dir.startswith(home):
            download_dir = "~" + download_dir[len(home):]
        mode = "HEADLESS" if config.headless else "VISIBLE BROWSER"
        width = max(
            4,
            min(shutil.get_terminal_size(fallback=(80, 24)).columns - 2, 100),
        )
        header = _build_header_fragments(
            width=width,
            logo=LOGO,
            mode=mode,
            download_dir=download_dir,
            version=__version__,
        )

        self._write("")
        for line in header:
            self._write_styled(line)
        self._write("")

    def _select(
        self,
        message: str,
        choices: list[Choice],
        *,
        default: object | None = None,
        escape_value: object | None = None,
        space_after_prompt: bool = True,
    ) -> object | None:
        options = {
            "choices": choices,
            "instruction": "↑↓ 选择 · Enter 确认",
            "pointer": "❯",
            "qmark": "",
            "style": TUI_STYLE,
            "use_emacs_keys": False,
            "use_jk_keys": False,
        }
        if default is not None:
            options["default"] = default
        prompt = questionary.select(message, **options)
        _configure_bounded_navigation(prompt)
        if escape_value is not None:
            _configure_escape_value(prompt, escape_value)
        if space_after_prompt:
            _add_question_spacing(prompt)
        return prompt.ask()

    def _clear_screen(self) -> None:
        if (
            not self._uses_terminal_output
            or not sys.stdout.isatty()
            or os.environ.get("TERM") == "dumb"
        ):
            return
        # Clear both the visible viewport and its scrollback. A long detail
        # page can scroll above row 1, where a viewport-only erase cannot
        # remove it before the next menu is rendered.
        sys.stdout.write("\033[H\033[2J\033[3J")
        sys.stdout.flush()

    def _redraw(self) -> None:
        self._clear_screen()
        self._show_header()

    def _write(self, message: str, style: str | None = None) -> None:
        if not self._uses_terminal_output:
            self.output(message)
            return
        questionary.print(message, style=style)

    def _write_styled(self, fragments: list[tuple[str, str]]) -> None:
        if not self._uses_terminal_output:
            self.output("".join(text for _style, text in fragments))
            return
        print_formatted_text(FormattedText(fragments))

    def _app(self) -> LiteratureHelper:
        return LiteratureHelper(
            config_path=self.config_path,
            output=self._write,
        )

    def _setup(self) -> None:
        self._redraw()
        config = AppConfig.load(self.config_path)
        download_dir = questionary.text(
            "默认下载目录",
            default=str(config.download_dir),
            validate=lambda value: bool(value.strip()) or "目录不能为空",
        ).ask()
        if download_dir is None:
            return
        headless = questionary.confirm(
            "日常默认使用无界面模式？",
            default=config.headless,
        ).ask()
        if headless is None:
            return

        config.download_dir = Path(download_dir).expanduser().resolve()
        config.headless = headless
        config.validate()
        config.ensure_directories()
        path = config.write(self.config_path, overwrite=True)
        self._write(f"配置已保存：{path}")

        if questionary.confirm("是否现在登录科研通？", default=True).ask():
            self._login(return_to="主菜单")

    def _account_management(self) -> None:
        while True:
            self._redraw()
            action = self._select(
                "账号管理",
                choices=[
                    Choice("登录账号", "login"),
                    Choice("积分管理", "points"),
                    Choice("返回", _BACK),
                ],
                escape_value=_BACK,
            )
            if action in (None, _BACK):
                return
            try:
                if action == "login":
                    self._login()
                elif action == "points":
                    self._points_management()
            except KeyboardInterrupt:
                self._write("\n操作已取消。")
                self._pause("按 Enter 返回账号管理")
            except Exception as exc:
                self._write(f"\n操作失败：{type(exc).__name__}: {exc}")
                self._pause("按 Enter 返回账号管理")

    def _login(self, *, return_to: str = "账号管理") -> None:
        self._redraw()
        mode = self._select(
            "登录方式",
            choices=[
                Choice("终端输入邮箱和密码", "credentials"),
                Choice("打开浏览器手动登录（验证码）", "browser"),
                Choice("返回", _BACK),
            ],
            escape_value=_BACK,
        )
        if mode in (None, _BACK):
            return

        app = self._app()
        if mode == "browser":
            self._write("即将打开浏览器；登录完成后按终端提示继续。")
            asyncio.run(app.login(headless=False))
        else:
            email = questionary.text(
                "科研通邮箱",
                validate=lambda value: bool(value.strip()) or "邮箱不能为空",
            ).ask()
            if email is None:
                return
            password = questionary.password(
                "科研通密码（不会保存）",
                validate=lambda value: bool(value) or "密码不能为空",
            ).ask()
            if password is None:
                return
            asyncio.run(
                app.login(
                    email=email.strip(),
                    password=password,
                    headless=True,
                )
            )
        self._write("登录成功，会话已保存到本地浏览器配置。")
        self._pause(f"按 Enter 返回{return_to}")

    def _points_management(self) -> None:
        while True:
            self._redraw()
            action = self._select(
                "积分管理",
                choices=[
                    Choice("积分刷新", "refresh"),
                    Choice("积分签到", "check_in"),
                    Choice("积分充值", "recharge"),
                    Choice("返回", _BACK),
                ],
                escape_value=_BACK,
            )
            if action in (None, _BACK):
                return
            try:
                if action == "refresh":
                    self._refresh_account_points()
                elif action == "check_in":
                    self._check_in()
                elif action == "recharge":
                    self._recharge_points()
            except KeyboardInterrupt:
                self._write("\n操作已取消。")
                self._pause("按 Enter 返回积分管理")
            except Exception as exc:
                self._write(f"\n操作失败：{type(exc).__name__}: {exc}")
                self._pause("按 Enter 返回积分管理")

    def _refresh_account_points(self) -> None:
        self._redraw()
        points = asyncio.run(self._app().account_points())
        self._write(f"当前科研通积分：{points.total}")
        self._write(f"获取时间：{points.retrieved_at}")
        self._pause("按 Enter 返回积分管理")

    def _check_in(self) -> None:
        self._redraw()
        points = asyncio.run(self._app().check_in())
        self._write(f"签到页面已关闭，当前科研通积分：{points.total}")
        self._pause("按 Enter 返回积分管理")

    def _recharge_points(self) -> None:
        self._redraw()
        points = asyncio.run(self._app().recharge_points())
        self._write(f"充值页面已关闭，当前科研通积分：{points.total}")
        self._pause("按 Enter 返回积分管理")

    def _fetch(self) -> None:
        while True:
            self._redraw()
            action = self._select(
                "下载文献",
                choices=[
                    Choice("下载单篇文献", "single"),
                    Choice("顺序下载多篇", "many"),
                    Choice("返回", _BACK),
                ],
                escape_value=_BACK,
            )
            if action in (None, _BACK):
                return
            completed = (
                self._fetch_single()
                if action == "single"
                else self._fetch_many()
            )
            if completed:
                return

    def _fetch_single(self) -> bool:
        self._redraw()
        query_prompt = questionary.text(
            "请输入单篇文献 DOI 或准确标题（Esc 返回）",
            validate=lambda value: bool(value.strip()) or "DOI 或标题不能为空",
        )
        _configure_escape_value(query_prompt, _BACK)
        query = query_prompt.ask()
        if query in (None, _BACK):
            return False
        query = normalize_query(query)

        options = self._choose_fetch_options()
        if options is None:
            return False
        mode, download_dir = options

        app = self._app()
        allow_repeat = False
        if app.has_publish_attempt(query):
            allow_repeat = bool(
                questionary.confirm(
                    "该 DOI/标题已有发布记录。你是否已在网站确认不存在重复求助？",
                    default=False,
                ).ask()
            )
            if not allow_repeat:
                self._write("已取消，未再次发布。")
                self._pause()
                return True

        if not questionary.confirm("确认开始获取文献？", default=True).ask():
            return False
        task = asyncio.run(
            app.fetch(
                query,
                download_dir=download_dir,
                headless=mode,
                allow_repeat=allow_repeat,
            )
        )
        self._show_task(task)
        self._pause()
        return True

    def _fetch_many(self) -> bool:
        queries = self._collect_fetch_queries()
        if queries is None:
            return False
        options = self._choose_fetch_options()
        if options is None:
            return False
        mode, download_dir = options

        self._redraw()
        self._write(f"顺序下载队列 · 共 {len(queries)} 篇")
        for index, query in enumerate(queries, start=1):
            self._write(f"  {index}. {query}")

        app = self._app()
        repeated = [query for query in queries if app.has_publish_attempt(query)]
        allow_repeat = False
        if repeated:
            self._write("")
            self._write(f"其中 {len(repeated)} 篇已有发布记录：")
            for query in repeated:
                self._write(f"  - {query}")
            allow_repeat = bool(
                questionary.confirm(
                    "是否已在网站确认这些文献不存在重复求助？",
                    default=False,
                ).ask()
            )
            if not allow_repeat:
                self._write("已取消，未发布队列。")
                self._pause()
                return True

        if not questionary.confirm(
            "确认按以上顺序逐篇获取？",
            default=True,
        ).ask():
            return False
        result = asyncio.run(
            app.fetch_many(
                queries,
                download_dir=download_dir,
                headless=mode,
                allow_repeat=allow_repeat,
            )
        )
        self._show_fetch_queue(result)
        self._pause()
        return True

    def _collect_fetch_queries(self) -> list[str] | None:
        self._redraw()
        self._write(
            "请逐行输入 DOI 或准确标题；直接按 Enter 结束，Esc 取消。"
        )
        self._write(f"单次最多 {MAX_FETCH_QUEUE_ITEMS} 篇，不会并发发布。")
        queries: list[str] = []
        while len(queries) < MAX_FETCH_QUEUE_ITEMS:
            prompt = questionary.text(f"第 {len(queries) + 1} 篇")
            _configure_escape_value(prompt, _BACK)
            value = prompt.ask()
            if value in (None, _BACK):
                return None
            if not value.strip():
                if queries:
                    break
                self._write("请至少输入一篇文献。")
                continue
            query = normalize_query(value)
            if query.casefold() in {item.casefold() for item in queries}:
                self._write("该 DOI/标题已在队列中，请输入其他文献。")
                continue
            queries.append(query)
        return normalize_queries(queries)

    def _choose_fetch_options(self) -> tuple[bool, Path | None] | None:
        self._redraw()
        config = AppConfig.load(self.config_path)
        mode = self._select(
            "运行模式",
            choices=[
                Choice(
                    "无界面运行"
                    + ("（当前默认）" if config.headless else ""),
                    True,
                ),
                Choice(
                    "显示浏览器"
                    + ("（当前默认）" if not config.headless else ""),
                    False,
                ),
                Choice("返回上一步", _BACK),
            ],
            default=config.headless,
            escape_value=_BACK,
        )
        if mode in (None, _BACK):
            return None

        download_dir: Path | None = None
        if questionary.confirm("本次临时更改下载目录？", default=False).ask():
            chosen_dir = questionary.text(
                "本次下载目录",
                default=str(config.download_dir),
                validate=lambda value: bool(value.strip()) or "目录不能为空",
            ).ask()
            if chosen_dir is None:
                return None
            download_dir = Path(chosen_dir).expanduser().resolve()
        return bool(mode), download_dir

    def _show_fetch_queue(self, result: FetchQueueResult) -> None:
        self._write("")
        self._write(
            f"顺序下载结果：成功 {result.successful_count}/"
            f"{len(result.queries)} 篇"
        )
        for index, task in enumerate(result.tasks, start=1):
            status = _STATUS_LABELS.get(task.status, task.status.value)
            path = f" · {task.download_path}" if task.download_path else ""
            self._write(f"  {index}. {status} · {task.query}{path}")
        if result.error:
            self._write(
                f"队列已停止：{result.stopped_query or '-'} · "
                f"{result.error['type']}: {result.error['message']}"
            )

    def _history(self) -> None:
        while True:
            self._redraw()
            action = self._select(
                "历史记录",
                choices=[
                    Choice("查看任务与下载记录", "records"),
                    Choice("恢复未完成求助", "recover"),
                    Choice("处理历史待确认", "accept_all"),
                    Choice("返回", _BACK),
                ],
                escape_value=_BACK,
            )
            if action in (None, _BACK):
                return
            if action == "records":
                self._history_records()
            elif action == "recover":
                self._recover()
                self._pause("按 Enter 返回历史记录")
            elif action == "accept_all":
                self._accept_all()
                self._pause("按 Enter 返回历史记录")

    def _history_records(self) -> None:
        app = self._app()
        while True:
            self._redraw()
            tasks = app.list_tasks(limit=50)
            if not tasks:
                self._write("暂无历史任务。")
                return
            choices = [
                Choice(self._history_task_choice(index, task), task.id)
                for index, task in enumerate(tasks, start=1)
            ]
            choices.append(Choice("返回", _BACK))
            task_id = self._select(
                "文献与下载记录",
                choices=choices,
                escape_value=_BACK,
            )
            if task_id in (None, _BACK):
                return
            task = app.get_task(task_id)
            self._redraw()
            self._show_task(task, include_events=True)
            self._task_actions(app, task)

    def _task_actions(self, app: LiteratureHelper, task: Task) -> None:
        choices = [
            Choice("删除该历史记录", "delete"),
            Choice("返回历史记录", _BACK),
        ]
        if task.status == TaskStatus.DOWNLOADED_PENDING_REVIEW:
            choices[:0] = [
                Choice("立即在网站采纳文件", "confirm"),
                Choice("将文件标记为有误", "reject"),
            ]
        elif task.status in {
            TaskStatus.CREATED,
            TaskStatus.WAITING_LOGIN,
            TaskStatus.MATCHING,
            TaskStatus.READY_TO_PUBLISH,
            TaskStatus.PUBLISHED,
            TaskStatus.WAITING_FILE,
            TaskStatus.DOWNLOADING,
        }:
            choices.insert(0, Choice("解除本地活动任务", "cancel"))
        if task.request_url and task.status in {
            TaskStatus.FAILED,
            TaskStatus.TIMED_OUT,
            TaskStatus.WAITING_FILE,
        }:
            choices.insert(0, Choice("尝试恢复下载", "recover"))

        self._write("")
        action = self._select(
            "任务操作",
            choices=choices,
            escape_value=_BACK,
        )
        if action in (None, _BACK):
            return
        if action == "confirm":
            if questionary.confirm("确认采纳该文件？", default=True).ask():
                self._show_task(asyncio.run(app.confirm(task.id)))
        elif action == "reject":
            reason = questionary.text(
                "标记原因",
                validate=lambda value: bool(value.strip()) or "原因不能为空",
            ).ask()
            if reason:
                self._show_task(app.reject(task.id, reason=reason.strip()))
        elif action == "cancel":
            if questionary.confirm(
                "只解除本地任务，不会关闭网站求助。确认继续？",
                default=False,
            ).ask():
                self._show_task(app.cancel(task.id))
        elif action == "recover":
            self._show_task(asyncio.run(app.recover(task.id)))
        elif action == "delete":
            confirmed = questionary.confirm(
                "确认删除该历史记录？任务事件会一并删除；"
                "已下载的 PDF 和科研通网站求助会保留。",
                default=False,
            ).ask()
            if confirmed:
                deleted = app.delete_task(task.id)
                self._redraw()
                self._write(f"已删除历史记录：{self._task_title(deleted)}")
                if deleted.download_path:
                    self._write(f"PDF 文件仍保留在：{deleted.download_path}")
                self._pause("按 Enter 返回历史记录")

    def _recover(self) -> None:
        self._redraw()
        app = self._app()
        recoverable = [
            task
            for task in app.list_tasks(limit=50)
            if task.status
            in {
                TaskStatus.PUBLISHED,
                TaskStatus.WAITING_FILE,
                TaskStatus.DOWNLOADING,
                TaskStatus.FAILED,
                TaskStatus.TIMED_OUT,
            }
        ]
        choices = [
            Choice("从科研通网站待确认列表选择", _SITE_PENDING),
            *[Choice(self._task_choice(task), task.id) for task in recoverable],
            Choice("返回", _BACK),
        ]
        selected = self._select(
            "选择要恢复的求助",
            choices=choices,
            escape_value=_BACK,
        )
        if selected in (None, _BACK):
            return
        task_id = None if selected == _SITE_PENDING else selected
        self._show_task(asyncio.run(app.recover(task_id)))

    def _accept_all(self) -> None:
        self._redraw()
        if not questionary.confirm(
            "将采纳科研通网站中全部历史待确认文件，是否继续？",
            default=False,
        ).ask():
            return
        result = asyncio.run(self._app().accept_all())
        self._write(
            f"处理完成：网站采纳 {result.website_count} 条，"
            f"本地同步 {result.local_count} 条。"
        )

    def _settings(self) -> None:
        config = AppConfig.load(self.config_path)
        while True:
            self._redraw()
            action = self._select(
                "设置",
                choices=[
                    Choice(f"下载目录  {config.download_dir}", "download_dir"),
                    Choice(
                        "默认模式  " + ("无界面" if config.headless else "显示浏览器"),
                        "headless",
                    ),
                    Choice(
                        f"等待应助超时  {config.poll_timeout_seconds:g} 秒",
                        "timeout",
                    ),
                    Choice(
                        "高速通道  "
                        + ("优先" if config.prefer_high_speed_download else "不优先"),
                        "high_speed",
                    ),
                    Choice("环境检查", "doctor"),
                    Choice("返回", _BACK),
                ],
                escape_value=_BACK,
            )
            if action in (None, _BACK):
                return
            if action == "doctor":
                self._doctor()
                self._pause("按 Enter 返回设置")
                continue
            if action == "download_dir":
                value = questionary.text(
                    "默认下载目录",
                    default=str(config.download_dir),
                    validate=lambda item: bool(item.strip()) or "目录不能为空",
                ).ask()
                if value:
                    config.download_dir = Path(value).expanduser().resolve()
            elif action == "headless":
                value = questionary.confirm(
                    "默认使用无界面模式？",
                    default=config.headless,
                ).ask()
                if value is not None:
                    config.headless = value
            elif action == "timeout":
                value = questionary.text(
                    "等待应助超时秒数",
                    default=f"{config.poll_timeout_seconds:g}",
                    validate=_positive_number,
                ).ask()
                if value:
                    config.poll_timeout_seconds = float(value)
            elif action == "high_speed":
                value = questionary.confirm(
                    "优先使用高速通道？",
                    default=config.prefer_high_speed_download,
                ).ask()
                if value is not None:
                    config.prefer_high_speed_download = value

            config.validate()
            config.ensure_directories()
            config.write(self.config_path, overwrite=True)

    def _doctor(self) -> None:
        self._redraw()
        app = self._app()
        checks = app.diagnostics()
        self._write(json.dumps(checks, ensure_ascii=False, indent=2))
        self._write("环境检查通过。" if app.diagnostics_ok() else "环境检查未通过。")

    def _show_task(self, task: Task, *, include_events: bool = False) -> None:
        missing = "未识别"
        self._write("智能识别文献信息")
        if task.literature is None:
            self._write("  暂无：该任务尚未保存智能识别结果")
        else:
            literature = task.literature
            self._write(f"  标题：{literature.title or missing}")
            self._write(f"  DOI：{literature.doi or missing}")
            self._write(f"  文献链接：{literature.url or missing}")
            self._write(f"  期刊：{literature.journal or missing}")
            self._write(
                "  作者："
                + ("; ".join(literature.authors) if literature.authors else missing)
            )
            self._write(f"  出版日期：{literature.publication_date or missing}")
            self._write(
                "  出版年份："
                + (
                    str(literature.publication_year)
                    if literature.publication_year is not None
                    else missing
                )
            )
            self._write(f"  数据来源：{literature.source or missing}")
            self._write(f"  识别时间：{literature.extracted_at or missing}")

        self._write("")
        self._write("任务与文件")
        self._write(f"  任务 ID：{task.id}")
        self._write(f"  原始输入：{task.query}")
        self._write(f"  输入类型：{task.query_type.upper()}")
        self._write(f"  状态：{_STATUS_LABELS.get(task.status, task.status.value)}")
        self._write(f"  创建时间：{task.created_at}")
        self._write(f"  更新时间：{task.updated_at}")
        if task.request_url:
            self._write(f"  求助地址：{task.request_url}")
        if task.download_path:
            self._write(f"  下载文件：{task.download_path}")
        if task.validation:
            self._write(
                "  PDF："
                f"{task.validation.get('page_count') or '?'} 页 · "
                f"{task.validation.get('size_bytes') or 0} 字节 · "
                + ("检查通过" if task.validation.get("ok") else "检查未通过")
            )
        if task.error:
            self._write(f"  异常：{task.error}")
        if include_events:
            events = self._app().task_events(task.id)
            self._write("")
            self._write("最近事件：")
            for event in events[-8:]:
                message = event.get("message") or "-"
                self._write(
                    f"  {event.get('created_at') or '-'}  "
                    f"{event.get('status') or '-'}  {message}"
                )

    @classmethod
    def _history_task_choice(cls, index: int, task: Task) -> str:
        return f"{index:>2}. {cls._task_title(task)[:88]}"

    @staticmethod
    def _task_choice(task: Task) -> str:
        title = LiteratureHelperTUI._task_title(task)
        status = _STATUS_LABELS.get(task.status, task.status.value)
        downloaded = " · PDF" if task.download_path else ""
        return f"{status}{downloaded}  {title[:70]}  [{task.id}]"

    @staticmethod
    def _task_title(task: Task) -> str:
        if task.literature is not None:
            if task.literature.title:
                return task.literature.title
            if task.literature.doi:
                return task.literature.doi
        return task.query or f"未命名任务 [{task.id}]"

    def _pause(self, message: str = "按 Enter 返回主菜单") -> None:
        self._write("")
        questionary.text(message, default="", style=TUI_STYLE).ask()


def _build_header_box(
    *,
    width: int,
    logo: str,
    mode: str,
    download_dir: str,
    version: str,
) -> list[str]:
    return [
        "".join(text for _style, text in line)
        for line in _build_header_fragments(
            width=width,
            logo=logo,
            mode=mode,
            download_dir=download_dir,
            version=version,
        )
    ]


def _build_header_fragments(
    *,
    width: int,
    logo: str,
    mode: str,
    download_dir: str,
    version: str,
) -> list[list[tuple[str, str]]]:
    width = max(4, width)
    inner_width = width - 2
    top = [(_FRAME_STYLE, "┌" + "─" * inner_width + "┐")]
    blank = [
        (_FRAME_STYLE, "│"),
        ("", " " * inner_width),
        (_FRAME_STYLE, "│"),
    ]
    logo_rows = [
        [
            (_FRAME_STYLE, "│"),
            (
                _LOGO_STYLE,
                _fit_display(f"  {line}", inner_width, align="left"),
            ),
            (_FRAME_STYLE, "│"),
        ]
        for line in logo.splitlines()
    ]
    label_width = min(inner_width, _display_width("  DOWNLOADS  "))
    divider_width = 1 if inner_width > label_width else 0
    value_width = max(0, inner_width - label_width - divider_width)
    info_rows = [
        [
            (_FRAME_STYLE, "│"),
            (
                _INFO_STYLE,
                _fit_display(label, label_width, align="left"),
            ),
            (_INFO_STYLE, "│" if divider_width else ""),
            (
                _INFO_STYLE,
                _fit_display(f"  {value}", value_width, align="left"),
            ),
            (_FRAME_STYLE, "│"),
        ]
        for label, value in (
            ("  MODE", mode),
            ("  DOWNLOADS", download_dir),
        )
    ]
    bottom = [
        (
            _FRAME_STYLE,
            _build_titled_bottom_border(
                width=width,
                title=f"LITERATURE HELPER · v{version}",
            ),
        )
    ]
    return [
        top,
        blank,
        *logo_rows,
        blank,
        *info_rows,
        blank,
        bottom,
    ]


def _build_titled_bottom_border(*, width: int, title: str) -> str:
    inner_width = max(0, width - 2)
    title = _truncate_display(f" {title} ", inner_width)
    remaining = max(0, inner_width - _display_width(title))
    trailing_width = min(3, remaining)
    leading_width = remaining - trailing_width
    return (
        "└"
        + "─" * leading_width
        + title
        + "─" * trailing_width
        + "┘"
    )


def _fit_display(text: str, width: int, *, align: str) -> str:
    text = _truncate_display(text, width)
    padding = " " * max(0, width - _display_width(text))
    return padding + text if align == "right" else text + padding


def _truncate_display(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if _display_width(text) <= width:
        return text

    target = max(0, width - 1)
    result: list[str] = []
    used = 0
    for character in text:
        character_width = _character_width(character)
        if used + character_width > target:
            break
        result.append(character)
        used += character_width
    return "".join(result) + "…"


def _display_width(text: str) -> int:
    return sum(_character_width(character) for character in text)


def _character_width(character: str) -> int:
    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1


def _positive_number(value: str) -> bool | str:
    try:
        return float(value) > 0 or "请输入大于 0 的数字"
    except ValueError:
        return "请输入有效数字"


def _configure_escape_value(question: Any, value: object) -> bool:
    application = getattr(question, "application", None)
    bindings = getattr(application, "key_bindings", None)
    if bindings is None or not hasattr(bindings, "add"):
        return False

    @bindings.add(Keys.Escape, eager=True)
    def return_to_parent(event: Any) -> None:
        event.app.exit(result=value)

    return True


def _add_question_spacing(question: Any) -> bool:
    application = getattr(question, "application", None)
    layout = getattr(application, "layout", None)
    container = getattr(layout, "container", None)
    children = getattr(container, "children", None)
    if not children:
        return False
    container.children = [
        children[0],
        Window(height=1),
        *children[1:],
    ]
    return True


def _configure_bounded_navigation(question: Any) -> InquirerControl | None:
    """Stop arrow-key selection at the first and last visible choices."""
    application = getattr(question, "application", None)
    layout = getattr(application, "layout", None)
    container = getattr(layout, "container", None)
    for child in getattr(container, "children", ()):
        window = getattr(child, "content", None)
        control = getattr(window, "content", None)
        if isinstance(control, InquirerControl):
            control.select_next = MethodType(_select_next_bounded, control)
            control.select_previous = MethodType(_select_previous_bounded, control)
            return control
    return None


def _select_next_bounded(control: InquirerControl) -> None:
    _move_selection_bounded(control, 1)


def _select_previous_bounded(control: InquirerControl) -> None:
    _move_selection_bounded(control, -1)


def _move_selection_bounded(control: InquirerControl, step: int) -> None:
    original = control.pointed_at
    candidate = original + step
    while 0 <= candidate < control.choice_count:
        control.pointed_at = candidate
        if control.is_selection_valid():
            return
        candidate += step
    control.pointed_at = original


def run_tui(*, config_path: Path | None = None) -> int:
    return LiteratureHelperTUI(config_path=config_path).run()
