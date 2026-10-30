from pathlib import Path
import struct

ROOT = Path("/Volumes/CD_7185/DB")
OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

A_PATH = ROOT / "IZ.MG1"
B_PATH = ROOT / "IZ.MG2"

A = A_PATH.read_bytes()
B = B_PATH.read_bytes()

# Exact runs already established by mg_delta_runs.txt.
# (A_start, A_end, B_start, B_end)
GROUPS = {
    "delta_CDE744": [
        (0x1FFBCC5, 0x1FFF78D, 0x131D581, 0x1321049),
        (0x1FFF792, 0x20019A4, 0x132104E, 0x1323260),
        (0x20019A8, 0x201F356, 0x1323264, 0x1340C12),
    ],

    "delta_437B32": [
        (0x9B0BE4, 0x9B2F28, 0x5790B2, 0x57B3F6),
        (0x9B2F2C, 0x9C05B7, 0x57B3FA, 0x588A85),
    ],
}


def nums(data):
    r = []

    if len(data) >= 2:
        r += [
            ("u16be", struct.unpack(">H", data[:2])[0]),
            ("u16le", struct.unpack("<H", data[:2])[0]),
        ]

    if len(data) >= 3:
        r += [
            ("u24be", int.from_bytes(data[:3], "big")),
            ("u24le", int.from_bytes(data[:3], "little")),
        ]

    if len(data) >= 4:
        r += [
            ("u32be", struct.unpack(">I", data[:4])[0]),
            ("u32le", struct.unpack("<I", data[:4])[0]),
        ]

    return r


report = OUT / "mg_sparse_gap_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for group, runs in GROUPS.items():

        print("=" * 80, file=out)
        print(group, file=out)

        for i in range(len(runs) - 1):

            a1s, a1e, b1s, b1e = runs[i]
            a2s, a2e, b2s, b2e = runs[i + 1]

            agap = A[a1e:a2s]
            bgap = B[b1e:b2s]

            print(file=out)
            print(f"GAP {i+1}", file=out)

            print(
                f"A: 0x{a1e:X}..0x{a2s:X} "
                f"len={len(agap)}",
                file=out,
            )

            print(
                f"B: 0x{b1e:X}..0x{b2s:X} "
                f"len={len(bgap)}",
                file=out,
            )

            print("A GAP:", agap.hex(), file=out)
            print("B GAP:", bgap.hex(), file=out)

            print(
                "same length:",
                len(agap) == len(bgap),
                file=out,
            )

            if len(agap) == len(bgap):
                print(
                    "byte XOR:",
                    bytes(
                        x ^ y
                        for x, y in zip(agap, bgap)
                    ).hex(),
                    file=out,
                )

            print("A numeric:", file=out)

            for kind, value in nums(agap):
                print(
                    f"  {kind}: {value} "
                    f"(0x{value:X})",
                    file=out,
                )

            print("B numeric:", file=out)

            for kind, value in nums(bgap):
                print(
                    f"  {kind}: {value} "
                    f"(0x{value:X})",
                    file=out,
                )

            if len(agap) >= 4 and len(bgap) >= 4:

                abe = int.from_bytes(agap[:4], "big")
                bbe = int.from_bytes(bgap[:4], "big")

                ale = int.from_bytes(agap[:4], "little")
                ble = int.from_bytes(bgap[:4], "little")

                print(
                    "u32be B-A:",
                    bbe - abe,
                    f"({bbe-abe:+#x})",
                    file=out,
                )

                print(
                    "u32le B-A:",
                    ble - ale,
                    f"({ble-ale:+#x})",
                    file=out,
                )

            # Context around the changed field.
            CONTEXT = 48

            aa = max(0, a1e - CONTEXT)
            ae = min(len(A), a2s + CONTEXT)

            ba = max(0, b1e - CONTEXT)
            be = min(len(B), b2s + CONTEXT)

            print("A CONTEXT:", A[aa:ae].hex(), file=out)
            print("B CONTEXT:", B[ba:be].hex(), file=out)

            # Verify bytes immediately around the gap really are equal.
            left = min(32, a1e, b1e)
            right = min(
                32,
                len(A) - a2s,
                len(B) - b2s
            )

            print(
                "LEFT32 SAME:",
                A[a1e-left:a1e] == B[b1e-left:b1e],
                file=out,
            )

            print(
                "RIGHT32 SAME:",
                A[a2s:a2s+right] == B[b2s:b2s+right],
                file=out,
            )

print("Created:", report)
