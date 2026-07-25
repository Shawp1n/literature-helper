from unittest.mock import AsyncMock

import pytest

from literature_helper.adapter import (
    AbleSciAdapter,
    PageStructureChanged,
    PendingReviewRequired,
    SiteSelectors,
    _filename_from_disposition,
    _metadata_from_snapshot,
    _safe_filename,
    _unique_path,
)
from literature_helper.models import LiteratureMetadata


def test_filename_from_disposition():
    assert (
        _filename_from_disposition("attachment; filename*=UTF-8''paper%20one.pdf")
        == "paper one.pdf"
    )
    assert _filename_from_disposition('attachment; filename="paper.pdf"') == "paper.pdf"


def test_safe_filename_removes_path_and_unsafe_chars():
    assert _safe_filename("../../bad:name", ".pdf") == "bad_name.pdf"


def test_unique_path(tmp_path):
    original = tmp_path / "paper.pdf"
    original.write_bytes(b"x")
    assert _unique_path(original).name == "paper (1).pdf"


class FakeLocator:
    def __init__(self, on_click=None):
        self.clicks = 0
        self.filled = None
        self.checked = False
        self.on_click = on_click

    async def click(self, *args, **kwargs):
        self.clicks += 1
        if self.on_click:
            self.on_click()

    async def fill(self, value):
        self.filled = value

    async def check(self, *args, **kwargs):
        self.checked = True

    async def is_enabled(self):
        return True


def make_adapter(tmp_path):
    return AbleSciAdapter(
        selectors=SiteSelectors(),
        assist_url="https://www.ablesci.com/assist/create",
        my_assists_url="https://www.ablesci.com/my/assist-my",
        login_url="https://www.ablesci.com/site/login",
        headless=False,
        debug_dir=tmp_path,
        output=lambda _: None,
    )


@pytest.mark.asyncio
async def test_credential_login_fills_form_and_saves_session(
    tmp_path,
    monkeypatch,
):
    adapter = make_adapter(tmp_path)

    class Page:
        url = "about:blank"

        async def goto(self, url, **_kwargs):
            self.url = url

    page = Page()
    email_input = FakeLocator()
    password_input = FakeLocator()
    remember = FakeLocator()
    submit = FakeLocator(
        on_click=lambda: setattr(page, "url", adapter.assist_url)
    )

    async def first_visible(_page, selectors, _timeout):
        if selectors is adapter.selectors.login_email_inputs:
            return email_input
        if selectors is adapter.selectors.login_password_inputs:
            return password_input
        if selectors is adapter.selectors.login_remember_inputs:
            return remember
        if selectors is adapter.selectors.login_submit_buttons:
            return submit
        raise AssertionError("unexpected selector group")

    monkeypatch.setattr(adapter, "_first_visible", first_visible)
    monkeypatch.setattr(adapter, "_settle", AsyncMock())
    monkeypatch.setattr(adapter, "_captcha_visible", AsyncMock(return_value=False))
    monkeypatch.setattr(adapter, "is_login_page", AsyncMock(return_value=False))

    await adapter.credential_login(
        page,
        email="person@example.com",
        password="secret",
    )

    assert email_input.filled == "person@example.com"
    assert password_input.filled == "secret"
    assert remember.checked is True
    assert submit.clicks == 1
    assert page.url == adapter.assist_url


