#!/usr/bin/env python3
"""Read-only NCDx geography decoder for EUZ logical files from CD_7190.

Verified on user-provided Siemens EU44420940.82 CTY/CNY/RL/TYP/CL/CT.
No writes to source; output is CSV/GeoJSON/JSON in a separate new directory.
The road files here provide NAMES, not decoded road geometry or navigation routing.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import struct
from datetime import datetime, timezone

BASE = 94
FORMATS = {
    "CTY": (3, 178, 34),
    "CNY": (12, 174, 30),
    "RL": (21, 61, 7),
    "TYP": (1, 54, 13),
    "CL": (19, 44, 6),
    "CT": (20, 14, None),
    "IOF": (21, 6, None),
}


def decode_text(raw: bytes) -> str:
    # All observed text bytes in the checked name fields decode with cp1252.
    # Trim only trailing padding; do not silently strip significant characters.
    return raw.split(b"\0", 1)[0].decode("cp1252")


def sha256(path: Path) -> str:
    dig = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            dig.update(chunk)
    return dig.hexdigest()


def load_file(input_dir: Path, name: str, expected_sha: str | None = None):
    path = input_dir / ("EUZ." + name + ".logical.bin")
    d = path.read_bytes()
    if d[:7] != b"SIEMENS":
        raise ValueError(f"{name}: SIEMENS header missing")
    file_type, count, declared = struct.unpack_from("<HII", d, 84)
    fmt_type, stride, _ = FORMATS[name]
    if file_type != fmt_type:
        raise ValueError(f"{name}: unexpected file type {file_type}; expected {fmt_type}")
    if len(d) != BASE + count * stride:
        raise ValueError(f"{name}: incompatible fixed-record layout. actual={len(d)}, expected={BASE + count * stride}")
    data_code = decode_text(d[47:63])
    digest = hashlib.sha256(d).hexdigest()
    if expected_sha and digest != expected_sha:
        raise ValueError(f"{name}: SHA-256 mismatch with earlier EVIDENCE.json")
    return d, {"type_id": file_type, "records": count, "record_bytes": stride,
               "header_bytes": BASE, "size_bytes": len(d), "header_word_90": declared,
               "data_code": data_code, "sha256": digest}


def iter_records(data: bytes, n: int, stride: int):
    for i in range(n):
        base = BASE + stride * i
        yield i, data[base:base + stride]


def parse_regions(data: bytes, meta: dict) -> list[dict]:
    out = []
    for i, record in iter_records(data, meta["records"], meta["record_bytes"]):
        region_id = struct.unpack_from("<H", record, 0)[0]
        if region_id != i:
            raise ValueError(f"CNY: region_id {region_id} != record index {i}")
        name = decode_text(record[30:])
        if not name:
            raise ValueError(f"CNY: empty name at record {i}")
        out.append({"region_id": i, "name": name})
    return out


def parse_cities(data: bytes, meta: dict, regions: list[dict]) -> list[dict]:
    out = []
    for i, record in iter_records(data, meta["records"], meta["record_bytes"]):
        city_id, region_id = struct.unpack_from("<II", record, 0)
        if city_id != i:
            raise ValueError(f"CTY: city_id {city_id} != record index {i}")
        if region_id >= len(regions):
            raise ValueError(f"CTY: missing CNY region for city={i}, region={region_id}")
        if record[8:18] != b"\x00" * 10:
            raise ValueError(f"CTY: unexpected nonzero reserved bytes at record {i}")
        x1, y1, x2, y2 = struct.unpack_from("<iiii", record, 18)
        if not (-18000000 <= x1 <= x2 <= 18000000 and -9000000 <= y1 <= y2 <= 9000000):
            raise ValueError(f"CTY: invalid geographic bounding values at city {i}")
        name = decode_text(record[34:])
        if not name:
            raise ValueError(f"CTY: empty name at record {i}")
        out.append({
            "city_id": i, "name": name,
            "region_id": region_id, "region_name": regions[region_id]["name"],
            "lon_min": x1 / 100000, "lat_min": y1 / 100000,
            "lon_max": x2 / 100000, "lat_max": y2 / 100000,
            "lon_center": (x1+x2) / 200000, "lat_center": (y1+y2) / 200000,
        })
    return out


def parse_names(data: bytes, meta: dict, nameoffset: int) -> list[dict]:
    out = []
    for i, record in iter_records(data, meta["records"], meta["record_bytes"]):
        out.append({"record_index": i, "name": decode_text(record[nameoffset:])})
    return out


def parse_aliases(data: bytes, meta: dict, cities: list[dict]) -> list[dict]:
    """CL strings use the 2-byte prefix at offset +4 and suffix at +6."""
    out = []
    for i, record in iter_records(data, meta["records"], meta["record_bytes"]):
        city_id = struct.unpack_from("<I", record, 0)[0]
        if not 0 <= city_id < len(cities):
            raise ValueError(f"CL: missing CTY city index {city_id} at record {i}")
        alias = decode_text(record[4:])
        out.append({"record_index": i, "city_id": city_id,
                    "lookup_name": alias, "city_name": cities[city_id]["name"],
                    "exact_city_name": alias == cities[city_id]["name"]})
    return out


def parse_road_names(data: bytes, meta: dict, iof_count: int) -> list[dict]:
    """RL first u32 values lie in range of IOF record indices; reference meaning remains tentative."""
    out = []
    for i, record in iter_records(data, meta["records"], meta["record_bytes"]):
        candidate = struct.unpack_from("<I", record, 0)[0]
        if candidate >= iof_count:
            raise ValueError(f"RL: reference candidate {candidate} exceeds IOF count")
        out.append({"record_index": i, "ref_candidate_iof_index":candidate,
                    "name":decode_text(record[7:])})
    return out


def find_input_path() -> Path:
    candidates = [Path.cwd(), Path.cwd() / "decoded", Path.cwd() / "LAB_OUTPUT" / "decoded",
                  Path(__file__).resolve().parent / "decoded",
                  Path(__file__).resolve().parent / "LAB_OUTPUT" / "decoded"]
    for c in candidates:
        if (c / "EUZ.CTY.logical.bin").is_file() and (c / "EUZ.CNY.logical.bin").is_file():
            return c
    try:
        from tkinter import Tk, filedialog
        root = Tk(); root.withdraw()
        selected = filedialog.askopenfilename(title="Оберіть EUZ.CTY.logical.bin", filetypes=[("Binary files", "*.bin"),("All", "*.*")])
        root.destroy()
        if selected:
            return Path(selected).parent
    except Exception:
        pass
    raise FileNotFoundError("Could not find decoded files. Use --input-dir PATH")


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only EUZ geography decoder")
    ap.add_argument("--input-dir", type=Path)
    ap.add_argument("--output-dir", type=Path)
    ap.add_argument("--evidence", type=Path, help="Original EVIDENCE.json for source SHA-256 cross-check")
    args = ap.parse_args()
    source = args.input_dir or find_input_path()
    if not source.is_dir():
        raise FileNotFoundError(source)
    root = args.output_dir or (Path(__file__).resolve().parent / "OUTPUT_GEO")
    # Do not silently replace earlier results.
    outdir = root
    if outdir.exists():
        suffix = datetime.now(timezone.utc).strftime("_%Y%m%dT%H%M%SZ")
        outdir = root.with_name(root.name + suffix)
        if outdir.exists():
            raise FileExistsError(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    epath = args.evidence or (source.parent / "EVIDENCE.json")
    ref = json.loads(epath.read_text(encoding="utf-8")) if epath.is_file() else {}
    data, meta = {}, {}
    for name in FORMATS:
        expected = ref.get("files", {}).get("EUZ." + name, {}).get("logical_sha256")
        data[name], meta[name] = load_file(source, name, expected)
    if len(set(v["data_code"] for v in meta.values())) != 1:
        raise ValueError("Mixed dataset codes. Do not merge different discs")
    regions = parse_regions(data["CNY"], meta["CNY"])
    cities = parse_cities(data["CTY"], meta["CTY"], regions)
    roads = parse_road_names(data["RL"], meta["RL"], meta["IOF"]["records"])
    types = parse_names(data["TYP"], meta["TYP"], 13)
    aliases = parse_aliases(data["CL"], meta["CL"], cities)
    write_csv(outdir / "regions.csv", regions, ["region_id", "name"])
    write_csv(outdir / "cities.csv", cities, ["city_id", "name", "region_id", "region_name", "lon_min", "lat_min", "lon_max", "lat_max", "lon_center", "lat_center"])
    write_csv(outdir / "road_names.csv", roads, ["record_index", "ref_candidate_iof_index", "name"])
    write_csv(outdir / "street_types.csv", types, ["record_index", "name"])
    write_csv(outdir / "city_lookup_aliases.csv", aliases, ["record_index", "city_id", "lookup_name", "city_name", "exact_city_name"])
    # GeoJSON coordinates are point-in-bounding-box centers, not verified city centers.
    with (outdir / "city_bbox_centers.geojson").open("w", encoding="utf-8") as fh:
        fh.write('{"type":"FeatureCollection","features":[\n')
        for i, c in enumerate(cities):
            feat = {"type": "Feature", "properties": {"city_id":c["city_id"], "name":c["name"], "region_id":c["region_id"], "region":c["region_name"], "point_kind":"BBOX_CENTER_NOT_OFFICIAL_CENTROID"}, "geometry":{"type":"Point","coordinates":[c["lon_center"],c["lat_center"]]}}
            fh.write((",\n" if i else "") + json.dumps(feat, ensure_ascii=False, separators=(",", ":")))
        fh.write("\n]}\n")
    result = {
        "status": "PASS", "dataset":meta["CTY"]["data_code"],
        "claim": "CTY city records and CNY region index linkage decoded; no route graph or navigable disc",
        "evidence_verified_against_manifest": bool(ref),
        "files":meta,
        "validated": {"city_records": len(cities), "region_records": len(regions), "city_ids_sequential":True,
                      "all_city_region_ids_in_range":True,"all_regions_referenced": len(set(x["region_id"] for x in cities))==len(regions),
                      "bbox_coordinate_scale": 100000, "bbox_order_and_degree_range_all_pass":True,
                      "road_name_entries":len(roads),"type_name_entries":len(types),"city_lookup_alias_entries":len(aliases),"alias_exact_city_name":sum(e["exact_city_name"] for e in aliases),"alias_not_exact_city_name":sum(not e["exact_city_name"] for e in aliases),"alias_distinct_city_ids":len({e["city_id"] for e in aliases}),"rl_reference_candidates_in_iof_range":True,"iof_records":meta["IOF"]["records"]},
        "examples": [cities[x] for x in [0,1,10,100,1000,5000,20000,len(cities)-1]],
        "limitations": ["City coordinate fields are bounding rectangles, not roads nor confirmed official city centers", "Assumes CP1252 on observed name fields; verify across other disc datasets", "Record layout proven on EU44420940.82 only", "RL first u32 points within IOF index space, but semantics are not yet proven", "CL alternate names may include length-limited or translated labels, not all are strict synonyms", "Does not decode EUZ.RT or MP0/MG1/MG2/MG3 or routing indexes", "This output is not a disk and must not be burned for NCDR 1500"],
    }
    (outdir / "EVIDENCE_GEOGRAPHY.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("GEO_DECODE_PASS",len(cities),"cities",len(regions),"regions",len(aliases),"city name lookup records",len(roads),"road-name records")
    print("OUTPUT:",outdir)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
