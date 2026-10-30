from __future__ import annotations

import math
import re
import struct
from typing import Sequence


MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
_HEADER_MIN_BYTES = 110
_HEADER_SCALE = 100_000
_MEASUREMENT = re.compile(r"alignment_([0-7])/scale_(100000|1000000|10000000)_(lat_lon|lon_lat)\Z")


def _bounds(value: Sequence[float], name: str) -> tuple[float, float, float, float]:
    if isinstance(value, (str, bytes)) or len(value) != 4:
        raise ValueError(f"{name} must be (min_lat, min_lon, max_lat, max_lon)")
    try:
        south, west, north, east = (float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} contains a non-numeric bound") from exc
    if not all(math.isfinite(item) for item in (south, west, north, east)):
        raise ValueError(f"{name} contains a non-finite bound")
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError(f"{name} is outside ordered WGS84 bounds")
    return south, west, north, east


def parse_geographic_header(header: bytes) -> dict:
    """Read fixed geographic-header facts; this does not identify road semantics."""
    if not isinstance(header, bytes) or len(header) < _HEADER_MIN_BYTES:
        raise ValueError("geographic header must contain at least 110 bytes")
    marker_ok = header[:7] == b"SIEMENS" or header[:13] == b"(*$SIEMENS&^)"
    if not marker_ok:
        raise ValueError("unrecognized geographic header magic")
    type_id = struct.unpack_from("<H", header, 84)[0]
    record_count = struct.unpack_from("<I", header, 86)[0]
    field_90_u32 = struct.unpack_from("<I", header, 90)[0]
    west_i, south_i, east_i, north_i = struct.unpack_from("<iiii", header, 94)
    bbox_i32 = [west_i, south_i, east_i, north_i]
    bbox_degrees = [value / _HEADER_SCALE for value in bbox_i32]
    west, south, east, north = bbox_degrees
    bbox_valid = (-180 <= west < east <= 180 and -90 <= south < north <= 90)
    return {
        "magic": "(*$SIEMENS&^)" if header[:13] == b"(*$SIEMENS&^)" else "SIEMENS",
        "type_id": type_id,
        "record_count": record_count,
        "field_90_u32_uninterpreted": field_90_u32,
        "bbox_i32": bbox_i32,
        "bbox_degrees": bbox_degrees,
        "bbox_valid": bbox_valid,
        "semantic_claim": "fixed header fields only; record and road semantics unknown",
    }


def _city_box_index(city_boxes: Sequence[Sequence[int]]) -> tuple[dict, list]:
    if isinstance(city_boxes, (str, bytes)) or len(city_boxes) > 100_000:
        raise ValueError("city_boxes must be a bounded sequence of at most 100000 boxes")
    grid: dict[tuple[int, int], list[tuple[int, float, float, float, float]]] = {}
    wide: list[tuple[int, float, float, float, float]] = []
    for index, box in enumerate(city_boxes):
        if isinstance(box, (str, bytes)) or len(box) != 4:
            raise ValueError("each city box must be (min_lon, min_lat, max_lon, max_lat) at 1e5 scale")
        try:
            min_lon, min_lat, max_lon, max_lat = (float(item) / _HEADER_SCALE for item in box)
        except (TypeError, ValueError) as exc:
            raise ValueError("city box contains a non-numeric bound") from exc
        if not all(math.isfinite(item) for item in (min_lon, min_lat, max_lon, max_lat)):
            raise ValueError("city box contains a non-finite bound")
        if not (-180 <= min_lon <= max_lon <= 180 and -90 <= min_lat <= max_lat <= 90):
            raise ValueError("city box is outside WGS84 bounds")
        entry = (index, min_lon, min_lat, max_lon, max_lat)
        x0, x1 = math.floor(min_lon), math.floor(max_lon)
        y0, y1 = math.floor(min_lat), math.floor(max_lat)
        cell_count = (x1 - x0 + 1) * (y1 - y0 + 1)
        if cell_count > 64:
            wide.append(entry)
            continue
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                grid.setdefault((x, y), []).append(entry)
    return grid, wide


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    value = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    return radius * 2.0 * math.asin(min(1.0, math.sqrt(value)))


def analyze_payload(payload: bytes, measurement: str, region_bounds: Sequence[float],
                    control_bounds: Sequence[float], city_boxes: Sequence[Sequence[int]],
                    max_step_km: float = 5.0) -> dict:
    """Count bounded coordinate-like values against geography without retaining them."""
    if not isinstance(payload, bytes) or len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("payload must be bytes no larger than 4 MiB")
    match = _MEASUREMENT.fullmatch(str(measurement))
    if not match:
        raise ValueError("measurement must declare alignment, supported scale and coordinate order")
    alignment, scale_text, order = match.groups()
    alignment_bytes = int(alignment)
    scale = int(scale_text)
    region = _bounds(region_bounds, "region_bounds")
    control = _bounds(control_bounds, "control_bounds")
    try:
        step_limit = float(max_step_km)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_step_km must be a finite positive distance") from exc
    if not math.isfinite(step_limit) or step_limit <= 0 or step_limit > 20050:
        raise ValueError("max_step_km must be finite and between 0 and 20050")
    grid, wide_boxes = _city_box_index(city_boxes)

    region_pairs = 0
    control_pairs = 0
    city_hits = 0
    hit_box_ids: set[int] = set()
    adjacent = 0
    max_continuous = 0
    current_continuous = 0
    previous_region_point = None
    end = len(payload) - 7
    for offset in range(alignment_bytes, max(alignment_bytes, end), 8):
        first, second = struct.unpack_from("<ii", payload, offset)
        if order == "lat_lon":
            latitude, longitude = first / scale, second / scale
        else:
            longitude, latitude = first / scale, second / scale
        inside_region = (region[0] <= latitude <= region[2]
                         and region[1] <= longitude <= region[3])
        inside_control = (control[0] <= latitude <= control[2]
                          and control[1] <= longitude <= control[3])
        if inside_region:
            region_pairs += 1
            candidates = list(grid.get((math.floor(longitude), math.floor(latitude)), ()))
            candidates.extend(wide_boxes)
            point_box_hits = [entry[0] for entry in candidates
                              if entry[1] <= longitude <= entry[3]
                              and entry[2] <= latitude <= entry[4]]
            if point_box_hits:
                city_hits += 1
                hit_box_ids.update(point_box_hits)
            distance = (_haversine_km(previous_region_point[0], previous_region_point[1],
                                       latitude, longitude)
                        if previous_region_point is not None else 0.0)
            if previous_region_point is not None and 0.0 < distance <= step_limit:
                adjacent += 1
                current_continuous += 1
            else:
                current_continuous = 1
            if current_continuous > max_continuous:
                max_continuous = current_continuous
            previous_region_point = (latitude, longitude)
        else:
            current_continuous = 0
            previous_region_point = None
        if inside_control:
            control_pairs += 1

    return {
        "measurement": measurement,
        "coordinate_candidate_pairs_in_region": region_pairs,
        "coordinate_pairs_in_displaced_control": control_pairs,
        "points_inside_cty_city_bounding_boxes": city_hits,
        "distinct_cty_city_boxes_hit": len(hit_box_ids),
        "adjacent_pairs_within_5km": adjacent if step_limit == 5.0 else None,
        "adjacent_pairs_within_max_step_km": adjacent,
        "max_step_km": step_limit,
        "max_continuous_region_candidate_points": max_continuous,
        "payload_bytes_examined": len(payload),
        "raw_coordinate_values_retained": False,
        "road_geometry_decoded": False,
        "semantic_claim": "geographic coordinate candidates only; road geometry unproven",
    }
