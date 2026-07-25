from types import SimpleNamespace

import questionary
from prompt_toolkit.keys import Keys

from literature_helper.api import LiteratureHelper
from literature_helper.config import AppConfig
from literature_helper.models import LiteratureMetadata, TaskStatus
from literature_helper.storage import TaskStore
from literature_helper.tui import (
    LOGO,
    LiteratureHelperTUI,
    TUI_STYLE,
    _add_question_spacing,
    _build_header_box,
    _build_header_fragments,
    _configure_bounded_navigation,
    _configure_escape_value,
    _display_width,
    _positive_number,
)


class _Answer:
    def __init__(self, value):
        self.value = value

    def ask(self):
        return self.value


def test_logo_uses_compact_three_line_box_style():
    assert LOGO == (
        "┃  ┛━┏┛┃ ┃┏━┛┃  ┏━┃┏━┛┏━┃\n"
        "┃  ┃ ┃ ┏━┃┏━┛┃  ┏━┛┏━┛┏┏┛\n"
        "━━┛┛ ┛ ┛ ┛━━┛━━┛┛  ━━┛┛ ┛"
    )

    lines = LOGO.splitlines()
    assert len(lines) == 3
    assert all(any(character in line for character in "┃━┏┓┗┛") for line in lines)


def test_tui_can_exit_from_main_menu(tmp_path, monkeypatch):
    config = AppConfig.defaults(tmp_path / "app")
    config.write()
    messages = []
    monkeypatch.setattr(
        "literature_helper.tui.questionary.select",
        lambda *_args, **_kwargs: _Answer("exit"),
    )

    exit_code = LiteratureHelperTUI(
        config_path=config.data_dir / "config.json",
        output=messages.append,
    ).run()

    assert exit_code == 0
    assert messages[0] == ""
    assert messages[1].startswith("┌")
    assert all(
        any(line in message for message in messages)
        for line in LOGO.splitlines()
    )
    assert any("LITERATURE HELPER" in message for message in messages)


def test_header_box_contains_all_information_and_stays_aligned():
    box = _build_header_box(
        width=80,
        logo=LOGO,
        mode="HEADLESS",
        download_dir="~/Downloads/科研通",
        version="0.7.1",
    )

    assert all(_display_width(line) == 80 for line in box)
    assert any("MODE       │  HEADLESS" in line for line in box)
    assert any("DOWNLOADS  │  ~/Downloads/科研通" in line for line in box)
    assert "─ LITERATURE HELPER · v0.7.1 ─" in box[-1]


def test_header_box_uses_distinct_logo_info_and_divider_colors():
    lines = _build_header_fragments(
        width=80,
        logo=LOGO,
        mode="HEADLESS",
        download_dir="~/Downloads/科研通",
        version="0.7.1",
    )
    fragments = [fragment for line in lines for fragment in line]

    assert any(
        style == "fg:#ffd75f bold" and LOGO.splitlines()[0] in text
        for style, text in fragments
    )
    assert any(
        style == "fg:#8a8a8a" and "MODE" in text
        for style, text in fragments
    )
    assert any(
        style == "fg:#8a8a8a" and "HEADLESS" in text
        for style, text in fragments
    )
    assert sum(
        style == "fg:#8a8a8a" and text == "│"
        for style, text in fragments
    ) == 2
    assert any(
        style == "fg:#ffffff" and text.startswith("┌")
        for style, text in fragments
    )
    assert any(
        style == "fg:#ffffff" and "LITERATURE HELPER · v0.7.1" in text
        for style, text in fragments
    )


def test_header_box_truncates_wide_paths_without_breaking_border():
    box = _build_header_box(
        width=40,
        logo=LOGO,
        mode="VISIBLE BROWSER",
        download_dir="~/下载目录/科研论文/特别长的文件夹名称",
        version="0.7.1",
    )

    assert all(_display_width(line) == 40 for line in box)
    assert any("…" in line for line in box)
    assert all(line.endswith(("┐", "│", "┘")) for line in box)


