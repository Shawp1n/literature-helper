import json

from literature_helper import AccountPoints, ConfigError, FetchQueueResult
from literature_helper.cli import (
    CliExitCode,
    _print_task_summary,
    build_parser,
    exit_code_for_exception,
    main,
)
from literature_helper.models import LiteratureMetadata, TaskStatus
from literature_helper.storage import TaskStore


def test_task_summary_hides_verbose_validation_json(tmp_path, capsys):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("10.1000/example")
    task = store.update(
        task.id,
        TaskStatus.DOWNLOADED_PENDING_REVIEW,
        download_path=tmp_path / "paper.pdf",
        literature=LiteratureMetadata(
            title="A structured paper title",
            doi="10.1000/example",
            journal="Journal of Examples",
        ),
        validation={"ok": True, "sha256": "abc", "page_count": 16},
    )

    _print_task_summary(task)

    output = capsys.readouterr().out
    assert f"任务结果：{task.id}" in output
    assert "等待下次 fetch 自动采纳" in output
    assert str(tmp_path / "paper.pdf") in output
    assert "A structured paper title" in output
    assert "Journal of Examples" in output
    assert "sha256" not in output
    assert f"lithelper show {task.id}" in output


def test_parser_supports_json_headless_fetch():
    args = build_parser().parse_args(
        [
            "--json",
            "fetch",
            "10.1000/example",
            "--headless",
        ]
    )

    assert args.json is True
    assert args.headless is True
    assert args.query == "10.1000/example"


def test_parser_supports_multiple_ordered_queries():
    args = build_parser().parse_args(
        [
            "fetch-many",
            "10.1000/one",
            "A precise title",
            "--headless",
        ]
    )

    assert args.queries == ["10.1000/one", "A precise title"]
    assert args.headless is True


def test_fetch_many_emits_structured_result(monkeypatch, capsys):
    class App:
        async def fetch_many(self, queries, **options):
            assert queries == ["10.1000/one", "10.1000/two"]
            assert options["headless"] is True
            return FetchQueueResult(
                queries=queries,
                stopped_query=queries[0],
                error={"type": "PollTimedOut", "message": "timeout"},
            )

    monkeypatch.setattr("literature_helper.cli._app_from_args", lambda _args: App())

    exit_code = main(
        [
            "fetch-many",
            "10.1000/one",
            "10.1000/two",
            "--json",
            "--non-interactive",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == CliExitCode.TEMPORARY_FAILURE
    assert payload["completed"] is False
    assert payload["stopped_query"] == "10.1000/one"


def test_parser_supports_agent_headless_recovery():
    args = build_parser().parse_args(
        [
            "--json",
            "--non-interactive",
            "recover",
            "task123",
        ]
    )

    assert args.non_interactive is True
    assert args.task_id == "task123"
    assert args.headless is None


def test_contract_format_flags_work_before_or_after_subcommand():
    parser = build_parser()

    before = parser.parse_args(["--format", "json", "list"])
    after = parser.parse_args(["list", "--format", "json"])
    short = parser.parse_args(["list", "-f", "json"])

    assert before.format == "json"
    assert after.format == "json"
    assert short.format == "json"


def test_terminal_login_is_default_and_browser_is_explicit():
    parser = build_parser()

    terminal = parser.parse_args(["login"])
    browser = parser.parse_args(["login", "--manual-browser"])

    assert terminal.manual_browser is False
    assert browser.manual_browser is True


def test_points_supports_json_non_interactive_output(monkeypatch, capsys):
    class App:
        async def account_points(self, *, headless):
            assert headless is True
            return AccountPoints(
                total=42,
                retrieved_at="2026-07-25T12:00:00+00:00",
            )

    monkeypatch.setattr("literature_helper.cli._app_from_args", lambda _args: App())

    exit_code = main(["points", "--json", "--non-interactive"])

    assert exit_code == CliExitCode.OK
    assert json.loads(capsys.readouterr().out) == {
        "total": 42,
        "retrieved_at": "2026-07-25T12:00:00+00:00",
    }


def test_check_in_rejects_non_interactive_mode(monkeypatch, capsys):
    monkeypatch.setattr(
        "literature_helper.cli._app_from_args",
        lambda _args: object(),
    )

    exit_code = main(["check-in", "--json", "--non-interactive"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == CliExitCode.USAGE
    assert payload["error"]["type"] == "CliUsageError"
    assert "手动完成" in payload["error"]["message"]


def test_no_subcommand_is_reserved_for_tui():
    args = build_parser().parse_args([])

    assert args.command is None


def test_json_mode_without_subcommand_fails_without_waiting(capsys):
    exit_code = main(["--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == CliExitCode.USAGE
    assert payload["ok"] is False
    assert payload["error"]["type"] == "CliUsageError"
    assert "必须指定具体子命令" in payload["error"]["message"]
    assert payload["meta"] == {
        "command": None,
        "exit_code": CliExitCode.USAGE,
    }


def test_public_failure_categories_have_stable_exit_codes():
    assert exit_code_for_exception(KeyError("missing")) == CliExitCode.NO_INPUT
    assert exit_code_for_exception(ConfigError("invalid")) == CliExitCode.CONFIG
    assert exit_code_for_exception(TimeoutError()) == CliExitCode.TEMPORARY_FAILURE
