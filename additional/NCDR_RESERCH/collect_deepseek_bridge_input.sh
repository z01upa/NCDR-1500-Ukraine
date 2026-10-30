#!/bin/bash

set -u

SRC="$HOME/Desktop/NCDR_RESERCH"
DST="$SRC/DEEPSEEK_BRIDGE_INPUT"

mkdir -p "$DST"

echo "Collecting NCDR bridge research files..."
echo "SOURCE: $SRC"
echo "DEST:   $DST"
echo

copy_file () {
    src="$1"
    dst="$2"

    if [ -f "$src" ]; then
        echo "COPY: $src"
        cp -p "$src" "$dst"
        return 0
    fi

    return 1
}

copy_local_by_name () {
    name="$1"
    dstname="$2"

    found=$(
        find "$SRC" \
            -type f \
            -name "$name" \
            ! -path "$DST/*" \
            -print 2>/dev/null \
        | head -n 1
    )

    if [ -n "$found" ]; then
        echo "COPY LOCAL: $found"
        cp -p "$found" "$DST/$dstname"
        return 0
    fi

    echo "MISSING: $name"
    return 1
}

copy_disc_or_local () {
    discpath="$1"
    basename="$2"
    dstname="$3"

    if copy_file \
        "$discpath" \
        "$DST/$dstname"
    then
        return 0
    fi

    copy_local_by_name \
        "$basename" \
        "$dstname"
}

echo "============================================================"
echo "1. SQLITE SNAPSHOT"
echo "============================================================"

if [ -f "$SRC/mg_overnight.sqlite" ]; then
    rm -f "$DST/mg_overnight.sqlite"

    sqlite3 \
        "$SRC/mg_overnight.sqlite" \
        ".backup '$DST/mg_overnight.sqlite'"

    echo "SQLite snapshot created."

    echo -n "SQLite integrity: "
    sqlite3 \
        "$DST/mg_overnight.sqlite" \
        "PRAGMA integrity_check;"
else
    echo "MISSING: mg_overnight.sqlite"
fi

echo
echo "============================================================"
echo "2. ORIGINAL ROAD / ROUTING DATABASES"
echo "============================================================"

copy_disc_or_local \
    "/Volumes/CD_7185/DB/I.RD" \
    "I.RD" \
    "CD_7185_I.RD"

copy_disc_or_local \
    "/Volumes/CD_7185/DB/IZ.RT" \
    "IZ.RT" \
    "CD_7185_IZ.RT"

copy_disc_or_local \
    "/Volumes/CD_7185/DB/IZ.RL" \
    "IZ.RL" \
    "CD_7185_IZ.RL"

copy_disc_or_local \
    "/Volumes/CD_7186/DB/SC.RD" \
    "SC.RD" \
    "CD_7186_SC.RD"

copy_disc_or_local \
    "/Volumes/CD_7186/DB/SCZ.RT" \
    "SCZ.RT" \
    "CD_7186_SCZ.RT"

copy_disc_or_local \
    "/Volumes/CD_7186/DB/SCZ.RL" \
    "SCZ.RL" \
    "CD_7186_SCZ.RL"

echo
echo "============================================================"
echo "3. IMPORTANT REPORTS"
echo "============================================================"

copy_file \
    "$SRC/deep24/reports/05_nonmg_bridge_scan.txt" \
    "$DST/05_nonmg_bridge_scan.txt" \
|| copy_local_by_name \
    "05_nonmg_bridge_scan.txt" \
    "05_nonmg_bridge_scan.txt"

for f in \
    deep24_all_reports.txt \
    mg_24h_master_report.txt \
    mg_overnight_report.txt \
    mg_global_v5_report.txt \
    mg_global_v6_report.txt \
    gpu24_all_results.txt \
    lod_fuzzy_v2_report.txt \
    lod_reaggregate_by_class.txt \
    s65_exact_report.txt
do
    copy_local_by_name \
        "$f" \
        "$f"
done

echo
echo "============================================================"
echo "4. IMPORTANT SCRIPTS"
echo "============================================================"

for f in \
    mg_24h_autoresearch.py \
    mg_overnight_megaprobe.py \
    lod_fuzzy_cpu_v2.py \
    s65_exact_cpu_v1.py \
    gpu24_prepare.py \
    gpu_metric_miner.swift
do
    copy_local_by_name \
        "$f" \
        "$f"
done

echo
echo "============================================================"
echo "5. FORMAT DOCUMENTATION"
echo "============================================================"

for f in \
    FORMAT.md \
    FINDINGS.md \
    ROAD_FORMAT.md \
    OBJECT24_FORMAT.md \
    PROJECT_STATE.md \
    COMPRESSION01.md \
    TYPE00_ROAD_LISTS.md
do
    copy_local_by_name \
        "$f" \
        "$f"
done

echo
echo "============================================================"
echo "6. LEGACY DB_0 TABLES"
echo "============================================================"

for f in \
    phase12_road_refs.csv \
    type00_list_references.csv \
    type00_element_layout.csv \
    type00_targets.csv
do
    copy_local_by_name \
        "$f" \
        "$f"
done

echo
echo "============================================================"
echo "7. CREATE MANIFEST"
echo "============================================================"

{
    echo "NCDR DEEPSEEK BRIDGE INPUT"
    echo "Created: $(date)"
    echo
    echo "Purpose:"
    echo "MG -> RD -> RT/RL structural bridge research"
    echo
    echo "Files:"
    echo
    ls -lh "$DST"
} > "$DST/MANIFEST.txt"

echo
echo "============================================================"
echo "8. SHA256"
echo "============================================================"

rm -f "$DST/SHA256SUMS.txt"
touch "$DST/SHA256SUMS.txt"

for file in "$DST"/*
do
    [ -f "$file" ] || continue

    base=$(basename "$file")

    if [ "$base" = "SHA256SUMS.txt" ]; then
        continue
    fi

    hash=$(
        shasum -a 256 "$file" \
        | awk '{print $1}'
    )

    echo "$hash  $base" \
        >> "$DST/SHA256SUMS.txt"
done

echo
echo "============================================================"
echo "READY"
echo "============================================================"

echo "Folder:"
echo "$DST"
echo

echo "Size:"
du -sh "$DST"

echo
echo "Files:"
ls -lh "$DST"

echo
echo "SQLite:"
if [ -f "$DST/mg_overnight.sqlite" ]; then
    sqlite3 \
        "$DST/mg_overnight.sqlite" \
        "PRAGMA integrity_check;"
else
    echo "MISSING"
fi

echo
echo "DEEPSEEK_BRIDGE_INPUT READY"
