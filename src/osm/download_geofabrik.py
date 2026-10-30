"""Stream the current Geofabrik Ukraine PBF to a project-local cache."""

from __future__ import annotations

import hashlib
from pathlib import Path
import urllib.error
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "osm"
PBF_PATH = DATA_DIR / "ukraine-latest.osm.pbf"
URL = "https://download.geofabrik.de/europe/ukraine-latest.osm.pbf"
USER_AGENT = "NCDR-Ukraine-local-map/0.1 (regional OSM extract download)"
MAX_BYTES = 1000 * 1024 * 1024


def download() -> dict[str, object]:
    if PBF_PATH.exists():
        return {"status": "CACHED", "path": str(PBF_PATH), "bytes": PBF_PATH.stat().st_size,
                "sha256": _sha256(PBF_PATH)}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = PBF_PATH.with_suffix(PBF_PATH.suffix + ".part")
    request = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open("xb") as output:
            content_length = int(response.headers.get("Content-Length", "0") or 0)
            if content_length and content_length > MAX_BYTES:
                raise RuntimeError(f"Ukraine extract exceeds {MAX_BYTES} byte safety cap: {content_length}")
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > MAX_BYTES:
                    raise RuntimeError(f"download exceeded {MAX_BYTES} byte safety cap")
                output.write(block)
            output.flush()
        if total < 100_000_000:
            raise RuntimeError(f"download unexpectedly small for the Ukraine regional extract: {total}")
        temporary.replace(PBF_PATH)
        return {"status": "DOWNLOADED", "path": str(PBF_PATH), "bytes": total,
                "sha256": _sha256(PBF_PATH), "url": URL, "response_last_modified": response.headers.get("Last-Modified")}
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    import json
    print(json.dumps(download(), ensure_ascii=True, indent=2))

