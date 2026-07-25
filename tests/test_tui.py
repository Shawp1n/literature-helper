from literature_helper.config import AppConfig
from literature_helper.tui import LOGO, LiteratureHelperTUI, _positive_number


class _Answer:
    def __init__(self, value):
        self.value = value

    def ask(self):
        return self.value


def test_logo_uses_compact_three_line_box_style():
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
    assert LOGO in messages
    assert any("Literature Helper" in message for message in messages)


def test_positive_number_validator():
    assert _positive_number("30") is True
    assert isinstance(_positive_number("0"), str)
    assert isinstance(_positive_number("not-a-number"), str)