def test_clear_screen_erases_visible_and_scrollback_buffers(
    monkeypatch,
):
    calls = []
    stdout = SimpleNamespace(
        isatty=lambda: True,
        write=lambda value: calls.append(("write", value)),
        flush=lambda: calls.append(("flush",)),
    )
    monkeypatch.setattr("literature_helper.tui.sys.stdout", stdout)
    monkeypatch.setenv("TERM", "xterm-256color")
    tui = LiteratureHelperTUI()

    tui._clear_screen()

    assert calls == [
        ("write", "\033[H\033[2J\033[3J"),
        ("flush",),
    ]


def test_clear_screen_does_not_write_to_custom_output(
    monkeypatch,
):
    calls = []
    stdout = SimpleNamespace(
        isatty=lambda: True,
        write=lambda value: calls.append(("write", value)),
        flush=lambda: calls.append(("flush",)),
    )
    monkeypatch.setattr("literature_helper.tui.sys.stdout", stdout)
    monkeypatch.setenv("TERM", "xterm-256color")

    LiteratureHelperTUI(output=calls.append)._clear_screen()

    assert calls == []


def test_main_menu_only_exposes_five_primary_actions(tmp_path, monkeypatch):
    config = AppConfig.defaults(tmp_path / "app")
    config.write()
    captured = {}

    def choose(message, *, choices, **_kwargs):
        captured["message"] = message
        captured["choices"] = choices
        return _Answer("exit")

    monkeypatch.setattr("literature_helper.tui.questionary.select", choose)

    LiteratureHelperTUI(
        config_path=config.data_dir / "config.json",
        output=lambda _message: None,
    ).run()

    assert captured["message"] == "主菜单"
    assert [choice.title for choice in captured["choices"]] == [
        "账号管理",
        "下载文献",
        "历史记录",
        "设置",
        "退出",
    ]
    assert [choice.value for choice in captured["choices"]] == [
        "account",
        "fetch",
        "history",
        "settings",
        "exit",
    ]


def test_account_management_contains_login_points_and_return(monkeypatch):
    captured = {}
    tui = LiteratureHelperTUI(output=lambda _message: None)

    def choose(message, *, choices, **_kwargs):
        captured["message"] = message
        captured["choices"] = choices
        return "__back__"

    monkeypatch.setattr(tui, "_redraw", lambda: None)
    monkeypatch.setattr(tui, "_select", choose)

    tui._account_management()

    assert captured["message"] == "账号管理"
    assert [choice.title for choice in captured["choices"]] == [
        "登录账号",
        "积分管理",
        "返回",
    ]
    assert [choice.value for choice in captured["choices"]] == [
        "login",
        "points",
        "__back__",
    ]


def test_points_management_contains_three_actions_and_return(monkeypatch):
    captured = {}
    tui = LiteratureHelperTUI(output=lambda _message: None)

    def choose(message, *, choices, **_kwargs):
        captured["message"] = message
        captured["choices"] = choices
        return "__back__"

    monkeypatch.setattr(tui, "_redraw", lambda: None)
    monkeypatch.setattr(tui, "_select", choose)

    tui._points_management()

    assert captured["message"] == "积分管理"
    assert [choice.title for choice in captured["choices"]] == [
        "积分刷新",
        "积分签到",
        "积分充值",
        "返回",
    ]
    assert [choice.value for choice in captured["choices"]] == [
        "refresh",
        "check_in",
        "recharge",
        "__back__",
    ]


def test_download_menu_has_an_explicit_return_option(monkeypatch):
    captured = {}
    tui = LiteratureHelperTUI(output=lambda _message: None)

    def choose(message, *, choices, **_kwargs):
        captured["message"] = message
        captured["choices"] = choices
        return "__back__"

    monkeypatch.setattr(tui, "_redraw", lambda: None)
    monkeypatch.setattr(tui, "_select", choose)
    monkeypatch.setattr(
        "literature_helper.tui.questionary.text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("选择返回后不应进入 DOI 输入")
        ),
    )

    tui._fetch()

    assert captured["message"] == "下载文献"
    assert [choice.title for choice in captured["choices"]] == [
        "下载单篇文献",
        "顺序下载多篇",
        "返回",
    ]
    assert [choice.value for choice in captured["choices"]] == [
        "single",
        "many",
        "__back__",
    ]


