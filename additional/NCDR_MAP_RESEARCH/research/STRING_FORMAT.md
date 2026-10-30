# String extraction and reference candidates

Raw strings are printable ASCII or bytes 0xa0–0xff runs of at least three bytes followed by a null terminator. Latin-1 output preserves every source byte; it is a display candidate, not an encoding claim. Decompressed strings use the same rule. Unterminated printable runs are not included in this conservative pass.

Reported 100000 strings (the conservative scan is capped at 100000 rows to prevent binary false-positive output from dominating the corpus): raw=1412, decompressed=98588. Raw regions join adjacent strings when the next starts within 2,048 bytes; this is a reporting heuristic, not a dictionary boundary.

Found 126639 page-pointer-plus-immediate-key candidates and 0 exact big-endian absolute-offset candidates. Neither representation is confirmed: repeated independent source/target validation is still required.
