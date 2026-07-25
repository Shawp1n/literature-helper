from pypdf import PdfWriter

from literature_helper.pdfcheck import validate_pdf


def test_valid_pdf(tmp_path):
    path = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "Test"})
    with path.open("wb") as handle:
        writer.write(handle)

    report = validate_pdf(path, minimum_bytes=100)
    assert report.ok
    assert report.magic_ok
    assert report.readable
    assert report.page_count == 1
    assert len(report.sha256) == 64


def test_html_disguised_as_pdf(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_text("<html>login required</html>", encoding="utf-8")
    report = validate_pdf(path, minimum_bytes=10)
    assert not report.ok
    assert not report.magic_ok
    assert any("文件头" in item for item in report.warnings)