def test_cancelling_doi_input_returns_to_download_menu(monkeypatch):
    actions = iter(["single", "__back__"])
    redraws = []
    tui = LiteratureHelperTUI(output=lambda _message: None)

    monkeypatch.setattr(tui, "_redraw", lambda: redraws.append("redraw"))
    monkeypatch.setattr(tui, "_select", lambda *_args, **_kwargs: next(actions))
    monkeypatch.setattr(
        "literature_helper.tui.questionary.text",
        lambda *_args, **_kwargs: _Answer("__back__"),
    )

    tui._fetch()

    assert redraws == ["redraw", "redraw", "redraw"]


def test_multiple_query_input_uses_one_item_per_line(monkeypatch):
    answers = iter(
        [
            _Answer(" 10.1000/one "),
            _Answer("A   precise title"),
            _Answer(""),
        ]
    )
    messages = []
    tui = LiteratureHelperTUI(output=messages.append)
    monkeypatch.setattr(tui, "_redraw", lambda: None)
    monkeypatch.setattr(
        "literature_helper.tui.questionary.text",
        lambda *_args, **_kwargs: next(answers),
    )

    queries = tui._collect_fetch_queries()

    assert queries == ["10.1000/one", "A precise title"]
    assert any("不会并发发布" in message for message in messages)


def test_returning_from_submenu_does_not_require_extra_enter(
    tmp_path,
    monkeypatch,
):
    config = AppConfig.defaults(tmp_path / "app")
    config.write()
    answers = iter(["history", "__back__", "exit"])

    monkeypatch.setattr(
        "literature_helper.tui.questionary.select",
        lambda *_args, **_kwargs: _Answer(next(answers)),
    )
    monkeypatch.setattr(
        "literature_helper.tui.questionary.text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("返回上一级不应要求再次按 Enter")
        ),
    )

    exit_code = LiteratureHelperTUI(
        config_path=config.data_dir / "config.json",
        output=lambda _message: None,
    ).run()

    assert exit_code == 0


def test_history_groups_advanced_actions_in_submenu(tmp_path, monkeypatch):
    config = AppConfig.defaults(tmp_path / "app")
    config.write()
    captured = {}

    def choose(message, *, choices, **_kwargs):
        captured["message"] = message
        captured["choices"] = choices
        return _Answer("__back__")

    monkeypatch.setattr("literature_helper.tui.questionary.select", choose)

    LiteratureHelperTUI(
        config_path=config.data_dir / "config.json",
        output=lambda _message: None,
    )._history()

    assert captured["message"] == "历史记录"
    assert [choice.title for choice in captured["choices"]] == [
        "查看任务与下载记录",
        "恢复未完成求助",
        "处理历史待确认",
        "返回",
    ]


