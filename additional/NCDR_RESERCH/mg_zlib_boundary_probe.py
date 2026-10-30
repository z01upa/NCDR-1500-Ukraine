from pathlib import Path
import zlib

ROOT = Path("/Volumes/CD_7185/DB")
OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

FILES = {
    "MG1": (ROOT / "IZ.MG1").read_bytes(),
    "MG2": (ROOT / "IZ.MG2").read_bytes(),
}

# end = first byte AFTER suspected 4-byte zlib trailer.
TESTS = {
    "CDE744_GAP2": {
        "MG1": 0x20019A8,
        "MG2": 0x1323264,
    },
    "437B32_GAP1": {
        "MG1": 0x9B2F2C,
        "MG2": 0x57B3FA,
    },
}

SEARCH_BACK = 2 * 1024 * 1024
FEED_AFTER = 64


def valid_zlib_header(data, off):
    if off + 2 > len(data):
        return False

    cmf = data[off]
    flg = data[off + 1]

    if (cmf & 0x0F) != 8:
        return False

    if (cmf >> 4) > 7:
        return False

    return ((cmf << 8) | flg) % 31 == 0


def try_stream(data, start, expected_end):
    # Include a little data after expected end so unused_data
    # tells us exactly where the zlib stream stopped.
    stop = min(len(data), expected_end + FEED_AFTER)
    src = data[start:stop]

    try:
        d = zlib.decompressobj()
        raw = d.decompress(src)
        raw += d.flush()
    except zlib.error:
        return None

    if not d.eof:
        return None

    consumed = len(src) - len(d.unused_data)
    actual_end = start + consumed

    if actual_end != expected_end:
        return None

    trailer = data[expected_end - 4:expected_end]
    trailer_be = int.from_bytes(trailer, "big")

    calc = zlib.adler32(raw) & 0xFFFFFFFF

    return {
        "start": start,
        "end": actual_end,
        "packed_len": actual_end - start,
        "raw_len": len(raw),
        "trailer": trailer_be,
        "calculated": calc,
        "match": trailer_be == calc,
        "header": data[start:start+2].hex(),
        "first_raw": raw[:64].hex(),
        "last_raw": raw[-64:].hex(),
    }


report = OUT / "mg_zlib_boundary_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for test_name, offsets in TESTS.items():

        print("=" * 80, file=out)
        print("TEST:", test_name, file=out)

        results = {}

        for name in ("MG1", "MG2"):

            data = FILES[name]
            expected_end = offsets[name]

            trailer = data[expected_end-4:expected_end]

            print(file=out)
            print(name, file=out)
            print(
                f"EXPECTED END: 0x{expected_end:X}",
                file=out
            )
            print(
                "TRAILER:",
                trailer.hex(),
                file=out
            )
            print(
                "NEXT16:",
                data[expected_end:expected_end+16].hex(),
                file=out
            )

            lo = max(0, expected_end - SEARCH_BACK)

            candidates = []

            # Search backwards so nearest headers are tested first.
            for start in range(expected_end - 2, lo - 1, -1):

                if data[start] != 0x78:
                    continue

                if not valid_zlib_header(data, start):
                    continue

                r = try_stream(
                    data,
                    start,
                    expected_end
                )

                if r:
                    candidates.append(r)

                    # One exact stream ending here is sufficient,
                    # but retain a few in case nested false positives exist.
                    if len(candidates) >= 5:
                        break

            print(
                "VALID STREAMS ENDING HERE:",
                len(candidates),
                file=out
            )

            for i, r in enumerate(candidates):

                print(
                    f"  #{i+1} "
                    f"start=0x{r['start']:X} "
                    f"end=0x{r['end']:X} "
                    f"packed={r['packed_len']} "
                    f"raw={r['raw_len']} "
                    f"header={r['header']}",
                    file=out
                )

                print(
                    f"     trailer=0x{r['trailer']:08X} "
                    f"adler32=0x{r['calculated']:08X} "
                    f"MATCH={r['match']}",
                    file=out
                )

                print(
                    "     raw_first64=",
                    r["first_raw"],
                    file=out
                )

                print(
                    "     raw_last64=",
                    r["last_raw"],
                    file=out
                )

            results[name] = candidates

        print(file=out)
        print("CROSS FILE:", file=out)

        if results["MG1"] and results["MG2"]:

            a = results["MG1"][0]
            b = results["MG2"][0]

            print(
                "raw lengths:",
                a["raw_len"],
                b["raw_len"],
                file=out
            )

            print(
                "packed lengths:",
                a["packed_len"],
                b["packed_len"],
                file=out
            )

            print(
                "starts:",
                f"0x{a['start']:X}",
                f"0x{b['start']:X}",
                file=out
            )

        else:
            print(
                "No exact preceding zlib stream found "
                "for one or both files.",
                file=out
            )

print("Created:", report)
