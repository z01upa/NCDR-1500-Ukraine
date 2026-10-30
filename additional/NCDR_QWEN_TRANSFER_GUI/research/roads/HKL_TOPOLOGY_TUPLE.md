# raw32 topology tuple `+0x0E/+0x10/+0x12`

The authoritative 2,886-slot corpus contains 829 H values, 74 K values, 815 L
values, 1,449 HK pairs, 1,087 KL pairs, and 2,709 complete HKL tuples.

On 2,200 actual selected RR endpoint pairs, K equality remains the strongest
relation: 72.41% real versus 20.18% shuffled control. H equality is 7.73%
versus 0.82%; L equality is 0.18% versus 0.68%. HK/BE32 equality is 7.73%
versus 0.45%, while KL equality is 0.18% versus 0.64%. No tested cross-field
relation (H↔L, H↔K, K↔L) occurs in either real or control pairs.

Caller context improves deterministic neighbor mapping primarily by adding
road and sequence direction: `(target,ptr)` is 82.41%; adding road is 87.50%;
adding road and direction is 100%. A/B/C/D, F, or E flags add only about
0.35–0.46 percentage points to `(target,ptr)`. H/K/L have zero exact equality
with A/B/C/D/F/E fields. Their strongest correlations are weak: H vs E-flags
0.057, K vs E-flags 0.216, and L vs E-raw 0.193.

At nodes with multiple descriptors and neighbors, K is the best tested
neighbor selector, but only 119/272 mappings (43.75%) use one unique K. H is
38.24%, L 40.07%, HK 38.24%, KL 40.07%, and HKL 38.24%. For repeated physical
edges, K is also the most stable signature at 20/51 (39.22%).

Directional reuse again favors K: 23/26 bidirectional readable edges reuse a
canonical endpoint-K signature (88.46%). H is 10/26, L 13/26, HK 8/26, KL
12/26, and full HKL only 3/26. This supports K as a reused topology class;
H/L are caller-local indexing metadata rather than source/destination IDs.

## Decision

The tuple is topology class plus caller-local selector metadata. It does not
identify a physical edge or neighbor. The next bounded structure to inspect is
the immediately following raw32 words at `+0x14/+0x16`, conditioned on the
already-proven `(target,ptr,road,direction)` context.
