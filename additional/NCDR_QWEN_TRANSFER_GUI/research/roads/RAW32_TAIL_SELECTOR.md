# raw32 tail selector

The authoritative corpus contains 1,722 distinct M values, 93 distinct N
values, and 1,846 distinct MN composites. M is zero in 0.347% of slots and N
in 0.381%. Both are broad, mostly even, in-bounds byte values; no dereferenced
structure or pointer semantics is proven.

M/N do not identify opposite endpoints: M=M, N=N, MN=MN, M↔N, and all tested
K cross-relations have zero real matches on 2,200 RR transitions. N is instead
highly context-stable: 248/259 repeated directed edges (95.75%) and 26/26
bidirectional physical edges reuse the canonical endpoint N values. M is only
91/259 stable and 6/26 directionally reciprocal.

At multi-neighbor nodes, M yields 73.75% precision and 56.25% coverage; MN is
73.77%/56.25%; KM and KMN are 74.60%/56.62%. Full HKLMN reaches
82.25%/60.66%, but remains non-deterministic. No A/B/C/D/F/E-flags relation to
M or N is meaningful; the best rate is N-low-byte vs F at only 0.695%.

Screening O/P/Q/R identifies P as the best concrete selector candidate:
80.54% neighbor precision and 60.29% coverage. Adding K/M raises this only to
82.28%/60.66%; full HKLMNP is 82.40%/60.66%. P is not stable as an edge ID
(90/259 repeated directed edges, 34.75%). Q has the strongest endpoint
equality signal (34.55% real vs 17.64% control) but poor neighbor precision
(31.44%). O equality is nondiscriminative, and R is anti-correlated.

M/N and P have pointer-like numeric ranges, but no referenced local structure
is validated. Raw32 alone selects a neighbor only partially. Exact mapping
requires caller road and sequence direction; adding `(road_id,direction)` to
`(target,ptr)` gives 100%, whereas tested scalar caller fields do not.

## Decision

Raw32 distinguishes topology only together with caller metadata. The missing
selector is road-sequence direction, not A/B/C/D/F/E flags. The next exact
structure is the ordered predecessor/current/successor 24-byte object triple
inside each MORE_INFO-owned road array.
