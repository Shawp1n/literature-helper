from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pypdf import PdfReader


@dataclass(slots=True)
class PdfValidation:
    ok: bool
    path: str
    size_bytes: int
    sha256: str
    magic_ok: bool
    readable: bool
    page_count: int | None
    encrypted: bool
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pdf(path: Path, *, minimum_bytes: int = 8_000) -> PdfValidation:
    path = path.expanduser().resolve()
    if not path.is_file():
        return PdfValidation(
            ok=False,
            path=str(path),
            size_bytes=0,
            sha256="",
            magic_ok=False,
            readable=False,
            page_count=None,
            encrypted=False,
            error="文件不存在",
        )

    size = path.stat().st_size
    with path.open("rb") as handle:
        header = handle.read(5)
    magic_ok = header == b"%PDF-"
    warnings: list[str] = []
    if size < minimum_bytes:
        warnings.append(f"文件仅 {size} 字节，小于阈值 {minimum_bytes} 字节")
    if not magic_ok:
        warnings.append("文件头不是 %PDF-，可能下载到了登录页或错误页")

    readable = False
    page_count: int | None = None
    encrypted = False
    error: str | None = None
    if magic_ok:
        try:
            reader = PdfReader(str(path), strict=False)
            encrypted = reader.is_encrypted
            if encrypted:
                try:
                    reader.decrypt("")
                except Exception:
                    pass
            page_count = len(reader.pages)
            readable = page_count > 0
            if readable:
                _ = reader.pages[0].mediabox
        except Exception as exc:
            error = f"PDF 解析失败: {type(exc).__name__}: {exc}"

    ok = magic_ok and readable and size >= minimum_bytes
    return PdfValidation(
        ok=ok,
        path=str(path),
        size_bytes=size,
        sha256=_sha256(path),
        magic_ok=magic_ok,
        readable=readable,
        page_count=page_count,
        encrypted=encrypted,
        warnings=warnings,
        error=error,
    )
