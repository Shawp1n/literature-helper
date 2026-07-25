from __future__ import annotations

import argparse
import asyncio
from enum import IntEnum
import getpass
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .adapter import LoginRequired, PageStructureChanged, PollTimedOut
from .api import LiteratureHelper
from .config import AppConfig, ConfigError
from .models import FetchQueueResult, Task, TaskStatus


class CliExitCode(IntEnum):
    """Stable process exit codes for scripts and Agent callers."""

    OK = 0
    USAGE = 64
    NO_INPUT = 66
    UNAVAILABLE = 69
    SOFTWARE = 70
    TEMPORARY_FAILURE = 75
    AUTH_REQUIRED = 77
    CONFIG = 78
    INTERRUPTED = 130


class CliUsageError(ValueError):
    """The requested CLI invocation cannot be executed as supplied."""


def exit_code_for_exception(exc: Exception) -> CliExitCode:
    if isinstance(exc, CliUsageError):
        return CliExitCode.USAGE
    if isinstance(exc, LoginRequired):
        return CliExitCode.AUTH_REQUIRED
    if isinstance(exc, (PollTimedOut, TimeoutError)):
        return CliExitCode.TEMPORARY_FAILURE
    if isinstance(exc, (FileNotFoundError, KeyError)):
        return CliExitCode.NO_INPUT
    if isinstance(exc, PageStructureChanged):
        return CliExitCode.UNAVAILABLE
    if isinstance(
        exc,
        (ConfigError, FileExistsError, json.JSONDecodeError, PermissionError),
    ):
        return CliExitCode.CONFIG
    if isinstance(exc, ValueError):
        return CliExitCode.USAGE
    return CliExitCode.SOFTWARE


def error_document(
    exc: BaseException,
    *,
    command: str | None,
    exit_code: int,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "type": type(exc).__name__,
            "message": str(exc),
        },
        "meta": {
            "command": command,
            "exit_code": exit_code,
        },
    }


