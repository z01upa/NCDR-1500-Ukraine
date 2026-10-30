# MP0 Writer v1

Experimental full-container writer for one controlled edit to an existing MP0 edge. It reuses the current signed-secondary shape decoder and shape-tail encoder, preserves the original input, and refuses exact geometry copies in other blocks.

From the project root:

```powershell
python -B research/geometry_breakthrough/writer_v1/writer.py --dry-run
python -B research/geometry_breakthrough/writer_v1/writer.py
python -B research/geometry_breakthrough/writer_v1/verify_mp0.py --candidate research/geometry_breakthrough/writer_v1/EUZ_MP0_block886_edge1_geometry_experiment.MP0
python -B -m unittest discover -s research/geometry_breakthrough -t research/geometry_breakthrough -p 'test*.py' -v
```

The default source is `${NCDR_SOURCE_ROOT}\SW\DB\EUZ.MP0`. The default output is a new file in this directory. Existing output files are never overwritten. Block, edge, and point indexes are zero-based. The independent verifier imports `independent_verify.py`, not this Writer or the current decoder.

This v1 edits one existing shaped edge only. It updates the ordinary rounded-feet length field and full-file stream pointers after recompression. It does not add roads or alter direction flags. The test MP0 is not certified for an Opel unit or physical navigation use.
