from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
DOI_URL_PREFIX = re.compile(
    r"^(?:https?://)?(?:dx\.)?doi\.org/",
    re.IGNORECASE,
)
MAX_FETCH_QUEUE_ITEMS = 10


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


@dataclass(frozen=True, slots=True)
class AccountPoints:
    """Current AbleSci points for the saved login session."""

    total: int
    retrieved_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    normalized = DOI_URL_PREFIX.sub("", value.strip(), count=1)
    return "doi" if DOI_PATTERN.fullmatch(normalized) else "title"


def normalize_query(value: str) -> str:
    normalized = " ".join(value.strip().split())
    normalized = DOI_URL_PREFIX.sub("", normalized, count=1)
    if not normalized:
        raise ValueError("DOI 或标题不能为空")
    if len(normalized) > 1_000:
        raise ValueError("输入过长；请输入单篇文献的 DOI 或准确标题")
    return normalized


def normalize_queries(values: Iterable[str]) -> list[str]:
    """Normalize a small sequential queue and reject ambiguous duplicates."""
    if isinstance(values, str):
        raise ValueError("多篇下载需要字符串列表，不能传入单个字符串")
    normalized = [normalize_query(value) for value in values]
    if not normalized:
        raise ValueError("顺序下载队列不能为空")
    if len(normalized) > MAX_FETCH_QUEUE_ITEMS:
        raise ValueError(
            f"单次顺序下载最多 {MAX_FETCH_QUEUE_ITEMS} 篇，"
            "请拆分队列以避免高频操作"
        )

    seen: set[str] = set()
    duplicates: list[str] = []
    for query in normalized:
        key = query.casefold()
        if key in seen and query not in duplicates:
            duplicates.append(query)
        seen.add(key)
    if duplicates:
        raise ValueError("顺序下载队列包含重复项：" + "；".join(duplicates))
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


@dataclass(slots=True)
class FetchQueueResult:
    """Structured result for a strictly sequential literature queue."""

    queries: list[str]
    tasks: list[Task] = field(default_factory=list)
    stopped_query: str | None = None
    error: dict[str, str] | None = None

    @property
    def successful_count(self) -> int:
        return sum(
            task.status
            in {
                TaskStatus.DOWNLOADED_PENDING_REVIEW,
                TaskStatus.CONFIRMED,
            }
            for task in self.tasks
        )

    @property
    def completed(self) -> bool:
        return (
            self.error is None
            and len(self.tasks) == len(self.queries)
            and self.successful_count == len(self.queries)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "queries": list(self.queries),
            "tasks": [task.to_dict() for task in self.tasks],
            "total_count": len(self.queries),
            "processed_count": len(self.tasks),
            "successful_count": self.successful_count,
            "completed": self.completed,
            "stopped_query": self.stopped_query,
            "error": self.error,
        }
