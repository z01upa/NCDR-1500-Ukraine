# XREF v4 — targeted firmware cross-reference

This directory records a read-only, bounded examination of the already
identified `NAVIMAIN.EXE` and `NK.BIN`, reusing the existing PE header, import,
and embedded-PE readers. It does not create another Writer or repeat the MP0
geometry/topology sweep.

Run from the `NCDR_MAP_RESEARCH` root:

```powershell
python research/geometry_breakthrough/xref_v4/firmware_xref.py
python -m unittest discover -s research/geometry_breakthrough/xref_v4/tests -p "test_*.py" -v
```

The report binds both inputs to prior SHA-256 manifests and records exact
entrypoint/RVA/file offsets, raw bytes, imports and IAT literals, marker
searches, NK.BIN candidate signatures, and the already-established
high-degree topology count. Machine words are preserved as hex; no SH4
instruction is claimed as decoded.
