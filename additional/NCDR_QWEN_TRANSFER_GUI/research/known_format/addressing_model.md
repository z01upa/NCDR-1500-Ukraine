# Addressing model

The first four bytes self-identify every record as `uint24_be sector_id + uint8 physical_span`. `sector_id × 512` equals its physical file offset across the validated chain. This directly validates a 512-byte BL_ADDR variant for this DB. No independent 0x800 logical reference mapping was established here; treating each current sector ID as a published 0x800 page number would produce wrong physical offsets.
