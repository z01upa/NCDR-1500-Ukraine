"""Filter a dated Ukraine PBF to Kryvyi Rih and import its offline map database."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from src.osm.engine import import_osm_xml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "osm"
SOURCE_XML = DATA_DIR / "kryvyi_rih.osm.gz"
MAP_DB = DATA_DIR / "kryvyi_rih.sqlite"
PBF_PATH = DATA_DIR / "ukraine-latest.osm.pbf"
ENDPOINT = "https://overpass-api.de/api/interpreter"
USER_AGENT = "NCDR-Ukraine-local-map/0.1 (one-off Kryvyi Rih extract)"
BBOX = "47.58,32.50,48.23,33.95"
QUERY = f'''[out:xml][timeout:120];
(
  way["highway"]({BBOX});
  nwr["addr:housenumber"]({BBOX});
  nwr["amenity"]({BBOX});
  nwr["shop"]({BBOX});
  nwr["tourism"]({BBOX});
  nwr["leisure"]({BBOX});
  nwr["healthcare"]({BBOX});
  nwr["public_transport"]({BBOX});
);
out body;
>;
out skel qt;'''


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def download_overpass(
    max_attempts: int = 3,
    max_bytes: int = 300 * 1024 * 1024,
    output_path: Path | None = None,
) -> dict:
    overpass_xml = (output_path or DATA_DIR / "kryvyi_rih_overpass.osm").resolve()
    if overpass_xml.exists():
        return {"status": "CACHED", "path": str(overpass_xml), "bytes": overpass_xml.stat().st_size,
                "sha256": sha256_file(overpass_xml)}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    body = urllib.parse.urlencode({"data": QUERY}).encode("utf-8")
    error: str | None = None
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(ENDPOINT, data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                if response.status != 200:
                    raise RuntimeError(f"Overpass returned HTTP {response.status}")
                temporary = overpass_xml.with_suffix(".osm.part")
                size = 0
                with temporary.open("wb") as output:
                    while block := response.read(1024 * 1024):
                        size += len(block)
                        if size > max_bytes:
                            raise RuntimeError(f"Overpass response exceeded {max_bytes} byte safety cap")
                        output.write(block)
                if size < 1000:
                    raise RuntimeError(f"Overpass response is unexpectedly small ({size} bytes)")
                os_replace = overpass_xml.with_name(overpass_xml.name + ".tmp")
                temporary.replace(os_replace)
                os_replace.replace(overpass_xml)
                return {"status": "DOWNLOADED", "path": str(overpass_xml), "bytes": size,
                        "sha256": sha256_file(overpass_xml), "attempt": attempt}
        except (urllib.error.URLError, TimeoutError, RuntimeError, OSError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, urllib.error.HTTPError):
                retryable = exc.code in {429, 502, 503, 504}
            elif isinstance(exc, urllib.error.URLError):
                retryable = True
            else:
                retryable = isinstance(exc, TimeoutError) or "capacity" in error.casefold()
            if not retryable or attempt == max_attempts:
                break
            time.sleep(30 * (2 ** (attempt - 1)))
    raise RuntimeError(f"bounded Overpass download failed after {attempt} attempt(s): {error}")


def build(source: str = "geofabrik", force_fetch: bool = False,
          output_prefix: str | None = None) -> dict:
    if output_prefix is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", output_prefix):
        raise ValueError("output_prefix must contain only letters, digits, '_' or '-' (up to 64 characters)")
    city_xml = SOURCE_XML if output_prefix is None else DATA_DIR / f"{output_prefix}.osm.gz"
    map_db = MAP_DB if output_prefix is None else DATA_DIR / f"{output_prefix}.sqlite"
    metadata_path = DATA_DIR / ("source.json" if output_prefix is None else f"{output_prefix}.json")
    if output_prefix is None and map_db.is_file() and metadata_path.is_file():
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    if map_db.exists() or metadata_path.exists():
        raise FileExistsError(f"refusing to replace existing snapshot output: {map_db} or {metadata_path}")
    if force_fetch and city_xml.exists():
        raise RuntimeError("refusing to replace the cached OSM source; move it manually only if you intend a new dated snapshot")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if source == "geofabrik":
        from src.osm.download_geofabrik import download as download_pbf
        from src.osm.extract_pbf import extract_city
        if city_xml.exists():
            extraction = {"status": "CACHED_CITY_EXTRACT", "path": str(city_xml), "bytes": city_xml.stat().st_size,
                          "sha256": sha256_file(city_xml)}
            pbf_download = {"status": "CACHED_PBF" if PBF_PATH.exists() else "PBF_NOT_REQUIRED"}
        else:
            pbf_download = download_pbf()
            extraction = extract_city(PBF_PATH, city_xml)
        source_url = "https://download.geofabrik.de/europe/ukraine.html"
        dataset_timestamp = "2026-09-08T20:21:01Z (reported upstream content timestamp)"
        query = None
    elif source == "overpass":
        overpass_path = (DATA_DIR / f"{output_prefix}.osm" if output_prefix else
                         DATA_DIR / "kryvyi_rih_overpass.osm")
        extraction = download_overpass(output_path=overpass_path)
        overpass_path = Path(extraction["path"])
        source_url = ENDPOINT
        dataset_timestamp = "retrieved from Overpass; exact upstream base timestamp is not separately asserted"
        query = QUERY
        temporary_xml = overpass_path
        summary = import_osm_xml(temporary_xml, map_db)
        metadata = {"source": "OpenStreetMap via Overpass API", "source_url": source_url, "query": query,
            "retrieved_utc": datetime.now(timezone.utc).isoformat(), "dataset_timestamp": dataset_timestamp,
            "bbox_south_west_north_east": [47.58,32.50,48.23,33.95], "source_sha256": summary.source_sha256,
            "source_bytes": overpass_path.stat().st_size, "attribution": "Map data © OpenStreetMap contributors",
            "license": "Open Database License (ODbL)", "license_url": "https://www.openstreetmap.org/copyright",
            "download": extraction, "import_summary": summary.__dict__}
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata
    else:
        raise ValueError("source must be 'geofabrik' or 'overpass'")
    summary = import_osm_xml(city_xml, map_db)
    metadata = {
        "source": "OpenStreetMap via Geofabrik Ukraine regional extract",
        "source_url": source_url,
        "query": query,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_content_timestamp": dataset_timestamp,
        "pbf_download": pbf_download,
        "city_filter": extraction,
        "bbox_south_west_north_east": [47.58, 32.50, 48.23, 33.95],
        "source_sha256": summary.source_sha256,
        "source_bytes": city_xml.stat().st_size,
        "attribution": "Map data © OpenStreetMap contributors",
        "license": "Open Database License (ODbL)",
        "license_url": "https://www.openstreetmap.org/copyright",
        "importer_version": "0.1.0",
        "limitation": "City-sized bounding box; regional snapshot content is timestamped upstream; relation turn restrictions were not exported and routing remains experimental.",
        "import_summary": summary.__dict__,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and build a local Kryvyi Rih OSM map")
    parser.add_argument("--source", choices=("geofabrik", "overpass"), default="geofabrik")
    parser.add_argument("--force-fetch", action="store_true", help="refuse replacement; use a new source filename for another snapshot")
    parser.add_argument("--output-prefix", help="write a new snapshot as data/osm/<prefix>.sqlite and .json without replacing existing files")
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.force_fetch, args.output_prefix), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
