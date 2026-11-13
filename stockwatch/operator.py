"""Import human-reviewed operator statements. Reading an import performs no network I/O."""

import hashlib
import json
import re
from urllib.parse import urlsplit

from .issuer import is_bulletin_url
from .model import Observation, utc


FIELDS = {
    "incident_id", "supplier", "status", "published_at", "clock_basis",
    "url", "locator", "title", "uncertainty", "next_check",
}
TSMC_HOSTS = {"pr.tsmc.com", "investor.tsmc.com", "www.tsmc.com"}
TSMC_SEC_FILING = re.compile(r"/Archives/edgar/data/1046179/[0-9]{18}/[\w-]+\.html?")


def _issuer_url(url: str) -> bool:
    if is_bulletin_url(url):
        return True
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.path.strip("/") or any(ch.isspace() for ch in url):
        return False
    if parts.netloc == "www.sec.gov":
        return bool(TSMC_SEC_FILING.fullmatch(parts.path))
    return parts.netloc in TSMC_HOSTS and "\\" not in url


def document_url(url: str) -> str:
    # A TWSE index may contain several disclosures; its row locator is part of
    # the reference. A fragment on an individual SEC filing locates a passage.
    return url if is_bulletin_url(url) else url.partition("#")[0]


def parse_updates(payload: bytes, seen_at: str) -> list[Observation]:
    """Use import time as receipt for every row. Accept or reject the batch as a unit."""
    receipt = utc(seen_at)
    rows = json.loads(payload)
    if not isinstance(rows, list) or not rows:
        raise ValueError("operator import requires a nonempty JSON array")
    observations = []
    for position, row in enumerate(rows, 1):
        if not isinstance(row, dict) or row.keys() != FIELDS:
            raise ValueError(f"operator row {position}: expected fields {', '.join(sorted(FIELDS))}")
        for key, value in row.items():
            if not isinstance(value, str) or not value.strip() or not value.isprintable():
                raise ValueError(f"operator row {position}: {key} must be nonblank single-line text")
        if not re.fullmatch(r"usgs:[A-Za-z0-9_-]+", row["incident_id"]):
            raise ValueError(f"operator row {position}: expected a USGS incident ID")
        if row["supplier"] != "TSMC" or not _issuer_url(row["url"]):
            raise ValueError(f"operator row {position}: expected a TSMC disclosure or its SEC filing")
        if row["status"] not in {"monitoring", "narrowed", "closed"}:
            raise ValueError(f"operator row {position}: unsupported operational watch status")
        publication = utc(row["published_at"])
        if publication > receipt:
            raise ValueError(f"operator row {position}: disclosure postdates the import")

        # The same document can address several incidents.
        document_key = hashlib.sha256(document_url(row["url"]).encode("utf-8")).hexdigest()
        facts = {k: row[k] for k in (
            "incident_id", "supplier", "status", "locator", "uncertainty", "next_check", "clock_basis",
        )}
        observations.append(Observation(
            id=f"operator:{row['incident_id']}:{document_key}",
            revision=publication,
            occurred_at=publication,
            seen_at=receipt,
            source="TSMC",
            url=row["url"],
            title=row["title"],
            kind="operator_update",
            facts=facts,
        ))
    return observations
