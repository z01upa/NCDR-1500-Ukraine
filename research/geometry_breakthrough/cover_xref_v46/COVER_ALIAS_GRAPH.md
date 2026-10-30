# COVER ALIAS GRAPH

```text
Section 5 record bytes +4/+5
  ├─ 0x02FFB92C, r4=packed (block<<12)|edge, r5=cover output
  └─ 0x02FFBB00, same two-byte placement convention
       0x02FFB936 r10=r4; 0x02FFB938 r8=r5
       0x02FFB9D0 stores edge+5 → [r8+0x11]
       0x02FFB9D6 stores edge+4 → [r8+0x10] in bt/s delay slot
       0x02FFBB0A r10=r4; 0x02FFBB0C r8=r5; equivalent pair stores at
       0x02FFBB84 and delay-slot 0x02FFBB8A; its bit13 branch is at 0x02FFBB82.
       0x02FFB9BE loads first edge u32; 0x02FFB9C4 shifts right 13;
       0x02FFB9CA masks bit0; 0x02FFB9CC compares; 0x02FFB9D4 bt/s
       if bit13=1, branch to 0x02FFBA06 and 0x02FFBA0C stores -2 at [r8+0x18].
       This branch condition is bit13 of the first u32, not edge+4.

Proven real alias (`0x0306F484`):

```text
0x0306F538 (delay) r5 = SP+0x40
0x0306F536 jsr producer 0x02FFB92C, r4 is selected packed ID
producer writes stack object [SP+0x40]+0x10/+0x11
0x0306F542 loads consumer output address SP+0x40 into r4
0x0306F54A sets selector r6=r11; r5=SP+0xA8 node candidate
0x0306F54C jsr 0x0308C1F0
0x0308C1FE–0x0308C202 calls 0x0301EFE4 with cover ptr and node ptr
0x0308C206 adds 0x10 to cover; 0x0308C208 reads cover[0x10+selector]
0x0308C210 builds (1 << selector); 0x0308C212 tests that bit against byte
0x0308C214 bf/s and 0x0308C216 delay slot produce -1 on bit set, else 0
caller 0x0306F550–0x0306F556 maps this to -1/reject or 0/success
```

`0x0301EFE4` compares the node candidate's words at +4/+8/+12 with cover words +0x1C/+0x20/+0x24 and returns slot 0 when equal, slot 1 otherwise. Replay used a real Section 5 edge and executed this routine and `0x0308C1F0` without callback stubs.

Separate producer path: `0x0301FCD8` writes an attribute pair to a separately allocated object at `context+0x4C`; `0x0301F984` passes that pointer as `r4` to callback pointers at `context+0x3C` and `+0x40`. This establishes alias to the 0x301FCD8-produced object only. Callback bodies are indirect and their reads of +0x10/+0x11 are not established. It is not the SP+0x40 buffer from `0x02FFB92C`.

Literal `0x0301FAD4` resolves to `0x03060D48`; at `0x0301F978–0x0301F97E` it receives the `context+0x4C` temporary as r4 and the outer context as r5. `0x03060D48` compares coordinate/endpoint words, not attribute bytes +0x10/+0x11.

Candidate `0x02FD676C–0x02FD6884` reads byte `r9+4` at `0x02FD6826` as part of assembling a 32-bit value from `r9+4..+7`. No xref/call or def-use path aliases that `r9` object with either producer output in recovered evidence. Candidate remains unrelated/UNKNOWN, not a consumer proof.
