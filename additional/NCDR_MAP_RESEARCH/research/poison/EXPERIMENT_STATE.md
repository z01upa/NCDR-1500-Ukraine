# POISoN controlled writer experiment

POISoN successfully opened the original CARiN DB_0 under Windows using GTK 2.14.7.

All experiments started independently from the same ORIGINAL database.

## ORIGINAL
Untouched source database.

## OUTPUT_A
POISoN opened ORIGINAL.
No POI was added, removed or edited.
1935 editable points were loaded.
POISoN performed:
- Attaching 1935 points
- Splitting by size
- Preparing lookup
- Allocating IDs for POI blocks
- Saving POI blocks
- Database saved

This is the no-edit writer control.

## OUTPUT_B
Fresh copy of ORIGINAL.
One point added:

longitude = 37.65432
latitude  = 55.12345

Editable point count changed:
1935 -> 1936

POISoN saved the database successfully.

## OUTPUT_C
Fresh copy of ORIGINAL.
Two points added:

point 1:
longitude = 37.65432
latitude  = 55.12345

point 2:
longitude = 37.75432
latitude  = 55.22345

Editable point count changed:
1935 -> 1937

POISoN saved the database successfully.

## Important

A, B and C are independent outputs from ORIGINAL.

Correct differential comparisons:

ORIGINAL vs OUTPUT_A
OUTPUT_A vs OUTPUT_B
OUTPUT_A vs OUTPUT_C
OUTPUT_B vs OUTPUT_C

Do not modify any of these files.
