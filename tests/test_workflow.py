from unittest.mock import AsyncMock

import pytest
from pypdf import PdfWriter

from literature_helper.config import AppConfig
from literature_helper.models import LiteratureMetadata, TaskStatus
from literature_helper.workflow import LiteratureWorkflow, _merge_literature


@pytest.mark.asyncio
async def test_valid_download_is_automatically_accepted(tmp_path, monkeypatch):
    config = AppConfig.defaults(tmp_path / "app")
    config.minimum_pdf_bytes = 100
    config.auto_accept_after_validation = True
    workflow = LiteratureWorkflow(config, output=lambda _: None)
    task = workflow.store.create("10.1000/recovered")
    task = workflow.store.update(
        task.id,
        TaskStatus.WAITING_FILE,
        request_url="https://www.ablesci.com/assist/detail?id=test",
    )

    pdf_path = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    class Page:
        url = "https://www.ablesci.com/assist/detail?id=test"

        def is_closed(self):
            return False

        async def goto(self, url, **_kwargs):
            self.url = url

    page = Page()
    monkeypatch.setattr(
        workflow.adapter,
        "download",
        AsyncMock(return_value=pdf_path),
    )
    monkeypatch.setattr(
        workflow.adapter,
        "accept_uploaded_file",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "literature_helper.workflow.notify",
        lambda *_args, **_kwargs: True,
    )

    result = await workflow._download_and_validate(
        task,
        page,
        object(),
        download_dir=tmp_path,
    )

    assert result.status == TaskStatus.CONFIRMED
    workflow.adapter.accept_uploaded_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_closed_browser_cleanup_does_not_override_success(tmp_path):
    messages = []
    workflow = LiteratureWorkflow(
        AppConfig.defaults(tmp_path / "app"),
        output=messages.append,
    )

    class ClosedContext:
        async def close(self):
            raise RuntimeError(
                "BrowserContext.close: Target page, context or browser has been closed"
            )

    await workflow._safe_close_context(ClosedContext())

    assert messages == []


@pytest.mark.asyncio
async def test_credential_login_launches_headless_and_uses_adapter(
    tmp_path,
    monkeypatch,
):
    workflow = LiteratureWorkflow(AppConfig.defaults(tmp_path / "app"))
    page = object()

    class Context:
        pages = [page]

        async def close(self):
            pass

    playwright = object()

    class Manager:
        async def __aenter__(self):
            return playwright

        async def __aexit__(self, *_args):
            pass

    launch = AsyncMock(return_value=Context())
    credential_login = AsyncMock()
    monkeypatch.setattr(
        "literature_helper.workflow.async_playwright",
        lambda: Manager(),
    )
    monkeypatch.setattr(workflow, "_launch_context", launch)
    monkeypatch.setattr(
        workflow.adapter,
        "credential_login",
        credential_login,
    )

    await workflow.login(
        email="person@example.com",
        password="secret",
        headless=True,
    )

    launch.assert_awaited_once_with(playwright, headless=True)
    credential_login.assert_awaited_once_with(
        page,
        email="person@example.com",
        password="secret",
    )


@pytest.mark.asyncio
async def test_login_rejects_partial_credentials(tmp_path):
    workflow = LiteratureWorkflow(AppConfig.defaults(tmp_path / "app"))

    with pytest.raises(ValueError, match="同时提供"):
        await workflow.login(email="person@example.com")


def test_detail_metadata_completes_publish_page_metadata():
    earlier = LiteratureMetadata(
        doi="10.1000/example",
        journal=None,
    )
    later = LiteratureMetadata(
        title="A complete title",
        doi="10.1000/example",
        journal="Journal of Examples",
        authors=["Ada Lovelace"],
        publication_date="2024-10-01",
    )

    merged = _merge_literature(earlier, later)

    assert merged is not None
    assert merged.title == "A complete title"
    assert merged.journal == "Journal of Examples"
    assert merged.authors == ["Ada Lovelace"]
