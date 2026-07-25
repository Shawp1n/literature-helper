from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Callable

import questionary
from questionary import Choice

from . import __version__
from .api import LiteratureHelper
from .config import AppConfig, default_home
from .diagnostics import collect_diagnostics, diagnostics_ok
from .models import Task, TaskStatus


LOGO = r"""
┃  ┛━┏┛┃ ┃┏━┛┃  ┏━┃┏━┛┏━┃
┃  ┃ ┃ ┏━┃┏━┛┃  ┏━┛┏━┛┏┏┛
━━┛┛ ┛ ┛ ┛━━┛━━┛┛  ━━┛┛ ┛
""".strip("\n")

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

    @property
    def resolved_config_path(self) -> Path:
        return self.config_path or (default_home() / "config.json")

    def run(self) -> int:
        self._show_header()
        if not self.resolved_config_path.exists():
            proceed = questionary.confirm(
                "检测到首次使用，是否现在完成基础设置？",
                default=True,
            ).ask()
            if proceed:
                self._setup()

        while True:
            action = questionary.select(
                "请选择功能",
                choices=[
                    Choice("获取文献", "fetch"),
                    Choice("历史任务与下载记录", "history"),
                    Choice("恢复网站已有求助", "recover"),
                    Choice("批量采纳历史待确认", "accept_all"),
                    Choice("登录账号（密码不保存）", "login"),
                    Choice("设置", "settings"),
                    Choice("环境检查", "doctor"),
                    Choice("退出", "exit"),
                ],
                pointer="❯",
                qmark="",
            ).ask()
            if action in (None, "exit"):
                self.output("已退出 Literature Helper。")
                return 0

            handlers = {
                "fetch": self._fetch,
                "history": self._history,
                "recover": self._recover,
                "accept_all": self._accept_all,
                "login": self._login,
                "settings": self._settings,
                "doctor": self._doctor,
            }
            try:
                handlers[action]()
            except KeyboardInterrupt:
                self.output("\n操作已取消。")
            except Exception as exc:
                self.output(f"\n操作失败：{type(exc).__name__}: {exc}")
            self._pause()

    def _show_header(self) -> None:
        self.output(LOGO)
        self.output(f" Literature Helper {__version__} · 文献获取与管理\n")

    def _app(self) -> LiteratureHelper:
        return LiteratureHelper(
            config_path=self.config_path,
            output=self.output,
        )

    def _setup(self) -> None:
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
        self.output(f"配置已保存：{path}")

        if questionary.confirm("是否现在登录科研通？", default=True).ask():
            self._login()

    def _login(self) -> None:
        mode = questionary.select(
            "登录方式",
            choices=[
                Choice("终端输入邮箱和密码", "credentials"),
                Choice("打开浏览器手动登录（验证码）", "browser"),
                Choice("返回", _BACK),
            ],
            pointer="❯",
            qmark="",
        ).ask()
        if mode in (None, _BACK):
            return

        app = self._app()
        if mode == "browser":
            self.output("即将打开浏览器；登录完成后按终端提示继续。")
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
        self.output("登录成功，会话已保存到本地浏览器配置。")

    def _fetch(self) -> None:
        query = questionary.text(
            "请输入单篇文献 DOI 或准确标题",
            validate=lambda value: bool(value.strip()) or "DOI 或标题不能为空",
        ).ask()
        if query is None:
            return

        config = AppConfig.load(self.config_path)
        mode = questionary.select(
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
                Choice("返回", _BACK),
            ],
            default=config.headless,
            pointer="❯",
            qmark="",
        ).ask()
        if mode in (None, _BACK):
            return

        download_dir: Path | None = None
        if questionary.confirm("本次临时更改下载目录？", default=False).ask():
            chosen_dir = questionary.text(
                "本次下载目录",
                default=str(config.download_dir),
                validate=lambda value: bool(value.strip()) or "目录不能为空",
            ).ask()
            if chosen_dir is None:
                return
            download_dir = Path(chosen_dir).expanduser().resolve()

        app = self._app()
        allow_repeat = False
        if app.store.publish_attempt_exists(query.strip()):
            allow_repeat = bool(
                questionary.confirm(
                    "该 DOI/标题已有发布记录。你是否已在网站确认不存在重复求助？",
                    default=False,
                ).ask()
            )
            if not allow_repeat:
                self.output("已取消，未再次发布。")
                return

        if not questionary.confirm("确认开始获取文献？", default=True).ask():
            return
        task = asyncio.run(
            app.fetch(
                query.strip(),
                download_dir=download_dir,
                headless=mode,
                allow_repeat=allow_repeat,
            )
        )
        self._show_task(task)

    def _history(self) -> None:
        app = self._app()
        while True:
            tasks = app.list_tasks(limit=50)
            if not tasks:
                self.output("暂无历史任务。")
                return
            choices = [
                Choice(self._task_choice(task), task.id)
                for task in tasks
            ]
            choices.append(Choice("返回", _BACK))
            task_id = questionary.select(
                "历史任务与下载记录",
                choices=choices,
                pointer="❯",
                qmark="",
            ).ask()
            if task_id in (None, _BACK):
                return
            task = app.store.get(task_id)
            self._show_task(task, include_events=True)
            self._task_actions(app, task)

    def _task_actions(self, app: LiteratureHelper, task: Task) -> None:
        choices = [Choice("返回历史记录", _BACK)]
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

        action = questionary.select(
            "任务操作",
            choices=choices,
            pointer="❯",
            qmark="",
        ).ask()
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

    def _recover(self) -> None:
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
        selected = questionary.select(
            "选择要恢复的求助",
            choices=choices,
            pointer="❯",
            qmark="",
        ).ask()
        if selected in (None, _BACK):
            return
        task_id = None if selected == _SITE_PENDING else selected
        self._show_task(asyncio.run(app.recover(task_id)))

    def _accept_all(self) -> None:
        if not questionary.confirm(
            "将采纳科研通网站中全部历史待确认文件，是否继续？",
            default=False,
        ).ask():
            return
        result = asyncio.run(self._app().accept_all())
        self.output(
            f"处理完成：网站采纳 {result.website_count} 条，"
            f"本地同步 {result.local_count} 条。"
        )

    def _settings(self) -> None:
        config = AppConfig.load(self.config_path)
        while True:
            action = questionary.select(
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
                    Choice("返回", _BACK),
                ],
                pointer="❯",
                qmark="",
            ).ask()
            if action in (None, _BACK):
                return
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
            path = config.write(self.config_path, overwrite=True)
            self.output(f"设置已保存：{path}")

    def _doctor(self) -> None:
        config = AppConfig.load(self.config_path)
        config.validate()
        checks = collect_diagnostics(config, config_path=self.config_path)
        self.output(json.dumps(checks, ensure_ascii=False, indent=2))
        self.output("环境检查通过。" if diagnostics_ok(checks) else "环境检查未通过。")

    def _show_task(self, task: Task, *, include_events: bool = False) -> None:
        self.output("")
        self.output(f"任务：{task.id}")
        self.output(f"状态：{_STATUS_LABELS.get(task.status, task.status.value)}")
        if task.literature:
            if task.literature.title:
                self.output(f"标题：{task.literature.title}")
            if task.literature.doi:
                self.output(f"DOI：{task.literature.doi}")
            if task.literature.journal:
                self.output(f"期刊：{task.literature.journal}")
            if task.literature.authors:
                self.output("作者：" + "; ".join(task.literature.authors))
            if task.literature.publication_date:
                self.output(f"出版日期：{task.literature.publication_date}")
        else:
            self.output(f"输入：{task.query}")
        if task.download_path:
            self.output(f"文件：{task.download_path}")
        if task.validation:
            self.output(
                "PDF："
                f"{task.validation.get('page_count') or '?'} 页 · "
                f"{task.validation.get('size_bytes') or 0} 字节 · "
                + ("检查通过" if task.validation.get("ok") else "检查未通过")
            )
        if task.error:
            self.output(f"异常：{task.error}")
        if include_events:
            events = self._app().store.events(task.id)
            self.output("最近事件：")
            for event in events[-8:]:
                message = event.get("message") or "-"
                self.output(
                    f"  {event['created_at']}  {event['status']}  {message}"
                )

    @staticmethod
    def _task_choice(task: Task) -> str:
        title = task.literature.title if task.literature else task.query
        status = _STATUS_LABELS.get(task.status, task.status.value)
        downloaded = " · PDF" if task.download_path else ""
        return f"{status}{downloaded}  {title[:70]}  [{task.id}]"

    @staticmethod
    def _pause() -> None:
        questionary.text("按 Enter 返回主菜单", default="").ask()


def _positive_number(value: str) -> bool | str:
    try:
        return float(value) > 0 or "请输入大于 0 的数字"
    except ValueError:
        return "请输入有效数字"


def run_tui(*, config_path: Path | None = None) -> int:
    return LiteratureHelperTUI(config_path=config_path).run()