@pytest.mark.asyncio
async def test_prepare_request_extracts_metadata_before_publish(tmp_path, monkeypatch):
    adapter = make_adapter(tmp_path)
    query_input = FakeLocator()
    intelligent_extract = FakeLocator()
    extracted_publish = FakeLocator()

    async def first_visible(_page, selectors, _timeout):
        if selectors is adapter.selectors.query_inputs:
            return query_input
        if selectors is adapter.selectors.intelligent_extract_buttons:
            return intelligent_extract
        if selectors is adapter.selectors.extracted_publish_buttons:
            return extracted_publish
        raise AssertionError("智能提取成功后不应寻找普通发布按钮")

    monkeypatch.setattr(adapter, "_first_visible", first_visible)
    monkeypatch.setattr(adapter, "_settle", AsyncMock())
    monkeypatch.setattr(adapter, "_raise_if_blocked", AsyncMock())
    monkeypatch.setattr(adapter, "_captcha_visible", AsyncMock(return_value=False))
    metadata = LiteratureMetadata(
        title="An example paper",
        doi="10.1000/example",
    )
    monkeypatch.setattr(
        adapter,
        "extract_literature_metadata",
        AsyncMock(return_value=metadata),
    )

    result = await adapter.prepare_request(object(), "10.1000/example")

    assert query_input.filled == "10.1000/example"
    assert intelligent_extract.clicks == 1
    assert result.publish_button is extracted_publish
    assert result.literature is metadata


def test_metadata_snapshot_is_converted_to_structured_literature():
    snapshot = {
        "fields": [
            {
                "value": "A structured paper title",
                "label": "标题",
                "name": "Assist[title]",
            },
            {
                "value": "https://doi.org/10.1000/EXAMPLE",
                "label": "网址",
                "name": "Assist[url]",
            },
            {
                "value": "10.1000/EXAMPLE",
                "label": "DOI",
                "name": "Assist[doi]",
            },
            {
                "value": (
                    "期刊：Journal of Examples\n"
                    "作者：Ada Lovelace; Alan Turing\n"
                    "出版日期：2024-10-01"
                ),
                "label": "其它",
                "name": "Assist[other]",
            },
        ],
        "text": (
            "标题\nA structured paper title\n"
            "网址\nhttps://doi.org/10.1000/EXAMPLE\n"
            "DOI\n10.1000/EXAMPLE\n"
            "其它\n期刊：Journal of Examples\n"
            "作者：Ada Lovelace; Alan Turing\n"
            "出版日期：2024-10-01"
        ),
    }

    literature = _metadata_from_snapshot(snapshot, "10.1000/example")

    assert literature.title == "A structured paper title"
    assert literature.doi == "10.1000/EXAMPLE"
    assert literature.url == "https://doi.org/10.1000/EXAMPLE"
    assert literature.journal == "Journal of Examples"
    assert literature.authors == ["Ada Lovelace", "Alan Turing"]
    assert literature.publication_date == "2024-10-01"
    assert literature.publication_year == 2024


def test_internal_publication_enum_is_not_reported_as_journal():
    literature = _metadata_from_snapshot(
        {
            "fields": [
                {
                    "value": "1",
                    "name": "publication_type",
                    "label": "Publication",
                }
            ],
            "text": "DOI\n10.1000/example",
        },
        "10.1000/example",
    )

    assert literature.journal is None


@pytest.mark.asyncio
async def test_publish_success_opens_request_detail(tmp_path, monkeypatch):
    adapter = make_adapter(tmp_path)

    class FakePage:
        url = "https://www.ablesci.com/assist/create"

    page = FakePage()
    publish = FakeLocator()
    detail = FakeLocator(
        on_click=lambda: setattr(
            page,
            "url",
            "https://www.ablesci.com/assist/detail?id=example",
        )
    )

    async def first_visible(_page, selectors, _timeout):
        if selectors is adapter.selectors.post_publish_detail_buttons:
            return detail
        raise AssertionError("发布成功后应优先点击查看求助详情")

    monkeypatch.setattr(adapter, "_first_visible", first_visible)
    monkeypatch.setattr(adapter, "_settle", AsyncMock())
    monkeypatch.setattr(adapter, "_raise_if_blocked", AsyncMock())
    monkeypatch.setattr(adapter, "_captcha_visible", AsyncMock(return_value=False))

    outcome = await adapter.click_publish_once(page, publish)

    assert publish.clicks == 1
    assert detail.clicks == 1
    assert outcome.verified
    assert "/assist/detail" in outcome.request_url
    assert outcome.page is page


