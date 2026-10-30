# Autonomous NK.BIN decoder — LK841
Python 3.8+; standard library only; Windows and macOS; no Codex or paid API.

macOS:
```sh
python3 decode_nk.py "/path/to/original/NK.BIN" --out decoded_new
python3 analyze_image.py decoded_new
```
Windows PowerShell:
```powershell
py -3 decode_nk.py "D:\NCDR\NK.BIN" --out decoded_new
py -3 analyze_image.py decoded_new
```
Resume an interrupted run with the same input and output:
```sh
python3 decode_nk.py "/path/to/NK.BIN" --out decoded_new --resume
```
Exit 0 means complete packet decoding with verified sizes/checksums and terminator at EOF; exit 2 means partial/errors. Never overwrite the input. A changed input hash prevents resuming. Successful packet files and partial failures survive; exact error offsets are in decode_report.json. Original offsets and addresses in CSV/JSON are decimal integers; convert with hex() when needed.

Included `decoded/` is the actual full run, not a test fixture. It contains independently checksummed packet files, a single addressed image, and explicit hole/coverage metadata. Holes in addressed_image.bin are filled with zero for storage only: do not interpret them as recovered original bytes. The source NK.BIN is deliberately excluded from the ZIP; use the pinned original identified in FORMAT_RULES.md. No module executable has yet been reconstructed.
