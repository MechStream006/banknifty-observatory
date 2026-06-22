from __future__ import annotations

import datetime
from typing import Any

from pydantic import SecretStr

from lib.config._settings import BNOSettings

_SNAPSHOT_TYPE = "bno_config_snapshot_v1"


def get_redacted_snapshot(settings: BNOSettings) -> dict[str, Any]:
    """
    Return a fully redacted configuration dict safe for lineage records and logs.

    All SecretStr fields are replaced with the literal string '[REDACTED]'.
    Non-secret fields are included at their actual values.
    The snapshot is JSON-serialisable (all values are str, int, bool, list, or None).

    Never call settings.model_dump() directly for logging or lineage purposes —
    use this function exclusively.
    """
    snapshot: dict[str, Any] = {}

    for field_name in settings.model_fields:
        value = getattr(settings, field_name)
        if isinstance(value, SecretStr):
            snapshot[field_name] = "[REDACTED]"
        else:
            snapshot[field_name] = value

    snapshot["_snapshot_type"] = _SNAPSHOT_TYPE
    snapshot["_snapshot_at"] = (
        datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    )

    return snapshot
