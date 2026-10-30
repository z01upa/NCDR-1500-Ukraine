import struct, sqlite3
from pathlib import Path
from collections import Counter

SCALE = 100_000.0
DB = Path.home() / "Desktop" / "NCDR_RESERCH" / "mg_overnight.sqlite"
FILES = [
    ("7185", Path("/Volumes/CD_7185/DB/I.RD")),
    ("7186", Path("/Volumes/CD_7186/DB/SC.RD")),
]

print("Loading eids...")
con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute("SELECT DISTINCT eid FROM edges")
eids = {row[0] for row in cur.fetchall()}
print(f"  unique eids: {len(eids)}")

def scan_rd(path):
    data = path.read_bytes()
    print(f"\n=== {path.name} size={len(data)} ===")

    LON_MIN, LON_MAX = int(-15*SCALE), int(40*SCALE)
    LAT_MIN, LAT_MAX = int(30*SCALE), int(75*SCALE)

    records = []
    N = len(data)
    i = 0
    while i < N - 20:
        a, b = struct.unpack_from("<ii", data, i)
        if LON_MIN <= a <= LON_MAX and LAT_MIN <= b <= LAT_MAX:
            start = i - 2
            if start >= 0:
                id1, id2 = struct.unpack_from("<II", data, i + 8)
                if id1 < 100_000_000 and id2 < 100_000_000:
                    name_start = start + 18
                    name_end = name_start
                    while name_end < min(N, name_start + 100) and data[name_end] != 0:
                        name_end += 1
                    if 0 < name_end - name_start < 80:
                        name = data[name_start:name_end].decode('latin-1', 'replace')
                        if any(c.isalnum() for c in name):
                            records.append({
                                'offset': start,
                                'lon': a / SCALE,
                                'lat': b / SCALE,
                                'id1': id1,
                                'id2': id2,
                                'name': name,
                            })
                            i = name_end + 1
                            continue
        i += 1

    print(f"  records found: {len(records)}")
    return records

for tag, path in FILES:
    recs = scan_rd(path)
    if not recs:
        continue
    print(f"  first 5 records:")
    for r in recs[:5]:
        print(f"    off=0x{r['offset']:X} lon={r['lon']:.5f} lat={r['lat']:.5f} "
              f"id1={r['id1']} id2={r['id2']} name={r['name']!r}")

    id1s = Counter(r['id1'] for r in recs)
    id2s = Counter(r['id2'] for r in recs)
    print(f"  unique id1: {len(id1s)}, unique id2: {len(id2s)}")
    print(f"  id1 range: {min(id1s)} .. {max(id1s)}")
    print(f"  id2 range: {min(id2s)} .. {max(id2s)}")

    in_eids_id1 = sum(1 for r in recs if r['id1'] in eids)
    in_eids_id2 = sum(1 for r in recs if r['id2'] in eids)
    print(f"  id1 in mg.eid: {in_eids_id1} / {len(recs)} "
          f"({100*in_eids_id1/len(recs):.2f}%)")
    print(f"  id2 in mg.eid: {in_eids_id2} / {len(recs)} "
          f"({100*in_eids_id2/len(recs):.2f}%)")
