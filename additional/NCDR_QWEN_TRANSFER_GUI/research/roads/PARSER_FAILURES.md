# Deterministic road-parser status

The confirmed Moscow control and the ten confirmed non-Moscow header-LIST controls pass with the same parser implementation. The parser does not yet enumerate global 0x0F CH_IDX road-list links, so it cannot validly publish global ownership or a join percentage for the 10,615 reverse-reference rows.

The next implementation step is narrowly defined: add a structural 0x0F CH_IDX entry reader that validates the already-known 12-byte form (BL_ADDR to type-0x0E, one-byte key/flag, local LIST pointer/count), then feed only validated links to `parse_road_list`. No alternate BRIF, MORE_INFO, or object grammar is required.
