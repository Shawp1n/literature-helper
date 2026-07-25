from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)


class TaskStatus(StrEnum):
    CREATED = "created"
    WAITING_LOGIN = "waiting_login"
    MATCHING = "matching"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"
    WAITING_FILE = "waiting_file"
    DOWNLOADING = "downloading"
    DOWNLOADED_PENDING_REVIEW = "downloaded_pending_review"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = {
    TaskStatus.CREATED,
    TaskStatus.WAITING_LOGIN,
    TaskStatus.MATCHING,
    TaskStatus.READY_TO_PUBLISH,
    TaskStatus.PUBLISHED,
    TaskStatus.WAITING_FILE,
    TaskStatus.DOWNLOADING,
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class LiteratureMetadata:
    """Structured bibliographic data returned by AbleSci's smart extraction."""

    title: str | None = None
    doi: str | None = None
    url: str | None = None
    journal: str | None = None
    authors: list[str] = field(default_factory=list)
    publication_date: str | None = None
    source: str = "ablesci_intelligent_extract"
    extracted_at: str = field(default_factory=utc_now)

    @property
    def publication_year(self) -> int | None:
        if not self.publication_date:
            return None
        match = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", self.publication_date)
        return int(match.group()) if match else None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["publication_year"] = self.publication_year
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiteratureMetadata":
        authors = data.get("authors")
        journal = data.get("journal")
        if isinstance(journal, str) and re.fullmatch(r"[\d._-]+", journal.strip()):
            journal = None
        return cls(
            title=data.get("title"),
            doi=data.get("doi"),
            url=data.get("url"),
            journal=journal,
            authors=(
                [str(author) for author in authors]
                if isinstance(authors, list)
                else []
            ),
            publication_date=data.get("publication_date"),
            source=data.get("source") or "ablesci_intelligent_extract",
            extracted_at=data.get("extracted_at") or utc_now(),
        )


def classify_query(value: str) -> str:
    normalized = value.strip()
    if normalized.lower().startswith("https://doi.org/"):
        normalized = normalized[16:]
    return "doi" if DOI_PATTERN.fullmatch(normalized) else "title"


def normalize_query(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if normalized.lower().startswith("https://doi.org/"):
        normalized = normalized[16:]
    if not normalized:
        raise ValueError("DOI 或标题不能为空")
    if len(normalized) > 1_000:
        raise ValueError("输入过长；请输入单篇文献的 DOI 或准确标题")
    return normalized


@dataclass(slots=True)
class Task:
    id: str
    query: str
    query_type: str
    status: TaskStatus
    request_url: str | None
    download_path: Path | None
    literature: LiteratureMetadata | None
    validation: dict[str, Any] | None
    error: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        if self.download_path:
            data["download_path"] = str(self.download_path)
        if self.literature:
            data["literature"] = self.literature.to_dict()
        return data