@pytest.mark.asyncio
async def test_upload_notice_is_confirmed(tmp_path, monkeypatch):
    adapter = make_adapter(tmp_path)
    marker = FakeLocator()
    confirm = FakeLocator()

    async def first_visible(_page, selectors, _timeout):
        if selectors is adapter.selectors.upload_notice_markers:
            return marker
        if selectors is adapter.selectors.upload_notice_confirm_buttons:
            return confirm
        raise AssertionError("unexpected selector group")

    monkeypatch.setattr(adapter, "_first_visible", first_visible)
    monkeypatch.setattr(adapter, "_settle", AsyncMock())

    assert await adapter.dismiss_upload_notice(object())
    assert confirm.clicks == 1


@pytest.mark.asyncio
async def test_high_speed_download_channel_is_preferred(tmp_path, monkeypatch):
    adapter = make_adapter(tmp_path)
    high_speed = FakeLocator()

    async def first_visible(_page, selectors, _timeout):
        if selectors is adapter.selectors.high_speed_channels:
            return high_speed
        raise AssertionError("有高速通道时不应选择普通线路")

    monkeypatch.setattr(adapter, "_first_visible", first_visible)

    selected = await adapter._find_download_channel(
        object(),
        prefer_high_speed=True,
    )
    assert selected is high_speed


@pytest.mark.asyncio
async def test_first_visible_skips_hidden_earlier_matches():
    hidden = FakeLocator()
    visible = FakeLocator()

    async def hidden_is_visible():
        return False

    async def visible_is_visible():
        return True

    hidden.is_visible = hidden_is_visible
    visible.is_visible = visible_is_visible

    class Matches:
        async def count(self):
            return 2

        def nth(self, index):
            return [hidden, visible][index]

    class Page:
        def locator(self, selector):
            assert selector == 'button:has-text("高速通道")'
            return Matches()

    selected = await AbleSciAdapter._first_visible(
        Page(),
        ['button:has-text("高速通道")'],
        0,
    )

    assert selected is visible


@pytest.mark.asyncio
async def test_accept_file_requires_explicit_adapter_action(tmp_path, monkeypatch):
    adapter = make_adapter(tmp_path)
    handlers = {}

    class Page:
        def on(self, event, handler):
            handlers[event] = handler

        def remove_listener(self, event, handler):
            if handlers.get(event) is handler:
                handlers.pop(event)

    page = Page()

    class Dialog:
        accepted = False

        async def accept(self):
            self.accepted = True

    dialog = Dialog()
    accept = FakeLocator(on_click=lambda: handlers["dialog"](dialog))
    confirmation = FakeLocator()
    accepted_marker = FakeLocator()
    accepted_checks = 0

    async def first_visible(_page, selectors, _timeout):
        nonlocal accepted_checks
        if selectors is adapter.selectors.upload_notice_markers:
            return None
        if selectors is adapter.selectors.accepted_markers:
            accepted_checks += 1
            return accepted_marker if accepted_checks > 1 else None
        if selectors is adapter.selectors.accept_file_buttons:
            return accept if accept.clicks == 0 else None
        if selectors is adapter.selectors.accept_confirmation_buttons:
            return confirmation
        raise AssertionError("unexpected selector group")

    monkeypatch.setattr(adapter, "_first_visible", first_visible)
    monkeypatch.setattr(adapter, "_settle", AsyncMock())

    await adapter.accept_uploaded_file(page)

    assert accept.clicks == 1
    assert confirmation.clicks == 1
    assert dialog.accepted