class ContractArgumentParser(argparse.ArgumentParser):
    """Use a stable usage-error code instead of argparse's generic code 2."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(CliExitCode.USAGE, f"{self.prog}: error: {message}\n")


def _add_runtime_options(
    parser: argparse.ArgumentParser,
    *,
    with_defaults: bool,
) -> None:
    default = None if with_defaults else argparse.SUPPRESS
    parser.add_argument(
        "--config",
        type=Path,
        default=default,
        help="配置文件路径（默认位于用户数据目录）",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("table", "json"),
        default="table" if with_defaults else argparse.SUPPRESS,
        help="输出格式：table（默认）或 json",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False if with_defaults else argparse.SUPPRESS,
        help="兼容别名，等价于 --format json",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        default=False if with_defaults else argparse.SUPPRESS,
        help="禁止等待人工输入；适用于 Agent、CI 和调度器",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = ContractArgumentParser(
        prog="lithelper",
        description="Literature Helper：面向人类与 Agent 的个人文献获取工具",
    )
    parser.add_argument("--version", action="version", version=__version__)
    _add_runtime_options(parser, with_defaults=True)
    commands = parser.add_subparsers(
        dest="command",
        parser_class=ContractArgumentParser,
    )

    def command(name: str, **kwargs: object) -> argparse.ArgumentParser:
        child = commands.add_parser(name, **kwargs)
        _add_runtime_options(child, with_defaults=False)
        return child

    command("tui", help="打开方向键交互界面")

    init = command("init", help="创建默认配置和数据目录")
    init.add_argument("--force", action="store_true", help="覆盖已有配置")

    login = command("login", help="登录科研通并保存本地会话")
    login.add_argument(
        "--email",
        help="科研通邮箱；省略时在终端提示输入",
    )
    login.add_argument(
        "--manual-browser",
        action="store_true",
        help="打开浏览器手动登录，用于处理验证码等情况",
    )

    points = command("points", help="查询当前登录账号的科研通积分")
    points.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="无头查询积分",
    )

    command("check-in", help="打开科研通首页，手动完成积分签到")
    command("recharge", help="打开科研通官方页面，手动完成积分充值")

    fetch = command("fetch", help="发布单篇求助并等待 PDF")
    fetch.add_argument("query", help="单篇文献 DOI 或准确标题")
    fetch.add_argument("--download-dir", type=Path, help="本次下载目录")
    fetch.add_argument(
        "--manual-publish",
        action="store_true",
        help="停在最终发布前，由用户检查并手动点击",
    )
    fetch.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="无头运行（须已登录且不会遇到验证码）",
    )
    fetch.add_argument(
        "--allow-repeat-after-checking-site",
        action="store_true",
        help="已人工检查“我的求助”后，允许重复 DOI/标题再次发布",
    )

    fetch_many = command(
        "fetch-many",
        help="按输入顺序逐篇发布、等待并下载",
    )
    fetch_many.add_argument(
        "queries",
        nargs="+",
        metavar="QUERY",
        help="多个 DOI 或准确标题；包含空格的标题需要使用引号",
    )
    fetch_many.add_argument("--download-dir", type=Path, help="本次下载目录")
    fetch_many.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="无头顺序下载（须已登录）",
    )
    fetch_many.add_argument(
        "--allow-repeat-after-checking-site",
        action="store_true",
        help="已人工检查网站后，允许队列中的历史 DOI/标题再次发布",
    )

    recover = command(
        "recover",
        help="从网站待确认列表恢复下载，不再发布新求助",
    )
    recover.add_argument(
        "task_id",
        nargs="?",
        help="可选的本地任务 ID；省略时从网站列表选择并新建恢复记录",
    )
    recover.add_argument("--download-dir", type=Path, help="本次下载目录")
    recover.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="无头恢复下载",
    )

    accept_all = command(
        "accept-all",
        help="批量采纳网站上全部历史待确认求助",
    )
    accept_all.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="无头批量采纳",
    )

    listing = command("list", help="列出最近任务")
    listing.add_argument("--limit", type=int, default=20)

    show = command("show", help="显示任务详情和事件")
    show.add_argument("task_id")

    confirm = command(
        "confirm",
        help="立即同步在科研通采纳指定文件",
    )
    confirm.add_argument("task_id")
    confirm.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="无头执行网站采纳",
    )

    reject = command("reject", help="标记下载的文件有误（不会操作网站）")
    reject.add_argument("task_id")
    reject.add_argument("--reason", required=True, help="本地记录原因")

    cancel = command("cancel", help="解除中断后遗留的本地活动任务")
    cancel.add_argument("task_id")

    command("doctor", help="检查本地配置和 Python 依赖")
    return parser


def _config_from_args(args: argparse.Namespace) -> AppConfig:
    return AppConfig.load(args.config)


def _app_from_args(args: argparse.Namespace) -> LiteratureHelper:
    output = (
        (lambda message: print(message, file=sys.stderr))
        if args.json
        else print
    )
    input_func = input
    if args.non_interactive:
        def input_func(_prompt: str) -> str:
            raise RuntimeError("非交互模式禁止等待人工输入")

    return LiteratureHelper(
        config_path=args.config,
        output=output,
        input_func=input_func,
    )


def _print_task_summary(task: Task) -> None:
    labels = {
        TaskStatus.DOWNLOADED_PENDING_REVIEW: "PDF 已下载，等待下次 fetch 自动采纳",
        TaskStatus.CONFIRMED: "已采纳并确认",
        TaskStatus.REJECTED: "已标记为文件有误",
        TaskStatus.TIMED_OUT: "仍在等待应助",
        TaskStatus.CANCELLED: "本地任务已取消",
        TaskStatus.FAILED: "执行失败",
    }
    label = labels.get(task.status, task.status.value)
    print(f"任务结果：{task.id} · {label}")
    if task.literature:
        if task.literature.title:
            print(f"文献标题：{task.literature.title}")
        details = [
            value
            for value in (
                f"DOI {task.literature.doi}" if task.literature.doi else None,
                task.literature.journal,
                task.literature.publication_date,
            )
            if value
        ]
        if details:
            print("文献信息：" + " · ".join(details))
    if task.download_path:
        print(f"文件位置：{task.download_path}")
    if task.error:
        print(f"异常信息：{task.error}")
    print(f"完整记录：lithelper show {task.id}")


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_task_details(payload: dict[str, object]) -> None:
    task = payload
    print(f"任务：{task['id']}")
    print(f"状态：{task['status']}")
    literature = task.get("literature")
    if isinstance(literature, dict):
        for label, field in (
            ("标题", "title"),
            ("DOI", "doi"),
            ("期刊", "journal"),
            ("出版日期", "publication_date"),
        ):
            if value := literature.get(field):
                print(f"{label}：{value}")
    if path := task.get("download_path"):
        print(f"文件：{path}")
    if error := task.get("error"):
        print(f"异常：{error}")
    events = task.get("events")
    if isinstance(events, list) and events:
        print("事件：")
        for event in events:
            if not isinstance(event, dict):
                continue
            message = event.get("message") or "-"
            print(
                f"  {event.get('created_at')}  "
                f"{event.get('status')}  {message}"
            )


def _prompt_email() -> str:
    print("科研通邮箱：", end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip()


def _emit_task(task: Task, *, as_json: bool) -> None:
    if as_json:
        _print_json(task.to_dict())
    else:
        _print_task_summary(task)


def _emit_fetch_queue(result: FetchQueueResult, *, as_json: bool) -> None:
    if as_json:
        _print_json(result.to_dict())
        return
    print(
        f"顺序下载结果：成功 {result.successful_count}/{len(result.queries)} 篇，"
        f"已处理 {len(result.tasks)} 篇。"
    )
    for index, task in enumerate(result.tasks, start=1):
        path = str(task.download_path) if task.download_path else "-"
        print(
            f"  {index}. {task.status.value:27}  "
            f"{task.query[:52]}  {path}"
        )
    if result.error:
        print(
            f"队列停止：{result.stopped_query or '-'} · "
            f"{result.error['type']}: {result.error['message']}"
        )


def command_init(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    config.validate()
    config.ensure_directories()
    path = config.write(args.config, overwrite=args.force)
    LiteratureHelper(config=config)
    if args.json:
        _print_json(
            {
                "config_path": str(path),
                "download_dir": str(config.download_dir),
            }
        )
    else:
        print(f"配置已创建：{path}")
        print(f"下载目录：{config.download_dir}")
        print("下一步：lithelper login，或直接运行 lithelper 打开交互界面")
    return 0


def command_list(args: argparse.Namespace) -> int:
    tasks = _app_from_args(args).list_tasks(limit=args.limit)
    if args.json:
        _print_json([task.to_dict() for task in tasks])
        return 0
    if not tasks:
        print("暂无任务")
        return 0
    for task in tasks:
        path = str(task.download_path) if task.download_path else "-"
        print(f"{task.id}  {task.status.value:27}  {task.query[:52]}  {path}")
    return 0


def command_show(args: argparse.Namespace) -> int:
    payload = _app_from_args(args).task_details(args.task_id)
    if args.json:
        _print_json(payload)
    else:
        _print_task_details(payload)
    return 0


def command_confirm(args: argparse.Namespace) -> int:
    task = asyncio.run(
        _app_from_args(args).confirm(
            args.task_id,
            headless=True if args.non_interactive else args.headless,
        )
    )
    _emit_task(task, as_json=args.json)
    return 0


def command_reject(args: argparse.Namespace) -> int:
    task = _app_from_args(args).reject(args.task_id, reason=args.reason)
    _emit_task(task, as_json=args.json)
    return 0


def command_cancel(args: argparse.Namespace) -> int:
    task = _app_from_args(args).cancel(args.task_id)
    _emit_task(task, as_json=args.json)
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    app = _app_from_args(args)
    app.config.validate()
    checks = app.diagnostics()
    if args.json:
        _print_json(checks)
    else:
        for name, value in checks.items():
            print(f"{name:30} {value}")
    return CliExitCode.OK if app.diagnostics_ok() else CliExitCode.CONFIG


def _task_exit_code(task: Task) -> CliExitCode:
    if task.status == TaskStatus.TIMED_OUT:
        return CliExitCode.TEMPORARY_FAILURE
    if task.status == TaskStatus.WAITING_LOGIN:
        return CliExitCode.AUTH_REQUIRED
    if task.status == TaskStatus.FAILED:
        return CliExitCode.SOFTWARE
    return CliExitCode.OK


def _fetch_queue_exit_code(result: FetchQueueResult) -> CliExitCode:
    if result.completed:
        return CliExitCode.OK
    error_type = result.error["type"] if result.error else ""
    if error_type in {"LoginRequired", TaskStatus.WAITING_LOGIN.value}:
        return CliExitCode.AUTH_REQUIRED
    if error_type in {"PollTimedOut", TaskStatus.TIMED_OUT.value}:
        return CliExitCode.TEMPORARY_FAILURE
    if error_type == "PageStructureChanged":
        return CliExitCode.UNAVAILABLE
    return CliExitCode.SOFTWARE


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.json = bool(args.json or args.format == "json")
    try:
        if args.command in (None, "tui"):
            if args.json or args.non_interactive:
                raise CliUsageError("JSON/非交互模式必须指定具体子命令")
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                parser.print_help(file=sys.stderr)
                return CliExitCode.USAGE
            from .tui import run_tui

            return run_tui(config_path=args.config)

        command_handlers = {
            "init": command_init,
            "list": command_list,
            "show": command_show,
            "confirm": command_confirm,
            "reject": command_reject,
            "cancel": command_cancel,
            "doctor": command_doctor,
        }
        if handler := command_handlers.get(args.command):
            return handler(args)

        app = _app_from_args(args)
        if args.command == "login":
            if args.non_interactive:
                raise CliUsageError(
                    "登录需要安全输入密码或处理验证码，不能在非交互模式执行"
                )
            if args.manual_browser:
                asyncio.run(app.login(headless=False))
            else:
                email = args.email or _prompt_email()
                password = getpass.getpass("科研通密码（输入不回显）：")
                asyncio.run(
                    app.login(
                        email=email,
                        password=password,
                        headless=True,
                    )
                )
            if args.json:
                _print_json({"ok": True})
            return 0
        if args.command == "points":
            points = asyncio.run(
                app.account_points(
                    headless=True if args.non_interactive else args.headless,
                )
            )
            if args.json:
                _print_json(points.to_dict())
            else:
                print(f"当前科研通积分：{points.total}")
                print(f"获取时间：{points.retrieved_at}")
            return 0
        if args.command in {"check-in", "recharge"}:
            if args.non_interactive:
                raise CliUsageError(
                    "签到和充值必须由用户在科研通页面中手动完成，"
                    "不能在非交互模式执行"
                )
            points = asyncio.run(
                app.check_in()
                if args.command == "check-in"
                else app.recharge_points()
            )
            if args.json:
                _print_json(points.to_dict())
            else:
                print(f"当前科研通积分：{points.total}")
                print(f"获取时间：{points.retrieved_at}")
            return 0
        if args.command == "fetch":
            if args.non_interactive and args.manual_publish:
                raise CliUsageError("非交互模式不能使用 --manual-publish")
            headless = (
                True
                if args.non_interactive and args.headless is None
                else args.headless
            )
            task = asyncio.run(
                app.fetch(
                    args.query,
                    auto_publish=False if args.manual_publish else None,
                    download_dir=args.download_dir,
                    headless=headless,
                    allow_repeat=args.allow_repeat_after_checking_site,
                )
            )
            _emit_task(task, as_json=args.json)
            return _task_exit_code(task)
        if args.command == "fetch-many":
            headless = (
                True
                if args.non_interactive and args.headless is None
                else args.headless
            )
            result = asyncio.run(
                app.fetch_many(
                    args.queries,
                    download_dir=args.download_dir,
                    headless=headless,
                    allow_repeat=args.allow_repeat_after_checking_site,
                )
            )
            _emit_fetch_queue(result, as_json=args.json)
            return _fetch_queue_exit_code(result)
        if args.command == "recover":
            task = asyncio.run(
                app.recover(
                    args.task_id,
                    download_dir=args.download_dir,
                    headless=True if args.non_interactive else args.headless,
                )
            )
            _emit_task(task, as_json=args.json)
            return _task_exit_code(task)
        if args.command == "accept-all":
            result = asyncio.run(
                app.accept_all(
                    headless=True if args.non_interactive else args.headless
                )
            )
            if args.json:
                _print_json(result.to_dict())
            else:
                print(
                    f"批量采纳完成：网站处理 {result.website_count} 条，"
                    f"本地同步 {result.local_count} 条。"
                )
            return 0
    except KeyboardInterrupt:
        if args.json:
            _print_json(
                error_document(
                    KeyboardInterrupt("interrupted by user"),
                    command=args.command,
                    exit_code=CliExitCode.INTERRUPTED,
                )
            )
        else:
            print("\n已由用户中止。浏览器已关闭；任务记录仍保留。", file=sys.stderr)
        return CliExitCode.INTERRUPTED
    except Exception as exc:
        exit_code = exit_code_for_exception(exc)
        if args.json:
            _print_json(
                error_document(
                    exc,
                    command=args.command,
                    exit_code=exit_code,
                )
            )
        else:
            print(f"错误：{exc}", file=sys.stderr)
        return exit_code
    return CliExitCode.OK


if __name__ == "__main__":
    raise SystemExit(main())