def test_history_choices_are_numbered_titles_with_safe_fallback(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    titled = store.create("10.1000/titled")
    titled = store.update(
        titled.id,
        TaskStatus.READY_TO_PUBLISH,
        literature=LiteratureMetadata(title="Recognized paper title"),
    )
    missing_title = store.create("Original title input")
    missing_title = store.update(
        missing_title.id,
        TaskStatus.READY_TO_PUBLISH,
        literature=LiteratureMetadata(title=None, doi="10.1000/fallback"),
    )

    assert LiteratureHelperTUI._history_task_choice(1, titled) == (
        " 1. Recognized paper title"
    )
    assert LiteratureHelperTUI._history_task_choice(2, missing_title) == (
        " 2. 10.1000/fallback"
    )
    assert "10.1000/fallback" in LiteratureHelperTUI._task_choice(missing_title)


def test_task_details_show_all_recognized_literature_fields(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("10.1000/example")
    task = store.update(
        task.id,
        TaskStatus.DOWNLOADED_PENDING_REVIEW,
        request_url="https://www.ablesci.com/assist/detail?id=example",
        download_path=tmp_path / "paper.pdf",
        validation={"ok": True, "page_count": 12, "size_bytes": 2048},
        literature=LiteratureMetadata(
            title="Complete paper title",
            doi="10.1000/example",
            url="https://doi.org/10.1000/example",
            journal="Journal of Examples",
            authors=["Ada Lovelace", "Alan Turing"],
            publication_date="2024-10-01",
            source="ablesci_intelligent_extract",
            extracted_at="2026-07-25T12:00:00+00:00",
        ),
    )
    messages = []

    LiteratureHelperTUI(output=messages.append)._show_task(task)

    output = "\n".join(messages)
    assert "智能识别文献信息" in output
    assert "标题：Complete paper title" in output
    assert "DOI：10.1000/example" in output
    assert "文献链接：https://doi.org/10.1000/example" in output
    assert "期刊：Journal of Examples" in output
    assert "作者：Ada Lovelace; Alan Turing" in output
    assert "出版日期：2024-10-01" in output
    assert "出版年份：2024" in output
    assert "数据来源：ablesci_intelligent_extract" in output
    assert "识别时间：2026-07-25T12:00:00+00:00" in output
    assert "下载文件：" in output


def test_task_details_show_missing_fields_without_crashing(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("Original title")
    task = store.update(
        task.id,
        TaskStatus.READY_TO_PUBLISH,
        literature=LiteratureMetadata(title=None),
    )
    messages = []

    LiteratureHelperTUI(output=messages.append)._show_task(task)

    output = "\n".join(messages)
    assert "标题：未识别" in output
    assert "DOI：未识别" in output
    assert "原始输入：Original title" in output


def test_task_actions_have_spacing_and_delete_record_choice(tmp_path, monkeypatch):
    task = TaskStore(tmp_path / "tasks.sqlite3").create("10.1000/example")
    messages = []
    captured = {}
    tui = LiteratureHelperTUI(output=messages.append)

    def choose(message, *, choices, **_kwargs):
        captured["message"] = message
        captured["choices"] = choices
        return "__back__"

    monkeypatch.setattr(tui, "_select", choose)

    tui._task_actions(object(), task)

    assert messages == [""]
    assert captured["message"] == "任务操作"
    assert [choice.title for choice in captured["choices"]][-2:] == [
        "删除该历史记录",
        "返回历史记录",
    ]


def test_task_action_deletes_record_but_keeps_pdf(tmp_path, monkeypatch):
    config = AppConfig.defaults(tmp_path / "app")
    app = LiteratureHelper(config=config)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    task = app.store.create("10.1000/example")
    task = app.store.update(
        task.id,
        TaskStatus.DOWNLOADED_PENDING_REVIEW,
        download_path=pdf,
    )
    messages = []
    pauses = []
    tui = LiteratureHelperTUI(output=messages.append)

    monkeypatch.setattr(tui, "_select", lambda *_args, **_kwargs: "delete")
    monkeypatch.setattr(tui, "_redraw", lambda: None)
    monkeypatch.setattr(
        "literature_helper.tui.questionary.confirm",
        lambda *_args, **_kwargs: _Answer(True),
    )
    monkeypatch.setattr(tui, "_pause", pauses.append)

    tui._task_actions(app, task)

    assert app.list_tasks() == []
    assert pdf.exists()
    assert "已删除历史记录：10.1000/example" in messages
    assert f"PDF 文件仍保留在：{pdf}" in messages
    assert pauses == ["按 Enter 返回历史记录"]


def test_history_redraws_after_returning_from_completed_action(
    tmp_path,
    monkeypatch,
):
    config = AppConfig.defaults(tmp_path / "app")
    path = config.write()
    tui = LiteratureHelperTUI(config_path=path, output=lambda _message: None)
    actions = iter(["accept_all", "__back__"])
    redraws = []

    monkeypatch.setattr(tui, "_select", lambda *_args, **_kwargs: next(actions))
    monkeypatch.setattr(tui, "_accept_all", lambda: None)
    monkeypatch.setattr(tui, "_pause", lambda *_args: None)
    monkeypatch.setattr(tui, "_clear_screen", lambda: redraws.append("clear"))
    monkeypatch.setattr(tui, "_show_header", lambda: redraws.append("header"))

    tui._history()

    assert redraws == ["clear", "header", "clear", "header"]


def test_settings_redraws_instead_of_accumulating_old_answers(
    tmp_path,
    monkeypatch,
):
    config = AppConfig.defaults(tmp_path / "app")
    config.headless = False
    path = config.write()
    tui = LiteratureHelperTUI(config_path=path, output=lambda _message: None)
    actions = iter(["headless", "__back__"])
    redraws = []

    monkeypatch.setattr(tui, "_select", lambda *_args, **_kwargs: next(actions))
    monkeypatch.setattr(tui, "_clear_screen", lambda: redraws.append("clear"))
    monkeypatch.setattr(tui, "_show_header", lambda: redraws.append("header"))
    monkeypatch.setattr(
        "literature_helper.tui.questionary.confirm",
        lambda *_args, **_kwargs: _Answer(True),
    )

    tui._settings()

    assert redraws == ["clear", "header", "clear", "header"]
    assert AppConfig.load(path).headless is True


def test_all_return_prompts_have_a_blank_line_above(monkeypatch):
    messages = []
    captured = {}

    def text(message, **options):
        captured["message"] = message
        captured["options"] = options
        return _Answer("")

    monkeypatch.setattr("literature_helper.tui.questionary.text", text)
    tui = LiteratureHelperTUI(output=messages.append)

    tui._pause("按 Enter 返回设置")

    assert messages == [""]
    assert captured == {
        "message": "按 Enter 返回设置",
        "options": {
            "default": "",
            "style": TUI_STYLE,
        },
    }


def test_menu_navigation_stops_at_first_and_last_choice():
    prompt = questionary.select(
        "测试菜单",
        choices=["第一项", "第二项", "第三项"],
    )

    control = _configure_bounded_navigation(prompt)

    assert control is not None
    control.pointed_at = 0
    control.select_previous()
    assert control.pointed_at == 0
    control.pointed_at = 2
    control.select_next()
    assert control.pointed_at == 2


def test_escape_binding_returns_to_parent_value():
    prompt = questionary.select("二级菜单", choices=["第一项", "返回"])

    assert _configure_escape_value(prompt, "__back__") is True

    bindings = [
        binding
        for binding in prompt.application.key_bindings.bindings
        if binding.keys == (Keys.Escape,)
    ]
    results = []
    event = SimpleNamespace(
        app=SimpleNamespace(
            exit=lambda *, result: results.append(result),
        )
    )
    bindings[-1].handler(event)

    assert results == ["__back__"]


def test_blank_line_can_be_inserted_after_main_menu_prompt():
    prompt = questionary.select("主菜单", choices=["下载文献", "退出"])
    container = prompt.application.layout.container
    original_children = list(container.children)

    assert _add_question_spacing(prompt) is True

    assert len(container.children) == len(original_children) + 1
    assert container.children[0] is original_children[0]
    assert container.children[2] is original_children[1]


def test_all_select_menus_add_prompt_spacing_by_default(monkeypatch):
    prompt = _Answer("__back__")
    spaced = []
    monkeypatch.setattr(
        "literature_helper.tui.questionary.select",
        lambda *_args, **_kwargs: prompt,
    )
    monkeypatch.setattr(
        "literature_helper.tui._add_question_spacing",
        lambda question: spaced.append(question),
    )

    result = LiteratureHelperTUI(output=lambda _message: None)._select(
        "二级菜单",
        choices=[],
    )

    assert result == "__back__"
    assert spaced == [prompt]


def test_positive_number_validator():
    assert _positive_number("30") is True
    assert isinstance(_positive_number("0"), str)
    assert isinstance(_positive_number("not-a-number"), str)
