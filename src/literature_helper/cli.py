from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from pathlib import Path

from . import __version__
from .api import LiteratureHelper
from .config import AppConfig
from .diagnostics import collect_diagnostics, diagnostics_ok
from .models import Task, TaskStatus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lithelper",
        description="Literature Helper：面向人类与 Agent 的个人文献获取工具",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--config",
        type=Path,
        help="配置文件路径（默认位于用户数据目录）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="标准输出仅返回 JSON；过程日志写入标准错误",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="禁止等待人工输入；适用于 Agent、CI 和调度器",
    )
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("tui", help="打开方向键交互界面")

    init = commands.add_parser("init", help="创建默认配置和数据目录")
    init.add_argument("--force", action="store_true", help="覆盖已有配置")

    login = commands.add_parser("login", help="登录科研通并保存本地会话")
    login.add_argument(
        "--email",
        help="科研通邮箱；省略时在终端提示输入",
    )
    login.add_argument(
        "--manual-browser",
        action="store_true",
        help="打开浏览器手动登录，用于处理验证码等情况",
    )

    fetch = commands.add_parser("fetch", help="发布单篇求助并等待 PDF")
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

    recover = commands.add_parser(
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

    accept_all = commands.add_parser(
        "accept-all",
        help="批量采纳网站上全部历史待确认求助",
    )
    accept_all.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="无头批量采纳",
    )

    listing = commands.add_parser("list", help="列出最近任务")
    listing.add_argument("--limit", type=int, default=20)

    show = commands.add_parser("show", help="显示任务详情和事件")
    show.add_argument("task_id")

    confirm = commands.add_parser(
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

    reject = commands.add_parser("reject", help="标记下载的文件有误（不会操作网站）")
    reject.add_argument("task_id")
    reject.add_argument("--reason", required=True, help="本地记录原因")

    cancel = commands.add_parser("cancel", help="解除中断后遗留的本地活动任务")
    cancel.add_argument("task_id")

    commands.add_parser("doctor", help="检查本地配置和 Python 依赖")
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
        config=_config_from_args(args),
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


def _prompt_email() -> str:
    print("科研通邮箱：", end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip()


def _emit_task(task: Task, *, as_json: bool) -> None:
    if as_json:
        _print_json(task.to_dict())
    else:
        _print_task_summary(task)


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
    _print_json(_app_from_args(args).task_details(args.task_id))
    return 0


def command_confirm(args: argparse.Namespace) -> int:
    task = asyncio.run(
        _app_from_args(args).confirm(
            args.task_id,
            headless=True if args.non_interactive else bool(args.headless),
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
    config = _config_from_args(args)
    config.validate()
    checks = collect_diagnostics(config, config_path=args.config)
    _print_json(checks)
    return 0 if diagnostics_ok(checks) else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in (None, "tui"):
            if args.json or args.non_interactive:
                raise RuntimeError("JSON/非交互模式必须指定具体子命令")
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                parser.print_help(file=sys.stderr)
                return 2
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
                raise RuntimeError(
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
        if args.command == "fetch":
            if args.non_interactive and args.manual_publish:
                raise RuntimeError("非交互模式不能使用 --manual-publish")
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
            return 0 if task.status != TaskStatus.FAILED else 1
        if args.command == "recover":
            task = asyncio.run(
                app.recover(
                    args.task_id,
                    download_dir=args.download_dir,
                    headless=(
                        True if args.non_interactive else bool(args.headless)
                    ),
                )
            )
            _emit_task(task, as_json=args.json)
            return 0 if task.status != TaskStatus.FAILED else 1
        if args.command == "accept-all":
            result = asyncio.run(
                app.accept_all(
                    headless=(
                        True if args.non_interactive else bool(args.headless)
                    )
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
            _print_json({"ok": False, "error": {"type": "KeyboardInterrupt"}})
        else:
            print("\n已由用户中止。浏览器已关闭；任务记录仍保留。", file=sys.stderr)
        return 130
    except Exception as exc:
        if args.json:
            _print_json(
                {
                    "ok": False,
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                }
            )
        else:
            print(f"错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
