"""What a collector hands back to collect.py: the events it read, plus what disappeared."""

from dataclasses import dataclass, field


class CollectorError(Exception):
    """A problem with a source that the user can fix, reported in collector_runs."""


@dataclass
class Batch:
    events: list = field(default_factory=list)  # dicts with the events columns; see store.UPSERT_EVENT
    gone_ids: list = field(default_factory=list)  # events whose source record disappeared
    cached: int = 0  # records skipped because they hadn't changed since the last pass
    cursor: str | None = None  # new sources.cursor; None keeps the old one