@pytest.mark.asyncio
async def test_accept_file_treats_operation_success_popup_as_success(
    tmp_path,
    monkeypatch,
):
    adapter = make_adapter(tmp_path)

    class Page:
        def on(self, *_args):
            pass

        def remove_listener(self, *_args):
            pass

    accept = FakeLocator()
    confirmation = FakeLocator()
    success_marker = FakeLocator()
    success_confirmation = FakeLocator()

    async def first_visible(_page, selectors, _timeout):
        if selectors is adapter.selectors.upload_notice_markers:
            return None
        if selectors is adapter.selectors.accepted_markers:
            return None
        if selectors is adapter.selectors.accept_file_buttons:
            return accept if accept.clicks == 0 else None
        if selectors is adapter.selectors.accept_confirmation_buttons:
            return confirmation
        if selectors is adapter.selectors.acceptance_success_markers:
            return success_marker
        if selectors is adapter.selectors.acceptance_success_buttons:
            return success_confirmation
        raise AssertionError("unexpected selector group")

    monkeypatch.setattr(adapter, "_first_visible", first_visible)
    monkeypatch.setattr(adapter, "_settle", AsyncMock())

    await adapter.accept_uploaded_file(Page())

    assert accept.clicks == 1
    assert confirmation.clicks == 1
    assert success_confirmation.clicks == 1


@pytest.mark.asyncio
async def test_open_assist_recognizes_pending_review_redirect(tmp_path, monkeypatch):
    adapter = make_adapter(tmp_path)

    class RedirectPage:
        url = "about:blank"

        async def goto(self, *_args, **_kwargs):
            self.url = "https://www.ablesci.com/my/assist-my?status=uploaded"

    page = RedirectPage()
    monkeypatch.setattr(adapter, "is_login_page", AsyncMock(return_value=False))

    with pytest.raises(PendingReviewRequired, match="历史待确认"):
        await adapter.open_assist(page)


@pytest.mark.asyncio
async def test_open_pending_request_enters_existing_detail_without_publish(
    tmp_path, monkeypatch
):
    adapter = make_adapter(tmp_path)

    class Link:
        async def is_visible(self):
            return True

        async def get_attribute(self, name):
            return "/assist/detail?id=recovered" if name == "href" else None

        async def click(self):
            page.url = "https://www.ablesci.com/assist/detail?id=recovered"

    class Links:
        async def count(self):
            return 1

        def nth(self, _index):
            return Link()

    class Row:
        async def inner_text(self):
            return "2026-07-25 Existing paper title 待确认"

        def locator(self, selector):
            assert selector == "a"
            return Links()

    class Context:
        pages = []

    class RecoveryPage:
        url = "about:blank"
        context = Context()

        async def goto(self, url, **_kwargs):
            self.url = url

        async def wait_for_load_state(self, *_args, **_kwargs):
            return None

    page = RecoveryPage()
    page.context.pages = [page]
    monkeypatch.setattr(adapter, "is_login_page", AsyncMock(return_value=False))
    monkeypatch.setattr(adapter, "_first_visible", AsyncMock(return_value=None))
    monkeypatch.setattr(adapter, "_visible_items", AsyncMock(return_value=[Row()]))
    monkeypatch.setattr(adapter, "_settle", AsyncMock())

    detail_page, row_text = await adapter.open_pending_request(page)

    assert "/assist/detail?id=recovered" in detail_page.url
    assert "Existing paper title" in row_text


@pytest.mark.asyncio
async def test_prepare_request_never_falls_back_after_extraction_failure(
    tmp_path, monkeypatch
):
    adapter = make_adapter(tmp_path)
    query_input = FakeLocator()
    intelligent_extract = FakeLocator()

    async def first_visible(_page, selectors, _timeout):
        if selectors is adapter.selectors.query_inputs:
            return query_input
        if selectors is adapter.selectors.intelligent_extract_buttons:
            return intelligent_extract
        if selectors is adapter.selectors.extracted_publish_buttons:
            return None
        raise AssertionError("提取失败后不应退回普通发布流程")

    monkeypatch.setattr(adapter, "_first_visible", first_visible)
    monkeypatch.setattr(adapter, "_settle", AsyncMock())
    monkeypatch.setattr(adapter, "_raise_if_blocked", AsyncMock())
    monkeypatch.setattr(adapter, "_captcha_visible", AsyncMock(return_value=False))

    with pytest.raises(PageStructureChanged, match="信息正确，直接发布"):
        await adapter.prepare_request(object(), "10.1000/example")

    assert intelligent_extract.clicks == 1
