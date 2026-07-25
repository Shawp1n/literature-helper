from literature_helper.cli import _print_task_summary, build_parser, main
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


def test_terminal_login_is_default_and_browser_is_explicit():
    parser = build_parser()

    terminal = parser.parse_args(["login"])
    browser = parser.parse_args(["login", "--manual-browser"])

    assert terminal.manual_browser is False
    assert browser.manual_browser is True


def test_no_subcommand_is_reserved_for_tui():
    args = build_parser().parse_args([])

    assert args.command is None


def test_json_mode_without_subcommand_fails_without_waiting(capsys):
    exit_code = main(["--json"])

    payload = capsys.readouterr().out
    assert exit_code == 2
    assert '"ok": false' in payload
    assert "必须指定具体子命令" in payload
