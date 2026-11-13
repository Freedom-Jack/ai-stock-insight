"""The clocks and facts shared by source adapters and the watch engine."""

from dataclasses import dataclass
from datetime import datetime, timezone


def utc(value: str) -> str:
    """A single sortable representation. Never infer a timezone from the host."""
    if not isinstance(value, str):
        raise ValueError("expected an ISO 8601 timestamp with a UTC offset")
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("timestamp needs a UTC offset")
    try:
        as_utc = instant.astimezone(timezone.utc)
    except OverflowError as exc:
        raise ValueError("timestamp outside the supported UTC range") from exc
    return as_utc.isoformat(timespec="microseconds").replace("+00:00", "Z")


def now() -> str:
    return utc(datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class Observation:
    id: str                     # Stable identity within its source
    revision: str               # Publication/updated time of THIS source version
    occurred_at: str            # Earthquake origin time or operator statement time
    seen_at: str                # First local receipt of this version
    source: str
    url: str
    title: str
    kind: str
    facts: dict

    def __post_init__(self) -> None:
        for field in ("revision", "occurred_at", "seen_at"):
            object.__setattr__(self, field, utc(getattr(self, field)))
        if self.occurred_at > self.revision or self.revision > self.seen_at:
            raise ValueError(f"inconsistent event, source revision or receipt time for {self.id}")
