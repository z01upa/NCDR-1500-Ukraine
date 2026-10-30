#!/usr/bin/env python3

from pathlib import Path
from collections import defaultdict
import sqlite3
import struct
import zlib
import subprocess
import json
import os
import time

ROOT = Path.home() / "Desktop" / "NCDR_RESERCH"
OUT = ROOT / "bridge_v1"
CACHE = OUT / "cache"

MGDB = ROOT / "mg_overnight.sqlite"
DB = OUT / "bridge.sqlite"

CACHE.mkdir(parents=True, exist_ok=True)

REAL_LIMIT = 12000
CONTROL_LIMIT = 4000
MAX_ANCHORS = 500

FILES = {
    "7185_RD": Path("/Volumes/CD_7185/DB/I.RD"),
    "7185_RT": Path("/Volumes/CD_7185/DB/IZ.RT"),
    "7185_RL": Path("/Volumes/CD_7185/DB/IZ.RL"),

    "7186_RD": Path("/Volumes/CD_7186/DB/SC.RD"),
    "7186_RT": Path("/Volumes/CD_7186/DB/SCZ.RT"),
    "7186_RL": Path("/Volumes/CD_7186/DB/SCZ.RL"),
}


def logical_path(key, src):
    with src.open("rb") as f:
        h = f.read(16)

    if h[:4] != b"zip\x01":
        return src

    bs, total, _ = struct.unpack_from("<III", h, 4)
    n = (total + bs - 1) // bs

    dst = CACHE / f"{key}.logical"

    if dst.exists() and dst.stat().st_size == total:
        return dst

    print("DECOMPRESS", key, total, flush=True)

    tmp = CACHE / f"{key}.logical.tmp"

    with src.open("rb") as f:
        f.seek(16)

        offs = struct.unpack(
            "<" + "I" * (n + 1),
            f.read(4 * (n + 1)),
        )

        produced = 0

        with tmp.open("wb") as out:
            for i in range(n):
                f.seek(offs[i])

                raw = zlib.decompress(
                    f.read(offs[i + 1] - offs[i])
                )

                out.write(raw)
                produced += len(raw)

    if produced != total:
        raise RuntimeError(
            f"{key}: {produced} != {total}"
        )

    tmp.replace(dst)

    return dst


def catalog(conn, country):
    datasets = [
        country + "_MG1",
        country + "_MG2",
        country + "_MG3",
    ]

    rows = conn.execute("""
        SELECT
            (s65 & 65535),
            (s66 & 65535),
            COUNT(*) AS n,
            COUNT(DISTINCT dataset) AS lods
        FROM edges
        WHERE dataset IN (?,?,?)
        GROUP BY
            (s65 & 65535),
            (s66 & 65535)
        ORDER BY
            n ASC,
            lods DESC
        LIMIT ?
    """, datasets + [REAL_LIMIT]).fetchall()

    out = []

    for s65, s66, n, lods in rows:
        s65 = int(s65) & 0xffff
        s66 = int(s66) & 0xffff

        out.append({
            "sig": (s65 << 16) | s66,
            "s65": s65,
            "s66": s66,
            "mg_count": int(n),
            "lod_count": int(lods),
            "kind": "real",
        })

    all_real = {
        x["sig"]
        for x in out
    }

    controls = []
    used = set()

    N = len(out)

    for shift in (997, 2003, 4001, 6007, 7919):
        if not N:
            break

        shift %= N

        if shift == 0:
            shift = 1

        for i, a in enumerate(out):
            b = out[(i + shift) % N]

            sig = (
                (a["s65"] << 16)
                | b["s66"]
            )

            if sig in all_real or sig in used:
                continue

            used.add(sig)

            controls.append({
                "sig": sig,
                "s65": a["s65"],
                "s66": b["s66"],
                "mg_count": 0,
                "lod_count": 0,
                "kind": "control",
            })

            if len(controls) >= CONTROL_LIMIT:
                break

        if len(controls) >= CONTROL_LIMIT:
            break

    return out + controls


C = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>

#define NS 8

typedef struct {
    uint32_t key;
    uint64_t count;
    uint64_t mod32[32];
    uint64_t sample[NS];
    uint32_t ns;
} Rec;

static Rec *r;
static uint32_t *ht;
static size_t nr, hs;

static uint32_t H(uint32_t x) {
    x ^= x >> 16;
    x *= 0x7feb352d;
    x ^= x >> 15;
    x *= 0x846ca68b;
    x ^= x >> 16;
    return x;
}

static void put(uint32_t key, uint32_t idx) {
    size_t m = hs - 1;
    size_t p = H(key) & m;

    while (ht[p])
        p = (p + 1) & m;

    ht[p] = idx + 1;
}

