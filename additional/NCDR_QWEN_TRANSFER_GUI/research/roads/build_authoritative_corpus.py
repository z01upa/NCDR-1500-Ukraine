#!/usr/bin/env python3
"""Build the authoritative road corpus from confirmed CH_IDX ownership."""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
from pathlib import Path

from parse_roads import DB, ParseError, parse_brif, parse_ch_idx_entry, u16


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = list(rows[0]) if rows else ["empty"]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def haversine(a: dict, b: dict) -> float:
    p = math.pi / 180
    x = (math.sin((b["lat"] - a["lat"]) * p / 2) ** 2 +
         math.cos(a["lat"] * p) * math.cos(b["lat"] * p) *
         math.sin((b["lon"] - a["lon"]) * p / 2) ** 2)
    return 12_742_000 * math.asin(math.sqrt(x))


def slots_by_target(rows: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = collections.defaultdict(list)
    for row in rows:
        grouped[row["target_sector"]].append(row)
    return grouped


def build(db_path: Path, output: Path, scope_csv: Path | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    scope_sectors = None
    if scope_csv is not None:
        with scope_csv.open(newline="") as handle:
            scope_sectors = {int(row["o0e_sector"]) for row in csv.DictReader(handle)}
    roads: dict[tuple[int, int], dict] = {}
    invalid_brif = 0
    with DB(db_path) as db:
        selected: dict[int, set[int]] = collections.defaultdict(set)
        invalid_ch_idx = 0
        for sector, header in db.headers.items():
            if header.block_type != 0x0F:
                continue
            data = db.logical(sector)
            ptr, count = u16(data, 8), u16(data, 10)
            if ptr < 8 or count == 0 or ptr + count * 12 > len(data):
                invalid_ch_idx += 1
                continue
            for index in range(count):
                entry = parse_ch_idx_entry(data, ptr + index * 12, sector)
                target = db.headers.get(entry.target_sector)
                if target is None or target.span != entry.target_span:
                    invalid_ch_idx += 1
                    continue
                if target.block_type != 0x0E:
                    continue
                if scope_sectors is not None and entry.target_sector not in scope_sectors:
                    continue
                target_data = db.logical(entry.target_sector)
                if (entry.list_ptr < 8 or entry.list_count == 0 or
                        entry.list_ptr + entry.list_count * 8 > len(target_data)):
                    invalid_ch_idx += 1
                    continue
                selected[entry.target_sector].update(
                    entry.list_ptr + item * 8 for item in range(entry.list_count))

        for sector, offsets in selected.items():
            for offset in sorted(offsets):
                try:
                    roads[(sector, offset)] = parse_brif(db, sector, offset)
                except ParseError:
                    invalid_brif += 1

        objects: list[dict] = []
        duplicate_map: dict[tuple[int, int], set[str]] = collections.defaultdict(set)
        for (sector, brif), road in sorted(roads.items()):
            road_id = f"{sector:06X}:{brif:04X}"
            for index, obj in enumerate(road["objects"]):
                target = db.headers[obj["target_sector"]]
                readable = target.compression in (0, 2)
                raw32 = ""
                target_size = target.logical_size
                if readable:
                    logical = db.logical(obj["target_sector"])
                    target_size = len(logical)
                    if obj["ptr"] + 32 <= len(logical):
                        raw32 = logical[obj["ptr"]:obj["ptr"] + 32].hex()
                row = {
                    "road_id": road_id, "road_name": road["name"],
                    "road_object_index": index, "road_object_count": road["object_count"],
                    "0e_sector": sector, "object_start": obj["offset"],
                    "BL_ADDR_offset": obj["offset"] + 0x10,
                    "raw_hlon": obj["hlon"], "raw_hlat": obj["hlat"],
                    "lon": obj["lon"], "lat": obj["lat"],
                    "A": obj["A"], "B": obj["B"], "C": obj["C"], "D": obj["D"],
                    "target_sector": obj["target_sector"], "target_span": obj["target_span"],
                    "target_compression": target.compression,
                    "target_logical_size": target_size,
                    "E_raw": obj["E"], "E_flags": obj["E_flags"], "ptr": obj["ptr"],
                    "F": obj["F"], "raw32": raw32,
                    "physical_node_id": f'{obj["hlon"]:08X}{obj["hlat"]:08X}',
                }
                objects.append(row)
                duplicate_map[(sector, obj["offset"])].add(road_id)

        readable = [row for row in objects if row["raw32"]]
        write_csv(output / "authoritative_road_objects.csv", objects)
        write_csv(output / "authoritative_readable_objects.csv", readable)

        slots: dict[tuple[int, int], list[dict]] = collections.defaultdict(list)
        for row in readable:
            slots[(row["target_sector"], row["ptr"])].append(row)
        slot_rows = []
        for (sector, ptr), values in sorted(slots.items()):
            slot_rows.append({
                "target_sector": sector, "ptr": ptr, "raw32": values[0]["raw32"],
                "reference_count": len(values),
                "F_values": ";".join(map(str, sorted({v["F"] for v in values}))),
                "physical_node_count": len({v["physical_node_id"] for v in values}),
                "road_count": len({v["road_id"] for v in values}),
                "class": "Z" if int(values[0]["raw32"][32:36], 16) == 0 else "NZ",
            })
        write_csv(output / "authoritative_readable_slots.csv", slot_rows)

        by_road: dict[str, list[dict]] = collections.defaultdict(list)
        for row in objects:
            by_road[row["road_id"]].append(row)
        transitions = []
        for road_id, values in by_road.items():
            values.sort(key=lambda row: row["road_object_index"])
            collapsed = []
            for value in values:
                if not collapsed or value["physical_node_id"] != collapsed[-1]["physical_node_id"]:
                    collapsed.append(value)
            for left, right in zip(collapsed, collapsed[1:]):
                coverage = ("R" if left["raw32"] else "U") + ("R" if right["raw32"] else "U")
                transitions.append({
                    "road_id": road_id, "road_name": left["road_name"],
                    "P_node": left["physical_node_id"], "Q_node": right["physical_node_id"],
                    "P_object_index": left["road_object_index"], "Q_object_index": right["road_object_index"],
                    "distance_m": haversine(left, right), "coverage": coverage,
                    **{f"P_{key}": left[key] for key in ("target_sector", "ptr", "raw32", "A", "B", "C", "D", "E_raw", "F")},
                    **{f"Q_{key}": right[key] for key in ("target_sector", "ptr", "raw32", "A", "B", "C", "D", "E_raw", "F")},
                })
        write_csv(output / "authoritative_transitions.csv", transitions)
        rr = [row for row in transitions if row["coverage"] == "RR"]
        write_csv(output / "authoritative_rr_edges.csv", rr)

        nodes: dict[str, list[dict]] = collections.defaultdict(list)
        targets: dict[int, set[str]] = collections.defaultdict(set)
        for row in objects:
            nodes[row["physical_node_id"]].append(row)
            targets[row["target_sector"]].add(row["physical_node_id"])
        z = sum(row["class"] == "Z" for row in slot_rows)
        nz = len(slot_rows) - z
        summary = {
            "roads": len(roads), "owned_objects": len(objects),
            "readable_objects": len(readable), "invalid_ch_idx": invalid_ch_idx,
            "invalid_brif": invalid_brif,
            "duplicate_owned_offsets": sum(len(ids) > 1 for ids in duplicate_map.values()),
            "readable_ptr_in_bounds": len(readable),
            "ptr_mod32_distinct_by_target": max((len({v["ptr"] % 32 for v in values})
                                                   for values in slots_by_target(readable).values()), default=0),
            "unique_readable_slots": len(slot_rows), "readable_targets": len({r["target_sector"] for r in readable}),
            "Z_slots": z, "NZ_slots": nz,
            "F_invariant_slots": sum(len({v["F"] for v in values}) == 1 for values in slots.values()),
            "physical_nodes": len(nodes),
            "nodes_one_target": sum(len({v["target_sector"] for v in values}) == 1 for values in nodes.values()),
            "nodes_multi_target": sum(len({v["target_sector"] for v in values}) > 1 for values in nodes.values()),
            "targets_one_node": sum(len(values) == 1 for values in targets.values()),
            "targets_multi_node": sum(len(values) > 1 for values in targets.values()),
            "multi_object_roads": sum(len(values) > 1 for values in by_road.values()),
            "transition_occurrences": len(transitions),
            "unique_physical_pairs": len({tuple(sorted((r["P_node"], r["Q_node"]))) for r in transitions}),
            "coverage": dict(collections.Counter(r["coverage"] for r in transitions)),
        }
        (output / "authoritative_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("db0", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    parser.add_argument("--scope-csv", type=Path,
                        help="confirmed source-sector inventory; rows are never used as objects")
    args = parser.parse_args()
    print(json.dumps(build(args.db0, args.output, args.scope_csv), indent=2))
