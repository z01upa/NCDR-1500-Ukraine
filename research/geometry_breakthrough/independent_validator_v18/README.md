# Independent new-edge validator
Python 3.9+, standard library. No model/API/pypcode installation needed for validation. Original files opened read-only. Reader and topology_v6 are reused, not rewritten.

From this folder on Lenovo:
```
python validate_new_edge.py "C:\maps\original\EUZ.MP0" "C:\maps\candidate\EUZ.MP0" --reader-project "C:\path\NCDR_MAP_RESEARCH" --report validation.json
```
On Mac use python3. --reader-project must contain research/geometry_breakthrough/topology_v6/topology_decoder.py and research/geometry_breakthrough/independent_verify.py. Automatic discovery supports this Mac's NCDR_ASTRA_TRANSFER/project layout. Missing dependencies are reported as a failure, not silently replaced.

See VALIDATION_CONTRACT.md for strict append/identity constraints and exit codes. JSON reports distinguish FAIL from UNKNOWN. PASS does not certify the device. No Writer/Reader/GUI source was modified and no new edge was created.

Two approaches only: bounded static SH4 inspection, then comparative validation using existing readers. Account-wide five-hour usage was 8% at start and 24% before final checks; this is not per-model or per-task attribution.

The transfer package includes byte-identical copies of the two existing readers under dependencies/; --reader-project is optional. They are not forks or rewrites. Their hashes are recorded in each run.
