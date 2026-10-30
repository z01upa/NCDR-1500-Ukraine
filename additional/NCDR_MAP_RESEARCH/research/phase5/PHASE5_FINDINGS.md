# Phase 5 findings

## Confirmed

All selected records successfully decoded by zlib from local byte 8.

## Strongly supported

The `000402xx` signatures form a compression family. Their decompressed payloads have repeatable byte distributions, but no candidate width was consistent enough to establish a layout.

## Hypotheses

Exact sector-ID matches are candidate links only. Coordinate hits are single-value candidates; no encoding matched three independent cities.

## Rejected / not established

No fixed-width record layout, cross-record reference scheme, coordinate transform, polyline encoding, or routing graph was confirmed. GeoJSON was not generated because georeferencing was not validated.
