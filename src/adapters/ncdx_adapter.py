"""Future export boundary for a confirmed NCDx schema.

The Virtual CID internal model is intentionally independent from the Opel
container. This adapter remains unavailable until a record-level format is
confirmed by original-disc readback and an independent parser.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class NcdxFormatUnconfirmed(RuntimeError):
    pass


class NcdxAdapter:
    format_confirmed = False
    validation_available = False

    def read_validation_image(self, path: str | Path) -> Any:
        raise NcdxFormatUnconfirmed(
            "NCDx validation is disabled: only the fixed MP0 header is decoded; payload/index semantics are unknown."
        )

    def export_intermediate_map(self, intermediate_db: str | Path, output_path: str | Path) -> None:
        raise NcdxFormatUnconfirmed(
            "NCDx writing is disabled until the target format, record semantics, and independent readback are confirmed."
        )