static int get(uint32_t key) {
    size_t m = hs - 1;
    size_t p = H(key) & m;

    while (ht[p]) {
        uint32_t i = ht[p] - 1;

        if (r[i].key == key)
            return i;

        p = (p + 1) & m;
    }

    return -1;
}

int main(int ac, char **av) {
    if (ac != 4)
        return 2;

    FILE *sf = fopen(av[1], "r");

    size_t cap = 20000;

    r = calloc(cap, sizeof(Rec));

    unsigned int k;

    while (fscanf(sf, "%x", &k) == 1) {
        if (nr == cap) {
            cap *= 2;
            r = realloc(r, cap * sizeof(Rec));
        }

        r[nr].key = k;
        nr++;
    }

    fclose(sf);

    hs = 1;

    while (hs < nr * 4)
        hs <<= 1;

    ht = calloc(hs, sizeof(uint32_t));

    for (uint32_t i = 0; i < nr; i++)
        put(r[i].key, i);

    int fd = open(av[2], O_RDONLY);

    struct stat st;
    fstat(fd, &st);

    size_t sz = st.st_size;

    unsigned char *p = mmap(
        0, sz, PROT_READ, MAP_PRIVATE, fd, 0
    );

    for (size_t off = 0; off + 3 < sz; off++) {
        uint32_t v =
            ((uint32_t)p[off] << 24) |
            ((uint32_t)p[off+1] << 16) |
            ((uint32_t)p[off+2] << 8) |
            p[off+3];

        int i = get(v);

        if (i < 0)
            continue;

        r[i].count++;
        r[i].mod32[off & 31]++;

        if (r[i].ns < NS)
            r[i].sample[r[i].ns++] = off;
    }

    munmap(p, sz);
    close(fd);

    FILE *o = fopen(av[3], "w");

    for (size_t i = 0; i < nr; i++) {
        fprintf(
            o,
            "%08x\t%llu\t",
            r[i].key,
            (unsigned long long)r[i].count
        );

        for (int j = 0; j < 32; j++) {
            if (j)
                fputc(',', o);

            fprintf(
                o,
                "%llu",
                (unsigned long long)r[i].mod32[j]
            );
        }

        fputc('\t', o);

        for (uint32_t j = 0; j < r[i].ns; j++) {
            if (j)
                fputc(',', o);

            fprintf(
                o,
                "%llu",
                (unsigned long long)r[i].sample[j]
            );
        }

        fputc('\n', o);
    }

    fclose(o);

    return 0;
}
'''


def scanner():
    c = CACHE / "selective_scan.c"
    exe = CACHE / "selective_scan"

    c.write_text(C)

    subprocess.run(
        [
            "clang",
            "-O3",
            str(c),
            "-o",
            str(exe),
        ],
        check=True,
    )

    return exe


def parse(path):
    d = {}

    with path.open() as f:
        for line in f:
            c = line.rstrip().split("\t")

            sig = int(c[0], 16)

            d[sig] = {
                "count": int(c[1]),
                "mod32": [
                    int(x)
                    for x in c[2].split(",")
                ],
                "samples": (
                    [
                        int(x)
                        for x in c[3].split(",")
                    ]
                    if len(c) > 3 and c[3]
                    else []
                ),
            }

    return d


def dom(hist, mod):
    h = [0] * mod

    for i, n in enumerate(hist):
        h[i % mod] += n

    total = sum(h)

    if not total:
        return None

    r = max(
        range(mod),
        key=lambda x: h[x],
    )

    return {
        "residue": r,
        "pct": 100.0 * h[r] / total,
        "hits": h[r],
    }


def main():
    print("SELECTIVE MG->RD/RT/RL SCAN V2")

    for k, p in FILES.items():
        if not p.exists():
            raise SystemExit(
                f"MISSING: {p}"
            )

    logical = {
        k: logical_path(k, p)
        for k, p in FILES.items()
    }

    mg = sqlite3.connect(
        f"file:{MGDB}?mode=ro",
        uri=True,
    )

    cats = {
        c: catalog(mg, c)
        for c in ("7185", "7186")
    }

    mg.close()

    for c, rows in cats.items():
        print(
            c,
            "real",
            sum(x["kind"] == "real" for x in rows),
            "control",
            sum(x["kind"] == "control" for x in rows),
            flush=True,
        )

        (CACHE / f"{c}.sig").write_text(
            "".join(
                f"{x['sig']:08x}\n"
                for x in rows
            )
        )

    exe = scanner()

    scans = {}

    for key, path in logical.items():
        country = key[:4]

        out = CACHE / f"{key}.counts.tsv"

        print(
            time.strftime("%H:%M:%S"),
            "SCAN",
            key,
            path.stat().st_size,
            flush=True,
        )

        subprocess.run(
            [
                str(exe),
                str(CACHE / f"{country}.sig"),
                str(path),
                str(out),
            ],
            check=True,
        )

        scans[key] = parse(out)

    db = sqlite3.connect(DB)

    db.execute("""
        CREATE TABLE IF NOT EXISTS
        selective_signature_stats (
            country TEXT,
            file_key TEXT,
            sig INTEGER,
            kind TEXT,
            s65 INTEGER,
            s66 INTEGER,
            mg_count INTEGER,
            lod_count INTEGER,
            hit_count INTEGER,
            mod2 TEXT,
            mod4 TEXT,
            mod8 TEXT,
            mod16 TEXT,
            mod32 TEXT,
            samples TEXT,
            PRIMARY KEY (
                country,file_key,sig,kind
            )
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS
        selective_anchors (
            country TEXT,
            sig INTEGER,
            s65 INTEGER,
            s66 INTEGER,
            mg_count INTEGER,
            lod_count INTEGER,
            rd_hits INTEGER,
            rt_hits INTEGER,
            rl_hits INTEGER,
            score REAL,
            PRIMARY KEY(country,sig)
        )
    """)

    for country, rows in cats.items():
        for filekey in (
            country + "_RD",
            country + "_RT",
            country + "_RL",
        ):
            for m in rows:
                q = scans[filekey][m["sig"]]

                db.execute("""
                    INSERT OR REPLACE INTO
                    selective_signature_stats
                    VALUES (
                        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                    )
                """, (
                    country,
                    filekey,
                    m["sig"],
                    m["kind"],
                    m["s65"],
                    m["s66"],
                    m["mg_count"],
                    m["lod_count"],
                    q["count"],
                    json.dumps(dom(q["mod32"],2)),
                    json.dumps(dom(q["mod32"],4)),
                    json.dumps(dom(q["mod32"],8)),
                    json.dumps(dom(q["mod32"],16)),
                    json.dumps(dom(q["mod32"],32)),
                    json.dumps(q["samples"]),
                ))

    anchors = []

    for country, rows in cats.items():
        tmp = []

        for m in rows:
            if m["kind"] != "real":
                continue

            sig = m["sig"]

            rd = scans[country+"_RD"][sig]["count"]
            rt = scans[country+"_RT"][sig]["count"]
            rl = scans[country+"_RL"][sig]["count"]

            if not rd or not (rt + rl):
                continue

            score = (
                (m["mg_count"] + 1)
                * (rd + 1)
                * (rt + rl + 1)
            )

            tmp.append({
                **m,
                "country": country,
                "rd": rd,
                "rt": rt,
                "rl": rl,
                "score": score,
            })

        strict = [
            x for x in tmp
            if (
                x["mg_count"] <= 64
                and x["rd"] <= 128
                and x["rt"] + x["rl"] <= 256
            )
        ]

        if len(strict) < 50:
            strict = [
                x for x in tmp
                if (
                    x["mg_count"] <= 256
                    and x["rd"] <= 512
                    and x["rt"] + x["rl"] <= 1024
                )
            ]

        if len(strict) < 50:
            strict = tmp

        strict.sort(
            key=lambda x: (
                x["score"],
                x["rd"],
                x["rt"] + x["rl"],
            )
        )

        strict = strict[:MAX_ANCHORS]

        anchors.extend(strict)

        for x in strict:
            db.execute("""
                INSERT OR REPLACE INTO
                selective_anchors
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                country,
                x["sig"],
                x["s65"],
                x["s66"],
                x["mg_count"],
                x["lod_count"],
                x["rd"],
                x["rt"],
                x["rl"],
                x["score"],
            ))

    db.commit()
    db.close()

    report = OUT / "02_selective_signature_report.txt"

    with report.open("w") as f:
        print(
            "NCDR SELECTIVE SIGNATURE REPORT V2",
            file=f,
        )

        print(
            "CONFIRMED suffix4_BE = BE16(s65) || BE16(s66)",
            file=f,
        )

        print(
            "Raw suffix4_BE is not a unique edge ID.",
            file=f,
        )

        print(file=f)

        for country in ("7185", "7186"):
            aa = [
                x for x in anchors
                if x["country"] == country
            ]

            print("=" * 90, file=f)
            print(country, "anchors", len(aa), file=f)
            print("=" * 90, file=f)

            for x in aa[:100]:
                print(
                    f"sig={x['sig']:08X} "
                    f"s65={x['s65']} "
                    f"s66={x['s66']} "
                    f"MG={x['mg_count']} "
                    f"LOD={x['lod_count']} "
                    f"RD={x['rd']} "
                    f"RT={x['rt']} "
                    f"RL={x['rl']} "
                    f"score={x['score']}",
                    file=f,
                )

            print(file=f)

    print()
    print("DONE")
    print("anchors:", len(anchors))
    print("report:", report)


if __name__ == "__main__":
    main()
