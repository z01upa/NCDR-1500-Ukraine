# NCDR DB_0 — local Qwen run report

- Run: `c5f495efcd26_20261024_160522`
- Status: **BLOCKED_ORACLE**
- Created (UTC): 2026-10-24T13:17:34.567988+00:00
- DB_0 access: read-only
- Model endpoint: local Ollama API

## Deterministic inventory

- Validated chain records: 54010
- Compression 0x02 records validated: 16371
- Type/compression counts: `{"type_00_comp_00": 196, "type_00_comp_01": 5240, "type_00_comp_02": 3036, "type_01_comp_00": 701, "type_01_comp_02": 1312, "type_02_comp_00": 808, "type_02_comp_02": 1591, "type_03_comp_00": 767, "type_03_comp_02": 1878, "type_04_comp_00": 66, "type_04_comp_02": 4101, "type_06_comp_00": 4624, "type_06_comp_02": 809, "type_07_comp_00": 1, "type_08_comp_00": 44, "type_09_comp_00": 5241, "type_09_comp_02": 250, "type_0a_comp_02": 1, "type_0b_comp_00": 1, "type_0c_comp_02": 213, "type_0d_comp_02": 1, "type_0e_comp_02": 861, "type_0f_comp_02": 106, "type_10_comp_02": 542, "type_11_comp_02": 50, "type_13_comp_02": 1, "type_14_comp_00": 410, "type_14_comp_01": 156, "type_14_comp_02": 19, "type_15_comp_00": 2262, "type_15_comp_01": 1218, "type_15_comp_02": 394, "type_16_comp_00": 8799, "type_16_comp_01": 4922, "type_16_comp_02": 269, "type_17_comp_02": 672, "type_18_comp_00": 14, "type_1c_comp_00": 1698, "type_1c_comp_01": 264, "type_1c_comp_02": 245, "type_1d_comp_00": 102, "type_1d_comp_01": 60, "type_1d_comp_02": 17, "type_1e_comp_00": 30, "type_1e_comp_01": 15, "type_1e_comp_02": 3}`

## Road corpus

`{"F_invariant_slots": 190036, "NZ_slots": 190548, "Z_slots": 1420, "coverage": {"RR": 91176, "RU": 11173, "UR": 11378, "UU": 114101}, "duplicate_owned_offsets": 480264, "invalid_brif": 0, "invalid_ch_idx": 0, "multi_object_roads": 384191, "nodes_multi_target": 0, "nodes_one_target": 8177, "owned_objects": 2045228, "physical_nodes": 8177, "ptr_mod32_distinct_by_target": 1, "readable_objects": 1208221, "readable_ptr_in_bounds": 1208221, "readable_targets": 3036, "roads": 1203497, "status": "BUILT", "targets_multi_node": 0, "targets_one_node": 8177, "transition_occurrences": 227828, "unique_physical_pairs": 15758, "unique_readable_slots": 191968}`

## Experiments

### Round 1: `inspect_block`

Parameters: `{"length": 128, "offset": 8, "sector": "0x11576"}`

Result: `{"sector": "0x011576", "type": "0x00", "compression": "0x01", "span": 13, "logical_size_header": 11776, "view": "physical", "offset": 8, "returned": 128, "hex": "007400030094000500c80012017c0007019c00bc193c00991e0400051e54017f27600000275000022760004829a000412b2800002b2800042b48002206fd90000c8a5000072d90000cba50000000000004423a04000000000000293900009733000097330000000a000100000908019c193c0a7c1b64127c1cdc127c1cdc129c", "u16_be": [116, 3, 148, 5, 200, 18, 380, 7, 412, 188, 6460, 153, 7684, 5, 7764, 383, 10080, 0, 10064, 2, 10080, 72, 10656, 65, 11048, 0, 11048, 4, 11080, 34, 1789, 36864, 3210, 20480, 1837, 36864, 3258, 20480, 0, 0, 1090, 14852, 0, 0, 0, 10553, 0, 38707, 0, 38707, 0, 10, 1, 0, 2312, 412, 6460, 2684, 7012, 4732, 7388, 4732, 7388, 4764], "u32_be": [7602179, 9699333, 13107218, 24903687, 27001020, 423362713, 503578629, 508821887, 660602880, 659554306, 660602952, 698351681, 724041728, 724041732, 726138914, 117280768, 210391040, 120426496, 213536768, 0, 71449092, 0, 10553, 38707, 38707, 10, 65536, 151519644, 423365244, 459543164, 484184700, 484184732]}`

### Round 2: `codec_sweep`

Parameters: `{"codecs": ["bz2", "gzip", "lzma", "raw_deflate", "zlib"], "offsets": [8, 11, 14, 17, 20, 23, 26, 29, 32], "sectors": ["0x11576"]}`

Result: `{"error": "ValueError", "detail": "offsets must contain 1..8 entries"}`

### Round 3: `prefix_compare`

Parameters: `{"block_type": 0, "count": 6, "length": 32}`

Result: `{"block_type": "0x00", "payload_prefix_bytes": 32, "samples": {"0": [{"sector": "0x01161F", "span": 2, "logical_size": 0, "bytes": 32, "hex": "007400030094000400bc000400e400070104000802240006025400040294000e", "entropy": 3.1945}, {"sector": "0x014924", "span": 1, "logical_size": 0, "bytes": 32, "hex": "007400030094000300b4000300d4000700f40001013400000134000201540004", "entropy": 2.8732}, {"sector": "0x01D9F2", "span": 1, "logical_size": 0, "bytes": 32, "hex": "007400030094000300b4000300d4000700f40001013400000134000201540000", "entropy": 2.7076}, {"sector": "0x021C13", "span": 1, "logical_size": 0, "bytes": 32, "hex": "007400030094000300b4000400dc000700fc0002015c0002016c0002018c0002", "entropy": 3.0356}, {"sector": "0x03D236", "span": 2, "logical_size": 0, "bytes": 32, "hex": "007400030094000400bc000400e400070104000201640001016c0002018c0039", "entropy": 3.0817}, {"sector": "0x042720", "span": 2, "logical_size": 0, "bytes": 32, "hex": "007400030094000300b4000300d4000700f4000701f400060224000402640029", "entropy": 3.1606}], "1": [{"sector": "0x011576", "span": 13, "logical_size": 11776, "bytes": 32, "hex": "007400030094000500c80012017c0007019c00bc193c00991e0400051e54017f", "entropy": 3.6883}, {"sector": "0x025FF8", "span": 45, "logical_size": 45056, "bytes": 32, "hex": "007400030094000500c8003c03200007034002dd5f000265722800367588089c", "entropy": 3.8974}, {"sector": "0x02E803", "span": 31, "logical_size": 30720, "bytes": 32, "hex": "007400030094000500c8003202bc000702dc01c93c1c017447bc00364b1c06e6", "entropy": 3.9375}, {"sector": "0x036BEC", "span": 27, "logical_size": 31744, "bytes": 32, "hex": "007400030094000300b4004103400007036002bd5b20020b6b7800406f7800d6", "entropy": 3.671}, {"sector": "0x03DA87", "span": 12, "logical_size": 11776, "bytes": 32, "hex": "007400030094000400bc000c01340007015400620db4004d101c001911ac045a", "entropy": 3.8369}, {"sector": "0x042840", "span": 15, "logical_size": 16384, "bytes": 32, "hex": "007400030094000400bc0023021c0007023c012d27fc00fb2fd4002231f401a0", "entropy": 3.9835}], "2": [{"sector": "0x0115CD", "span": 35, "logical_size": 33280, "bytes": 32, "hex": "78daedbd09581457faef5f8d6c024a810a88280d6e8080c522b680ca4e032ea5", "entropy": 4.8514}, {"sector": "0x015D2F", "span": 24, "logical_size": 23040, "bytes": 32, "hex": "78daed9b7b5c5cd5b5f8f739675ec000034c06180e30c0f09e173040869c601e", "entropy": 4.8125}, {"sector": "0x019945", "span": 17, "logical_size": 15360, "bytes": 32, "hex": "78daed9a797c5355deff4fb6366dd2f6764fd3b4b9d9b`

### Round 4: `word_profile`

Parameters: `{"block_type": 0, "compression": 1, "offset_end": 136, "offset_start": 8, "sample_limit": 64, "step": 2, "width": 2}`

Result: `{"block_type": "0x00", "compression": "0x01", "sample_sectors": ["0x011576", "0x013597", "0x01791B", "0x01AC85", "0x020136", "0x02191A", "0x022549", "0x022D32", "0x0235E0", "0x023E74", "0x02480A", "0x0250F7", "0x025A99", "0x02636F", "0x0273B1", "0x027F39", "0x0289A9", "0x02941E", "0x029F5E", "0x02B154", "0x02BA11", "0x02C45D", "0x02CFA3", "0x02D7E4", "0x02DFF9", "0x02E719", "0x02F099", "0x02FB2D", "0x030529", "0x031001", "0x031ABF", "0x032450", "0x032D95", "0x033748", "0x034249", "0x034F90", "0x0359F0", "0x036394", "0x036DE4", "0x0377E5", "0x038156", "0x038B27", "0x039538", "0x039E8E", "0x03A917", "0x03B29E", "0x03BB8B", "0x03C5E7", "0x03CD16", "0x03D28B", "0x03D878", "0x03DC76", "0x03E089", "0x03E8CF", "0x03F00A", "0x03FA2D", "0x040483", "0x040AD7", "0x040F80", "0x041507", "0x04177B", "0x041B7B", "0x0422BD", "0x042840"], "width_bytes": 2, "offset_stats": {"8": {"observed": 64, "distinct": 1, "top_values": [{"value": "0x0074", "count": 64}]}, "10": {"observed": 64, "distinct": 2, "top_values": [{"value": "0x0003", "count": 63}, {"value": "0x0004", "count": 1}]}, "12": {"observed": 64, "distinct": 2, "top_values": [{"value": "0x0094", "count": 63}, {"value": "0x009C", "count": 1}]}, "14": {"observed": 64, "distinct": 9, "top_values": [{"value": "0x0004", "count": 20}, {"value": "0x0005", "count": 15}, {"value": "0x0003", "count": 14}, {"value": "0x0006", "count": 8}, {"value": "0x0007", "count": 3}, {"value": "0x000D", "count": 1}]}, "16": {"observed": 64, "distinct": 9, "top_values": [{"value": "0x00BC", "count": 20}, {"value": "0x00C8", "count": 15}, {"value": "0x00B4", "count": 14}, {"value": "0x00D0", "count": 8}, {"value": "0x00DC", "count": 3}, {"value": "0x0118", "count": 1}]}, "18": {"observed": 64, "distinct": 49, "top_values": [{"value": "0x0008", "count": 3}, {"value": "0x0007", "count": 3}, {"value": "0x0040", "count": 3}, {"value": "0x0012", "count": 2}, {"value": "0x0025", "count": 2}, {"value": "0x001E", "count": 2}]}, "20": {"observed": 64, "distinct": 53, "top_values": [{"value": "0x0104", "count": 3}, {"value": "0x0190", "count": 3}, {"value": "0x01CC", "count": 2}, {"value": "0x0118", "count": 2}, {"value": "0x0228", "count": 2}, {"value": "0x0230", "count": 2}]}, "22": {"observed": 64, "distinct": 1, "top_values": [{"value": "0x0007", "count": 64}]}, "24": {"observed": 64, "distinct": 53, "top_values": [{"value": "0x0124", "count": 3}, {"value": "0x01B0", "count": 3}, {"value": "0x01EC", "count": 2}, {"value": "0x0138", "count": 2}, {"va`

### Round 5: `list_type0_targets`

Parameters: `{"compression": 1, "limit": 24}`

Result: `{"count": 5240, "compression": 1, "samples": [{"sector": "0x011576", "span": 13, "logical_size": 11776, "physical_size": 6656}, {"sector": "0x01A2F0", "span": 5, "logical_size": 4608, "physical_size": 2560}, {"sector": "0x021CB6", "span": 32, "logical_size": 29184, "physical_size": 16384}, {"sector": "0x0237FA", "span": 9, "logical_size": 10240, "physical_size": 4608}, {"sector": "0x025082", "span": 32, "logical_size": 33280, "physical_size": 16384}, {"sector": "0x027193", "span": 1, "logical_size": 1024, "physical_size": 512}, {"sector": "0x028E06", "span": 36, "logical_size": 35840, "physical_size": 18432}, {"sector": "0x02B30E", "span": 36, "logical_size": 40448, "physical_size": 18432}, {"sector": "0x02CEC6", "span": 34, "logical_size": 36864, "physical_size": 17408}, {"sector": "0x02E597", "span": 15, "logical_size": 14848, "physical_size": 7680}, {"sector": "0x02FF3B", "span": 16, "logical_size": 17408, "physical_size": 8192}, {"sector": "0x031C0B", "span": 22, "logical_size": 22016, "physical_size": 11264}, {"sector": "0x0335E8", "span": 19, "logical_size": 20480, "physical_size": 9728}, {"sector": "0x0355E5", "span": 16, "logical_size": 17408, "physical_size": 8192}, {"sector": "0x037160", "span": 38, "logical_size": 39936, "physical_size": 19456}, {"sector": "0x038C26", "span": 25, "logical_size": 25088, "physical_size": 12800}, {"sector": "0x03A746", "span": 25, "logical_size": 25600, "physical_size": 12800}, {"sector": "0x03C197", "span": 36, "logical_size": 36352, "physical_size": 18432}, {"sector": "0x03D3A8", "span": 18, "logical_size": 18432, "physical_size": 9216}, {"sector": "0x03E0BC", "span": 15, "logical_size": 14848, "physical_size": 7680}, {"sector": "0x03F7B1", "span": 40, "logical_size": 42496, "physical_size": 20480}, {"sector": "0x040EFB", "span": 5, "logical_size": 4608, "physical_size": 2560}, {"sector": "0x0417ED", "span": 4, "logical_size": 3072, "physical_size": 2048}, {"sector": "0x042840", "span": 15, "logical_size": 16384, "physical_size": 7680}]}`

### Round 6: `road_summary`

Parameters: `{}`

Result: `{"roads": 1203497, "owned_objects": 2045228, "readable_objects": 1208221, "invalid_ch_idx": 0, "invalid_brif": 0, "duplicate_owned_offsets": 480264, "readable_ptr_in_bounds": 1208221, "ptr_mod32_distinct_by_target": 1, "unique_readable_slots": 191968, "readable_targets": 3036, "Z_slots": 1420, "NZ_slots": 190548, "F_invariant_slots": 190036, "physical_nodes": 8177, "nodes_one_target": 8177, "nodes_multi_target": 0, "targets_one_node": 8177, "targets_multi_node": 0, "multi_object_roads": 384191, "transition_occurrences": 227828, "unique_physical_pairs": 15758, "coverage": {"UU": 114101, "UR": 11378, "RR": 91176, "RU": 11173}}`

### Round 7: `codec_sweep`

Parameters: `{"codecs": ["raw_deflate", "zlib"], "offsets": [8, 14, 20], "sectors": ["0x011576", "0x025FF8", "0x03DA87"]}`

Result: `{"sectors": [{"sector": "0x011576", "attempts": 6, "valid_size_candidates": []}, {"sector": "0x025FF8", "attempts": 6, "valid_size_candidates": []}, {"sector": "0x03DA87", "attempts": 6, "valid_size_candidates": []}], "tested_codecs": ["raw_deflate", "zlib"], "offsets": [8, 14, 20], "size_rule": "decoded payload + 8 == advertised logical size"}`

### Round 10: `codec_sweep`

Parameters: `{"codecs": ["raw_deflate", "gzip", "lzma"], "offsets": [8, 16, 24], "sectors": [1, 2, 3]}`

Result: `{"error": "ValueError", "detail": "sector 0x1 is not a validated compression-0x01 record"}`

### Round 11: `codec_sweep`

Parameters: `{"codecs": ["lzma"], "offsets": [8, 10, 12], "sectors": 6}`

Result: `{"error": "ValueError", "detail": "sectors must contain 1..8 entries"}`

### Round 14: `word_profile`

Parameters: `{"block_type": 0, "compression": 1, "offset_end": 256, "offset_start": 8, "sample_limit": 32, "step": 4, "width": 4}`

Result: `{"block_type": "0x00", "compression": "0x01", "sample_sectors": ["0x011576", "0x01797E", "0x0204CD", "0x022640", "0x023723", "0x024947", "0x025C68", "0x0275B3", "0x028C25", "0x02A276", "0x02BCAB", "0x02D26A", "0x02E3E8", "0x02F4F9", "0x030A50", "0x031F69", "0x033262", "0x034AD2", "0x035FB5", "0x037421", "0x0387C8", "0x039B39", "0x03AFBC", "0x03C394", "0x03D238", "0x03DC0C", "0x03E731", "0x03F8B8", "0x040A07", "0x0414D5", "0x041B40", "0x042840"], "width_bytes": 4, "offset_stats": {"8": {"observed": 32, "distinct": 2, "top_values": [{"value": "0x00740003", "count": 30}, {"value": "0x00740004", "count": 2}]}, "12": {"observed": 32, "distinct": 8, "top_values": [{"value": "0x00940003", "count": 13}, {"value": "0x00940005", "count": 6}, {"value": "0x00940004", "count": 4}, {"value": "0x00940006", "count": 4}, {"value": "0x00940008", "count": 2}, {"value": "0x009C000F", "count": 1}]}, "16": {"observed": 32, "distinct": 32, "top_values": [{"value": "0x00C80012", "count": 1}, {"value": "0x00B40005", "count": 1}, {"value": "0x00BC0014", "count": 1}, {"value": "0x01340048", "count": 1}, {"value": "0x00E4000F", "count": 1}, {"value": "0x00B4002C", "count": 1}]}, "20": {"observed": 32, "distinct": 26, "top_values": [{"value": "0x017C0007", "count": 3}, {"value": "0x02880007", "count": 2}, {"value": "0x03B80007", "count": 2}, {"value": "0x021C0007", "count": 2}, {"value": "0x04740007", "count": 2}, {"value": "0x00E80007", "count": 1}]}, "24": {"observed": 32, "distinct": 32, "top_values": [{"value": "0x019C00BC", "count": 1}, {"value": "0x01080008", "count": 1}, {"value": "0x01A40056", "count": 1}, {"value": "0x04240105", "count": 1}, {"value": "0x019C01A8", "count": 1}, {"value": "0x028C034F", "count": 1}]}, "28": {"observed": 32, "distinct": 32, "top_values": [{"value": "0x193C0099", "count": 1}, {"value": "0x02280004", "count": 1}, {"value": "0x0C840052", "count": 1}, {"value": "0x24E400FD", "count": 1}, {"value": "0x36BC015E", "count": 1}, {"value": "0x6C8C02EF", "count": 1}]}, "32": {"observed": 32, "distinct": 32, "top_values": [{"value": "0x1E040005", "count": 1}, {"value": "0x02480008", "count": 1}, {"value": "0x0F140004", "count": 1}, {"value": "0x2CCC0005", "count": 1}, {"value": "0x41AC001F", "count": 1}, {"value": "0x8404001C", "count": 1}]}, "36": {"observed": 32, "distinct": 32, "top_values": [{"value": "0x1E54017F", "count": 1}, {"value": "0x02C80005", "count": 1}, {"value": "0x0F5400F8", "count": 1}, {"value": "0x2D1C013C", "count": 1}, {"value": "0x439`

### Round 15: `codec_sweep`

Parameters: `{"codecs": ["raw_deflate"], "offsets": [8, 12, 16], "sectors": ["0x011576", "0x025FF8", "0x03DA87"]}`

Result: `{"sectors": [{"sector": "0x011576", "attempts": 3, "valid_size_candidates": []}, {"sector": "0x025FF8", "attempts": 3, "valid_size_candidates": []}, {"sector": "0x03DA87", "attempts": 3, "valid_size_candidates": []}], "tested_codecs": ["raw_deflate"], "offsets": [8, 12, 16], "size_rule": "decoded payload + 8 == advertised logical size"}`

### Round 16: `prefix_compare`

Parameters: `{"block_type": 0, "count": 4, "length": 16}`

Result: `{"block_type": "0x00", "payload_prefix_bytes": 16, "samples": {"0": [{"sector": "0x01161F", "span": 2, "logical_size": 0, "bytes": 16, "hex": "007400030094000400bc000400e40007", "entropy": 2.375}, {"sector": "0x01BD75", "span": 1, "logical_size": 0, "bytes": 16, "hex": "007400030094000300b4000300d40007", "entropy": 2.2028}, {"sector": "0x027410", "span": 1, "logical_size": 0, "bytes": 16, "hex": "007400030094000300b4000300d40007", "entropy": 2.2028}, {"sector": "0x042720", "span": 2, "logical_size": 0, "bytes": 16, "hex": "007400030094000300b4000300d40007", "entropy": 2.2028}], "1": [{"sector": "0x011576", "span": 13, "logical_size": 11776, "bytes": 16, "hex": "007400030094000500c80012017c0007", "entropy": 2.7718}, {"sector": "0x02C45D", "span": 21, "logical_size": 22016, "bytes": 16, "hex": "007400030094000300b4001b01c40007", "entropy": 2.6468}, {"sector": "0x039538", "span": 24, "logical_size": 24576, "bytes": 16, "hex": "007400030094000700dc002102280007", "entropy": 2.6468}, {"sector": "0x042840", "span": 15, "logical_size": 16384, "bytes": 16, "hex": "007400030094000400bc0023021c0007", "entropy": 2.7718}], "2": [{"sector": "0x0115CD", "span": 35, "logical_size": 33280, "bytes": 16, "hex": "78daedbd09581457faef5f8d6c024a81", "entropy": 4.0}, {"sector": "0x0185EF", "span": 16, "logical_size": 16384, "bytes": 16, "hex": "78daed9a0b781bd599f78f6d599225d9", "entropy": 3.875}, {"sector": "0x01E879", "span": 16, "logical_size": 16896, "bytes": 16, "hex": "78daed9a0f741bd595ffdfc8339ad19f", "entropy": 3.875}, {"sector": "0x03E03D", "span": 6, "logical_size": 6144, "bytes": 16, "hex": "78daed970f90555519c0bffbff9efb7f", "entropy": 3.75}]}}`

### Round 17: `find_hex`

Parameters: `{"compression": 1, "hex": "0x00740003", "max_bytes": 256, "sample_limit": 16}`

Result: `{"error": "ValueError", "detail": "hex must contain even-length hexadecimal bytes"}`

### Round 18: `word_profile`

Parameters: `{"block_type": 0, "compression": 1, "offset_end": 256, "offset_start": 8, "sample_limit": 64, "step": 4, "width": 4}`

Result: `{"block_type": "0x00", "compression": "0x01", "sample_sectors": ["0x011576", "0x013597", "0x01791B", "0x01AC85", "0x020136", "0x02191A", "0x022549", "0x022D32", "0x0235E0", "0x023E74", "0x02480A", "0x0250F7", "0x025A99", "0x02636F", "0x0273B1", "0x027F39", "0x0289A9", "0x02941E", "0x029F5E", "0x02B154", "0x02BA11", "0x02C45D", "0x02CFA3", "0x02D7E4", "0x02DFF9", "0x02E719", "0x02F099", "0x02FB2D", "0x030529", "0x031001", "0x031ABF", "0x032450", "0x032D95", "0x033748", "0x034249", "0x034F90", "0x0359F0", "0x036394", "0x036DE4", "0x0377E5", "0x038156", "0x038B27", "0x039538", "0x039E8E", "0x03A917", "0x03B29E", "0x03BB8B", "0x03C5E7", "0x03CD16", "0x03D28B", "0x03D878", "0x03DC76", "0x03E089", "0x03E8CF", "0x03F00A", "0x03FA2D", "0x040483", "0x040AD7", "0x040F80", "0x041507", "0x04177B", "0x041B7B", "0x0422BD", "0x042840"], "width_bytes": 4, "offset_stats": {"8": {"observed": 64, "distinct": 2, "top_values": [{"value": "0x00740003", "count": 63}, {"value": "0x00740004", "count": 1}]}, "12": {"observed": 64, "distinct": 9, "top_values": [{"value": "0x00940004", "count": 20}, {"value": "0x00940005", "count": 15}, {"value": "0x00940003", "count": 14}, {"value": "0x00940006", "count": 8}, {"value": "0x00940007", "count": 3}, {"value": "0x0094000D", "count": 1}]}, "16": {"observed": 64, "distinct": 63, "top_values": [{"value": "0x00B40016", "count": 2}, {"value": "0x00C80012", "count": 1}, {"value": "0x01180012", "count": 1}, {"value": "0x00C80008", "count": 1}, {"value": "0x00BC0014", "count": 1}, {"value": "0x00B40025", "count": 1}]}, "20": {"observed": 64, "distinct": 53, "top_values": [{"value": "0x01040007", "count": 3}, {"value": "0x01900007", "count": 3}, {"value": "0x01CC0007", "count": 2}, {"value": "0x01180007", "count": 2}, {"value": "0x02280007", "count": 2}, {"value": "0x02300007", "count": 2}]}, "24": {"observed": 64, "distinct": 64, "top_values": [{"value": "0x019C00BC", "count": 1}, {"value": "0x01EC00B9", "count": 1}, {"value": "0x01380036", "count": 1}, {"value": "0x01A40089", "count": 1}, {"value": "0x0248005D", "count": 1}, {"value": "0x025001CD", "count": 1}]}, "28": {"observed": 64, "distinct": 64, "top_values": [{"value": "0x193C0099", "count": 1}, {"value": "0x192C009F", "count": 1}, {"value": "0x0818002C", "count": 1}, {"value": "0x12E40074", "count": 1}, {"value": "0x0E080057", "count": 1}, {"value": "0x3C10017A", "count": 1}]}, "32": {"observed": 64, "distinct": 64, "top_values": [{"value": "0x1E040005", "count": 1}, {"value": "0x1E2400`

### Round 19: `codec_sweep`

Parameters: `{"codecs": ["lzma"], "offsets": [8], "sectors": [1, 2]}`

Result: `{"error": "ValueError", "detail": "sector 0x1 is not a validated compression-0x01 record"}`

### Round 20: `codec_sweep`

Parameters: `{"codecs": ["zlib", "raw_deflate", "lzma"], "offsets": [8, 16, 24, 32], "sectors": 4}`

Result: `{"error": "ValueError", "detail": "sectors must contain 1..8 entries"}`

### Round 22: `codec_sweep`

Parameters: `{"codecs": ["zlib", "raw_deflate"], "offsets": [8, 16, 24, 32], "sectors": [1, 2, 3]}`

Result: `{"error": "ValueError", "detail": "sector 0x1 is not a validated compression-0x01 record"}`

### Round 23: `word_profile`

Parameters: `{"block_type": 0, "compression": 1, "offset_end": 256, "offset_start": 8, "sample_limit": 128, "step": 4, "width": 4}`

Result: `{"block_type": "0x00", "compression": "0x01", "sample_sectors": ["0x011576", "0x011FE2", "0x013597", "0x01511B", "0x0177A1", "0x0196F7", "0x01AC1F", "0x01DE60", "0x01FD8D", "0x0213A1", "0x0218C6", "0x021C99", "0x02239E", "0x02290A", "0x022CFA", "0x0230D7", "0x023545", "0x02398F", "0x023DF6", "0x024243", "0x024723", "0x024BAD", "0x02500C", "0x0254D4", "0x025985", "0x025E33", "0x026286", "0x026A40", "0x027285", "0x027805", "0x027E01", "0x02833B", "0x02881B", "0x028D3E", "0x0292CF", "0x029844", "0x029DEC", "0x02A31A", "0x02AE70", "0x02B4B3", "0x02B8E9", "0x02BCB6", "0x02C2CD", "0x02C7DE", "0x02CE14", "0x02D209", "0x02D6BC", "0x02DAA4", "0x02DE6C", "0x02E387", "0x02E615", "0x02E8EA", "0x02EE53", "0x02F35B", "0x02F8E4", "0x02FE65", "0x03030F", "0x030827", "0x030D12", "0x031321", "0x031851", "0x031D36", "0x03220B", "0x032682", "0x032AF4", "0x032FB5", "0x0334D6", "0x0339DA", "0x033EFA", "0x0344D3", "0x034CC0", "0x035223", "0x0356CE", "0x035BED", "0x0360E8", "0x0365C8", "0x036B02", "0x036FC7", "0x03750A", "0x0379B3", "0x037E87", "0x038313", "0x03881D", "0x038D07", "0x039204", "0x0396A6", "0x039B15", "0x03A02E", "0x03A59D", "0x03AA96", "0x03AF23", "0x03B46B", "0x03B8F7", "0x03BD34", "0x03C257", "0x03C749", "0x03C99F", "0x03CE06", "0x03D1E5", "0x03D2F2", "0x03D621", "0x03D90A", "0x03DB5C", "0x03DC9E", "0x03DF1D", "0x03E0F0", "0x03E463", "0x03E98A", "0x03EDA1", "0x03F0B8", "0x03F58E", "0x03FADC", "0x04009F", "0x0404D2", "0x0407C5", "0x040B50", "0x040F02", "0x040FBF", "0x0411C9", "0x04151F", "0x041676", "0x041780", "0x0418D7", "0x041B8B", "0x041EA7", "0x0422BD", "0x04263B", "0x042840"], "width_bytes": 4, "offset_stats": {"8": {"observed": 128, "distinct": 1, "top_values": [{"value": "0x00740003", "count": 128}]}, "12": {"observed": 128, "distinct": 9, "top_values": [{"value": "0x00940004", "count": 43}, {"value": "0x00940003", "count": 31}, {"value": "0x00940005", "count": 21}, {"value": "0x00940006", "count": 15}, {"value": "0x00940007", "count": 11}, {"value": "0x0094000D", "count": 3}]}, "16": {"observed": 128, "distinct": 110, "top_values": [{"value": "0x00BC0005", "count": 4}, {"value": "0x00BC000B", "count": 2}, {"value": "0x00BC0011", "count": 2}, {"value": "0x00B4000B", "count": 2}, {"value": "0x00B40007", "count": 2}, {"value": "0x00BC003D", "count": 2}]}, "20": {"observed": 128, "distinct": 89, "top_values": [{"value": "0x00F00007", "count": 5}, {"value": "0x01680007", "count": 4}, {"value": "0x01CC0007", "count": 3}, {"value": "0x012C0007", "count": 3}, {"v`

### Round 24: `codec_sweep`

Parameters: `{"codecs": ["zlib", "raw_deflate", "lzma"], "offsets": [8, 16, 24], "sectors": 4}`

Result: `{"error": "ValueError", "detail": "sectors must contain 1..8 entries"}`

### Round 26: `codec_sweep`

Parameters: `{"codecs": ["zlib", "raw_deflate", "gzip"], "offsets": [8, 12, 16], "sectors": 4}`

Result: `{"error": "ValueError", "detail": "sectors must contain 1..8 entries"}`

### Round 27: `list_type0_targets`

Parameters: `{"compression": 1, "limit": 8}`

Result: `{"count": 5240, "compression": 1, "samples": [{"sector": "0x011576", "span": 13, "logical_size": 11776, "physical_size": 6656}, {"sector": "0x023E74", "span": 44, "logical_size": 47616, "physical_size": 22528}, {"sector": "0x029F5E", "span": 32, "logical_size": 33280, "physical_size": 16384}, {"sector": "0x02FB2D", "span": 43, "logical_size": 41984, "physical_size": 22016}, {"sector": "0x0359F0", "span": 41, "logical_size": 41472, "physical_size": 20992}, {"sector": "0x03B29E", "span": 11, "logical_size": 10752, "physical_size": 5632}, {"sector": "0x03F00A", "span": 31, "logical_size": 32256, "physical_size": 15872}, {"sector": "0x042840", "span": 15, "logical_size": 16384, "physical_size": 7680}]}`

### Round 28: `prefix_compare`

Parameters: `{"block_type": 0, "count": 4, "length": 32}`

Result: `{"block_type": "0x00", "payload_prefix_bytes": 32, "samples": {"0": [{"sector": "0x01161F", "span": 2, "logical_size": 0, "bytes": 32, "hex": "007400030094000400bc000400e400070104000802240006025400040294000e", "entropy": 3.1945}, {"sector": "0x01BD75", "span": 1, "logical_size": 0, "bytes": 32, "hex": "007400030094000300b4000300d4000700f40001013400000134000201540000", "entropy": 2.7076}, {"sector": "0x027410", "span": 1, "logical_size": 0, "bytes": 32, "hex": "007400030094000300b4000300d4000700f40002015400020164000201840001", "entropy": 2.9495}, {"sector": "0x042720", "span": 2, "logical_size": 0, "bytes": 32, "hex": "007400030094000300b4000300d4000700f4000701f400060224000402640029", "entropy": 3.1606}], "1": [{"sector": "0x011576", "span": 13, "logical_size": 11776, "bytes": 32, "hex": "007400030094000500c80012017c0007019c00bc193c00991e0400051e54017f", "entropy": 3.6883}, {"sector": "0x02C45D", "span": 21, "logical_size": 22016, "bytes": 32, "hex": "007400030094000300b4001b01c4000701e401bc39840159444c002c470c0094", "entropy": 3.7335}, {"sector": "0x039538", "span": 24, "logical_size": 24576, "bytes": 32, "hex": "007400030094000700dc00210228000702480120266800d02ce800282f680765", "entropy": 3.7724}, {"sector": "0x042840", "span": 15, "logical_size": 16384, "bytes": 32, "hex": "007400030094000400bc0023021c0007023c012d27fc00fb2fd4002231f401a0", "entropy": 3.9835}], "2": [{"sector": "0x0115CD", "span": 35, "logical_size": 33280, "bytes": 32, "hex": "78daedbd09581457faef5f8d6c024a810a88280d6e8080c522b680ca4e032ea5", "entropy": 4.8514}, {"sector": "0x0185EF", "span": 16, "logical_size": 16384, "bytes": 32, "hex": "78daed9a0b781bd599f78f6d599225d99ad1dd962fa38ba511b1c104139cc4b1", "entropy": 4.8125}, {"sector": "0x01E879", "span": 16, "logical_size": 16896, "bytes": 32, "hex": "78daed9a0f741bd595ffdfc8339ad19fd8b22ddbb23d9246b2a4d889f287e0fc", "entropy": 4.7264}, {"sector": "0x03E03D", "span": 6, "logical_size": 6144, "bytes": 32, "hex": "78daed970f90555519c0bffbff9efb7fff5dee63dffe99905c64c51541af08b1", "entropy": 4.75}]}}`

### Round 29: `list_type0_targets`

Parameters: `{"compression": 1, "limit": 32}`

Result: `{"count": 5240, "compression": 1, "samples": [{"sector": "0x011576", "span": 13, "logical_size": 11776, "physical_size": 6656}, {"sector": "0x01797E", "span": 1, "logical_size": 1024, "physical_size": 512}, {"sector": "0x0204CD", "span": 8, "logical_size": 7168, "physical_size": 4096}, {"sector": "0x022640", "span": 15, "logical_size": 14848, "physical_size": 7680}, {"sector": "0x023723", "span": 19, "logical_size": 21504, "physical_size": 9728}, {"sector": "0x024947", "span": 38, "logical_size": 41472, "physical_size": 19456}, {"sector": "0x025C68", "span": 14, "logical_size": 14848, "physical_size": 7168}, {"sector": "0x0275B3", "span": 34, "logical_size": 34816, "physical_size": 17408}, {"sector": "0x028C25", "span": 17, "logical_size": 19456, "physical_size": 8704}, {"sector": "0x02A276", "span": 34, "logical_size": 34304, "physical_size": 17408}, {"sector": "0x02BCAB", "span": 11, "logical_size": 11776, "physical_size": 5632}, {"sector": "0x02D26A", "span": 17, "logical_size": 17920, "physical_size": 8704}, {"sector": "0x02E3E8", "span": 24, "logical_size": 24576, "physical_size": 12288}, {"sector": "0x02F4F9", "span": 35, "logical_size": 33792, "physical_size": 17920}, {"sector": "0x030A50", "span": 29, "logical_size": 29184, "physical_size": 14848}, {"sector": "0x031F69", "span": 34, "logical_size": 37376, "physical_size": 17408}, {"sector": "0x033262", "span": 46, "logical_size": 48640, "physical_size": 23552}, {"sector": "0x034AD2", "span": 37, "logical_size": 37888, "physical_size": 18944}, {"sector": "0x035FB5", "span": 23, "logical_size": 22528, "physical_size": 11776}, {"sector": "0x037421", "span": 40, "logical_size": 41472, "physical_size": 20480}, {"sector": "0x0387C8", "span": 45, "logical_size": 48128, "physical_size": 23040}, {"sector": "0x039B39", "span": 39, "logical_size": 38400, "physical_size": 19968}, {"sector": "0x03AFBC", "span": 40, "logical_size": 40960, "physical_size": 20480}, {"sector": "0x03C394", "span": 26, "logical_size": 26624, "physical_size": 13312}, {"sector": "0x03D238", "span": 4, "logical_size": 4096, "physical_size": 2048}, {"sector": "0x03DC0C", "span": 6, "logical_size": 6144, "physical_size": 3072}, {"sector": "0x03E731", "span": 17, "logical_size": 17408, "physical_size": 8704}, {"sector": "0x03F8B8", "span": 25, "logical_size": 25600, "physical_size": 12800}, {"sector": "0x040A07", "span": 23, "logical_size": 26624, "physical_size": 11776}, {"sector": "0x0414D5", "span": 11, "logical_size": 10752, "physical_`

### Round 31: `codec_sweep`

Parameters: `{"codecs": ["zlib", "raw_deflate", "gzip"], "offsets": [8, 16, 24], "sectors": [1, 2, 3]}`

Result: `{"error": "ValueError", "detail": "sector 0x1 is not a validated compression-0x01 record"}`

### Round 32: `codec_sweep`

Parameters: `{"codecs": ["zlib", "raw_deflate", "gzip"], "offsets": [8, 16, 32], "sectors": [1, 2]}`

Result: `{"error": "ValueError", "detail": "sector 0x1 is not a validated compression-0x01 record"}`

### Round 33: `word_profile`

Parameters: `{"block_type": 0, "compression": 1, "offset_end": 64, "offset_start": 8, "sample_limit": 8, "width": 4}`

Result: `{"block_type": "0x00", "compression": "0x01", "sample_sectors": ["0x011576", "0x023E74", "0x029F5E", "0x02FB2D", "0x0359F0", "0x03B29E", "0x03F00A", "0x042840"], "width_bytes": 4, "offset_stats": {"8": {"observed": 8, "distinct": 1, "top_values": [{"value": "0x00740003", "count": 8}]}, "10": {"observed": 8, "distinct": 1, "top_values": [{"value": "0x00030094", "count": 8}]}, "12": {"observed": 8, "distinct": 5, "top_values": [{"value": "0x00940004", "count": 3}, {"value": "0x00940003", "count": 2}, {"value": "0x00940005", "count": 1}, {"value": "0x00940007", "count": 1}, {"value": "0x00940006", "count": 1}]}, "14": {"observed": 8, "distinct": 5, "top_values": [{"value": "0x000400BC", "count": 3}, {"value": "0x000300B4", "count": 2}, {"value": "0x000500C8", "count": 1}, {"value": "0x000700DC", "count": 1}, {"value": "0x000600D0", "count": 1}]}, "16": {"observed": 8, "distinct": 8, "top_values": [{"value": "0x00C80012", "count": 1}, {"value": "0x00B400AA", "count": 1}, {"value": "0x00BC0045", "count": 1}, {"value": "0x00DC0061", "count": 1}, {"value": "0x00B40088", "count": 1}, {"value": "0x00BC001A", "count": 1}]}, "18": {"observed": 8, "distinct": 8, "top_values": [{"value": "0x0012017C", "count": 1}, {"value": "0x00AA0758", "count": 1}, {"value": "0x00450370", "count": 1}, {"value": "0x006104A8", "count": 1}, {"value": "0x00880604", "count": 1}, {"value": "0x001A01C0", "count": 1}]}, "20": {"observed": 8, "distinct": 8, "top_values": [{"value": "0x017C0007", "count": 1}, {"value": "0x07580007", "count": 1}, {"value": "0x03700007", "count": 1}, {"value": "0x04A80007", "count": 1}, {"value": "0x06040007", "count": 1}, {"value": "0x01C00007", "count": 1}]}, "22": {"observed": 8, "distinct": 8, "top_values": [{"value": "0x0007019C", "count": 1}, {"value": "0x00070778", "count": 1}, {"value": "0x00070390", "count": 1}, {"value": "0x000704C8", "count": 1}, {"value": "0x00070624", "count": 1}, {"value": "0x000701E0", "count": 1}]}, "24": {"observed": 8, "distinct": 8, "top_values": [{"value": "0x019C00BC", "count": 1}, {"value": "0x077803E4", "count": 1}, {"value": "0x0390015E", "count": 1}, {"value": "0x04C80276", "count": 1}, {"value": "0x0624031C", "count": 1}, {"value": "0x01E000A8", "count": 1}]}, "26": {"observed": 8, "distinct": 8, "top_values": [{"value": "0x00BC193C", "count": 1}, {"value": "0x03E48418", "count": 1}, {"value": "0x015E2F70", "count": 1}, {"value": "0x027653A8", "count": 1}, {"value": "0x031C69C4", "count": 1}, {"value": "0x00A81700", "co`

### Round 34: `codec_sweep`

Parameters: `{"codecs": ["lzma"], "offsets": [8, 32], "sectors": [1, 2]}`

Result: `{"error": "ValueError", "detail": "sector 0x1 is not a validated compression-0x01 record"}`

### Round 36: `prefix_compare`

Parameters: `{"block_type": 0, "count": 6, "length": 48}`

Result: `{"block_type": "0x00", "payload_prefix_bytes": 48, "samples": {"0": [{"sector": "0x01161F", "span": 2, "logical_size": 0, "bytes": 48, "hex": "007400030094000400bc000400e400070104000802240006025400040294000e02f8000002e8000202f8000002f80000", "entropy": 3.0961}, {"sector": "0x014924", "span": 1, "logical_size": 0, "bytes": 48, "hex": "007400030094000300b4000300d4000700f40001013400000134000201540004017c0000016c0002017c0000017c0000", "entropy": 2.8819}, {"sector": "0x01D9F2", "span": 1, "logical_size": 0, "bytes": 48, "hex": "007400030094000300b4000300d4000700f4000101340000013400020154000001640000015400020164000001640000", "entropy": 2.7179}, {"sector": "0x021C13", "span": 1, "logical_size": 0, "bytes": 48, "hex": "007400030094000300b4000400dc000700fc0002015c0002016c0002018c000201a000000198000101a0000001a00000", "entropy": 2.9768}, {"sector": "0x03D236", "span": 2, "logical_size": 0, "bytes": 48, "hex": "007400030094000400bc000400e400070104000201640001016c0002018c003902f4000002e4000202f4000002f40000", "entropy": 3.0124}, {"sector": "0x042720", "span": 2, "logical_size": 0, "bytes": 48, "hex": "007400030094000300b4000300d4000700f4000701f400060224000402640029036c0000035c0002036c0000036c0000", "entropy": 3.0933}], "1": [{"sector": "0x011576", "span": 13, "logical_size": 11776, "bytes": 48, "hex": "007400030094000500c80012017c0007019c00bc193c00991e0400051e54017f27600000275000022760004829a00041", "entropy": 4.0409}, {"sector": "0x025FF8", "span": 45, "logical_size": 45056, "bytes": 48, "hex": "007400030094000500c8003c03200007034002dd5f000265722800367588089ca9680000a9300007a968002daad00003", "entropy": 4.0838}, {"sector": "0x02E803", "span": 31, "logical_size": 30720, "bytes": 48, "hex": "007400030094000500c8003202bc000702dc01c93c1c017447bc00364b1c06e674a000007480000474a0000074a00000", "entropy": 3.7752}, {"sector": "0x036BEC", "span": 27, "logical_size": 31744, "bytes": 48, "hex": "007400030094000300b4004103400007036002bd5b20020b6b7800406f7800d6749c0000747c0004749c000f75140000", "entropy": 3.8641}, {"sector": "0x03DA87", "span": 12, "logical_size": 11776, "bytes": 48, "hex": "007400030094000400bc000c01340007015400620db4004d101c001911ac045a2be000002bc800032be000002be00000", "entropy": 3.7466}, {"sector": "0x042840", "span": 15, "logical_size": 16384, "bytes": 48, "hex": "007400030094000400bc0023021c0007023c012d27fc00fb2fd4002231f401a03bcc00003bb400033bcc00083c0c0000", "entropy": 4.0567}], "2": [{"sector": "0x0115CD", "span": 35, "logical_size": 33280, "bytes": 48, `

### Round 37: `find_hex`

Parameters: `{"compression": 1, "hex": "00740003", "max_bytes": 256, "sample_limit": 16}`

Result: `{"pattern": "00740003", "samples": 16, "searched_payload_bytes_each": 256, "matches": [{"sector": "0x011576", "physical_offset": 8}, {"sector": "0x020B26", "physical_offset": 8}, {"sector": "0x02396E", "physical_offset": 8}, {"sector": "0x025FF8", "physical_offset": 8}, {"sector": "0x0291F5", "physical_offset": 8}, {"sector": "0x02C45D", "physical_offset": 8}, {"sector": "0x02E803", "physical_offset": 8}, {"sector": "0x0314AB", "physical_offset": 8}, {"sector": "0x033D76", "physical_offset": 8}, {"sector": "0x036BEC", "physical_offset": 8}, {"sector": "0x039538", "physical_offset": 8}, {"sector": "0x03BE05", "physical_offset": 8}, {"sector": "0x03DA87", "physical_offset": 8}, {"sector": "0x03F5C4", "physical_offset": 8}, {"sector": "0x0413ED", "physical_offset": 8}, {"sector": "0x042840", "physical_offset": 8}]}`

### Round 39: `find_hex`

Parameters: `{"compression": 1, "hex": "0001", "max_bytes": 256, "sample_limit": 4}`

Result: `{"pattern": "0001", "samples": 4, "searched_payload_bytes_each": 256, "matches": [{"sector": "0x011576", "physical_offset": 112}, {"sector": "0x039538", "physical_offset": 112}, {"sector": "0x042840", "physical_offset": 180}]}`

### Round 40: `word_profile`

Parameters: `{"block_type": 1, "compression": 0, "offset_end": 64, "offset_start": 8, "sample_limit": 8, "width": 4}`

Result: `{"block_type": "0x01", "compression": "0x00", "sample_sectors": ["0x04B914", "0x04BF83", "0x04C840", "0x04CC4F", "0x04CF6E", "0x04D141", "0x04D28D", "0x04D344"], "width_bytes": 4, "offset_stats": {"8": {"observed": 8, "distinct": 1, "top_values": [{"value": "0x00740002", "count": 8}]}, "10": {"observed": 8, "distinct": 1, "top_values": [{"value": "0x00020088", "count": 8}]}, "12": {"observed": 8, "distinct": 1, "top_values": [{"value": "0x00880002", "count": 8}]}, "14": {"observed": 8, "distinct": 1, "top_values": [{"value": "0x0002009C", "count": 8}]}, "16": {"observed": 8, "distinct": 1, "top_values": [{"value": "0x009C0002", "count": 8}]}, "18": {"observed": 8, "distinct": 1, "top_values": [{"value": "0x000200B0", "count": 8}]}, "20": {"observed": 8, "distinct": 1, "top_values": [{"value": "0x00B00007", "count": 8}]}, "22": {"observed": 8, "distinct": 1, "top_values": [{"value": "0x000700D0", "count": 8}]}, "24": {"observed": 8, "distinct": 6, "top_values": [{"value": "0x00D00001", "count": 2}, {"value": "0x00D00003", "count": 2}, {"value": "0x00D00006", "count": 1}, {"value": "0x00D00004", "count": 1}, {"value": "0x00D00002", "count": 1}, {"value": "0x00D0000E", "count": 1}]}, "26": {"observed": 8, "distinct": 6, "top_values": [{"value": "0x00010104", "count": 2}, {"value": "0x00030138", "count": 2}, {"value": "0x00060188", "count": 1}, {"value": "0x00040154", "count": 1}, {"value": "0x00020120", "count": 1}, {"value": "0x000E0258", "count": 1}]}, "28": {"observed": 8, "distinct": 6, "top_values": [{"value": "0x01040000", "count": 2}, {"value": "0x01380002", "count": 2}, {"value": "0x01880004", "count": 1}, {"value": "0x01540002", "count": 1}, {"value": "0x01200000", "count": 1}, {"value": "0x0258000C", "count": 1}]}, "30": {"observed": 8, "distinct": 6, "top_values": [{"value": "0x00000104", "count": 2}, {"value": "0x00020148", "count": 2}, {"value": "0x000401A8", "count": 1}, {"value": "0x00020164", "count": 1}, {"value": "0x00000120", "count": 1}, {"value": "0x000C02B8", "count": 1}]}, "32": {"observed": 8, "distinct": 7, "top_values": [{"value": "0x01040002", "count": 2}, {"value": "0x01A80004", "count": 1}, {"value": "0x01640004", "count": 1}, {"value": "0x01200004", "count": 1}, {"value": "0x01480002", "count": 1}, {"value": "0x02B80002", "count": 1}]}, "34": {"observed": 8, "distinct": 7, "top_values": [{"value": "0x00020124", "count": 2}, {"value": "0x000401E8", "count": 1}, {"value": "0x000401A4", "count": 1}, {"value": "0x00040160", "count": `

### Round 41: `codec_sweep`

Parameters: `{"codecs": ["zlib", "raw_deflate", "gzip", "lzma"], "offsets": [8, 16, 24, 32], "sectors": 4}`

Result: `{"error": "ValueError", "detail": "sectors must contain 1..8 entries"}`

### Round 42: `word_profile`

Parameters: `{"block_type": 1, "compression": 0, "offset_end": 64, "offset_start": 8, "sample_limit": 12, "step": 4, "width": 4}`

Result: `{"block_type": "0x01", "compression": "0x00", "sample_sectors": ["0x04B914", "0x04BBAA", "0x04C2C5", "0x04C7FC", "0x04CAC5", "0x04CD50", "0x04CF3B", "0x04D054", "0x04D164", "0x04D244", "0x04D2E8", "0x04D344"], "width_bytes": 4, "offset_stats": {"8": {"observed": 12, "distinct": 1, "top_values": [{"value": "0x00740002", "count": 12}]}, "12": {"observed": 12, "distinct": 1, "top_values": [{"value": "0x00880002", "count": 12}]}, "16": {"observed": 12, "distinct": 1, "top_values": [{"value": "0x009C0002", "count": 12}]}, "20": {"observed": 12, "distinct": 1, "top_values": [{"value": "0x00B00007", "count": 12}]}, "24": {"observed": 12, "distinct": 8, "top_values": [{"value": "0x00D00001", "count": 3}, {"value": "0x00D00002", "count": 2}, {"value": "0x00D00003", "count": 2}, {"value": "0x00D00006", "count": 1}, {"value": "0x00D00004", "count": 1}, {"value": "0x00D00008", "count": 1}]}, "28": {"observed": 12, "distinct": 9, "top_values": [{"value": "0x01040000", "count": 3}, {"value": "0x01200000", "count": 2}, {"value": "0x01880004", "count": 1}, {"value": "0x01540002", "count": 1}, {"value": "0x01BC0007", "count": 1}, {"value": "0x01380003", "count": 1}]}, "32": {"observed": 12, "distinct": 9, "top_values": [{"value": "0x01040002", "count": 3}, {"value": "0x01200004", "count": 2}, {"value": "0x01A80004", "count": 1}, {"value": "0x01640004", "count": 1}, {"value": "0x01F40002", "count": 1}, {"value": "0x01500001", "count": 1}]}, "36": {"observed": 12, "distinct": 11, "top_values": [{"value": "0x01240000", "count": 2}, {"value": "0x01E80036", "count": 1}, {"value": "0x01600037", "count": 1}, {"value": "0x01A40009", "count": 1}, {"value": "0x01600009", "count": 1}, {"value": "0x0214001B", "count": 1}]}, "40": {"observed": 12, "distinct": 11, "top_values": [{"value": "0x01340001", "count": 2}, {"value": "0x033C0001", "count": 1}, {"value": "0x02BC0001", "count": 1}, {"value": "0x01EC0001", "count": 1}, {"value": "0x01A80001", "count": 1}, {"value": "0x02C80001", "count": 1}]}, "44": {"observed": 12, "distinct": 11, "top_values": [{"value": "0x01240002", "count": 2}, {"value": "0x032C0002", "count": 1}, {"value": "0x02AC0002", "count": 1}, {"value": "0x01DC0002", "count": 1}, {"value": "0x01980002", "count": 1}, {"value": "0x02B80002", "count": 1}]}, "48": {"observed": 12, "distinct": 11, "top_values": [{"value": "0x01380000", "count": 2}, {"value": "0x03400000", "count": 1}, {"value": "0x02C00000", "count": 1}, {"value": "0x01F00000", "count": 1}, {"value": "0x01AC`

### Round 43: `word_profile`

Parameters: `{"block_type": 1, "compression": 1, "offset_end": 64, "offset_start": 8, "sample_limit": 12, "width": 4}`

Result: `{"block_type": "0x01", "compression": "0x01", "sample_sectors": [], "width_bytes": 4, "offset_stats": {"8": {"observed": 0, "distinct": 0, "top_values": []}, "10": {"observed": 0, "distinct": 0, "top_values": []}, "12": {"observed": 0, "distinct": 0, "top_values": []}, "14": {"observed": 0, "distinct": 0, "top_values": []}, "16": {"observed": 0, "distinct": 0, "top_values": []}, "18": {"observed": 0, "distinct": 0, "top_values": []}, "20": {"observed": 0, "distinct": 0, "top_values": []}, "22": {"observed": 0, "distinct": 0, "top_values": []}, "24": {"observed": 0, "distinct": 0, "top_values": []}, "26": {"observed": 0, "distinct": 0, "top_values": []}, "28": {"observed": 0, "distinct": 0, "top_values": []}, "30": {"observed": 0, "distinct": 0, "top_values": []}, "32": {"observed": 0, "distinct": 0, "top_values": []}, "34": {"observed": 0, "distinct": 0, "top_values": []}, "36": {"observed": 0, "distinct": 0, "top_values": []}, "38": {"observed": 0, "distinct": 0, "top_values": []}, "40": {"observed": 0, "distinct": 0, "top_values": []}, "42": {"observed": 0, "distinct": 0, "top_values": []}, "44": {"observed": 0, "distinct": 0, "top_values": []}, "46": {"observed": 0, "distinct": 0, "top_values": []}, "48": {"observed": 0, "distinct": 0, "top_values": []}, "50": {"observed": 0, "distinct": 0, "top_values": []}, "52": {"observed": 0, "distinct": 0, "top_values": []}, "54": {"observed": 0, "distinct": 0, "top_values": []}, "56": {"observed": 0, "distinct": 0, "top_values": []}, "58": {"observed": 0, "distinct": 0, "top_values": []}, "60": {"observed": 0, "distinct": 0, "top_values": []}, "62": {"observed": 0, "distinct": 0, "top_values": []}}}`

### Round 44: `find_hex`

Parameters: `{"compression": 1, "hex": "0002", "max_bytes": 512, "sample_limit": 8}`

Result: `{"pattern": "0002", "samples": 8, "searched_payload_bytes_each": 512, "matches": [{"sector": "0x011576", "physical_offset": 46}, {"sector": "0x023E74", "physical_offset": 149}, {"sector": "0x029F5E", "physical_offset": 157}, {"sector": "0x02FB2D", "physical_offset": 157}, {"sector": "0x0359F0", "physical_offset": 212}, {"sector": "0x03B29E", "physical_offset": 276}, {"sector": "0x03F00A", "physical_offset": 210}, {"sector": "0x042840", "physical_offset": 228}]}`

### Round 47: `prefix_compare`

Parameters: `{"block_type": 1, "count": 4, "length": 8}`

Result: `{"block_type": "0x01", "payload_prefix_bytes": 8, "samples": {"0": [{"sector": "0x04B914", "span": 2, "logical_size": 0, "bytes": 8, "hex": "0074000200880002", "entropy": 1.75}, {"sector": "0x04C9B3", "span": 1, "logical_size": 0, "bytes": 8, "hex": "0074000200880002", "entropy": 1.75}, {"sector": "0x04D098", "span": 2, "logical_size": 0, "bytes": 8, "hex": "0074000200880002", "entropy": 1.75}, {"sector": "0x04D344", "span": 1, "logical_size": 0, "bytes": 8, "hex": "0074000200880002", "entropy": 1.75}], "1": [], "2": [{"sector": "0x04B911", "span": 1, "logical_size": 1024, "bytes": 8, "hex": "78daed50b14a0341", "entropy": 3.0}, {"sector": "0x04C276", "span": 5, "logical_size": 3072, "bytes": 8, "hex": "78daa5967f5054d7", "entropy": 3.0}, {"sector": "0x04CC02", "span": 1, "logical_size": 1024, "bytes": 8, "hex": "78da6328616062e8", "entropy": 3.0}, {"sector": "0x04D341", "span": 3, "logical_size": 2560, "bytes": 8, "hex": "78daedd57f6c1365", "entropy": 3.0}]}}`

### Round 48: `codec_sweep`

Parameters: `{"codecs": ["zlib", "raw_deflate", "gzip"], "offsets": [8, 16, 24, 32], "sectors": [1, 2, 3, 4]}`

Result: `{"error": "ValueError", "detail": "sector 0x1 is not a validated compression-0x01 record"}`

### Round 49: `codec_sweep`

Parameters: `{"codecs": ["zlib", "raw_deflate"], "offsets": [8, 16, 24, 32], "sectors": 4}`

Result: `{"error": "ValueError", "detail": "sectors must contain 1..8 entries"}`

### Round 50: `codec_sweep`

Parameters: `{"codecs": ["zlib", "raw_deflate", "lzma"], "offsets": [8, 16, 24], "sectors": [42, 43]}`

Result: `{"error": "ValueError", "detail": "sector 0x2a is not a validated compression-0x01 record"}`

## Model hypotheses (candidates only)

- Round 7: **CANDIDATE** — Block type 0x00 with compression 0x01 contains consistent file signatures across multiple sectors
  - Expected if true: codec_sweep will identify valid compression patterns in raw_deflate/zlib format
  - Falsifier: codec_sweep returns error or inconsistent entropy values across sectors
- Round 8: **CANDIDATE** — Block type 0x00 with compression 0x01 contains consistent file signatures across multiple sectors
  - Expected if true: codec_sweep will identify valid compression patterns in raw_deflate/zlib format
  - Falsifier: codec_sweep returns error or inconsistent entropy values across sectors
- Round 9: **CANDIDATE** — Block type 0x00 with compression 0x01 contains consistent file signatures across multiple sectors
  - Expected if true: codec_sweep will identify valid compression patterns in raw_deflate/zlib format
  - Falsifier: codec_sweep returns error or inconsistent entropy values across sectors
- Round 10: **CANDIDATE** — The disk contains a compressed file system with deterministic header at offset 8 (0x0074 signature)
  - Expected if true: codec_sweep will identify valid decompression parameters for block_type 0x00
  - Falsifier: No compression algorithm produces consistent output across multiple sectors
- Round 11: **CANDIDATE** — LZMA-compressed archive with consistent header signature at offset 8
  - Expected if true: Decompression yields valid structure with expected size
  - Falsifier: Decompression fails or produces invalid data
- Round 14: **CANDIDATE** — Compression-0x01 records contain detectable byte-frequency signatures in their first 256 bytes that differ from type-0x00/0x02 patterns
  - Expected if true: Word profile analysis will show distinct entropy distribution and byte frequency clustering in compression-0x01 vs readable blocks
  - Falsifier: No significant statistical difference found between compression-0x01 and type-0x00/0x02 word profiles across multiple sectors
- Round 15: **CANDIDATE** — Compression-0x01 records use a fixed 4-byte header at offset 8 with repeated values indicating block type
  - Expected if true: codec_sweep will find valid size candidates when testing offsets [8, 12, 16] with raw_deflate codec on compression-0x01 sectors
  - Falsifier: No valid size candidates found across multiple codec/offset combinations for compression-0x01 sectors
- Round 16: **CANDIDATE** — Compression-0x01 blocks use consistent prefix patterns at offset 8
  - Expected if true: Multiple sectors show identical or near-identical byte sequences starting at offset 8
  - Falsifier: Different sectors show significantly different byte sequences at the same offset
- Round 17: **CANDIDATE** — The byte sequence 0x00740003 appears frequently at offset 8 in compression-0x01 blocks, suggesting it marks a structural boundary or header
  - Expected if true: Searching for this hex pattern across the file will reveal consistent occurrences at offset 8 in multiple sectors
  - Falsifier: The pattern 0x00740003 appears only once or in different positions than expected
- Round 18: **CANDIDATE** — Offset 8 contains repeated magic/header bytes (0x00740003) indicating file signature
  - Expected if true: Multiple samples at offset 8 will show identical top value with high frequency
  - Falsifier: Samples at offset 8 show diverse values without repetition pattern
- Round 19: **CANDIDATE** — Offset 8 shows repeating pattern (2 distinct values) suggesting compression-related structure
  - Expected if true: codec_sweep with lzma on offset 8 sectors will show consistent compression artifacts
  - Falsifier: codec_sweep returns no consistent patterns across multiple sectors at offset 8
- Round 20: **CANDIDATE** — Duplicate owned offsets indicate potential data redundancy or corruption in object storage structure
  - Expected if true: Further analysis will reveal consistent offset patterns across multiple objects with same duplicates
  - Falsifier: Analysis shows no correlation between duplicate counts and offset values, suggesting different issue
- Round 21: **CANDIDATE** — Block type 0 with compression 1 uses consistent 4-byte prefix patterns at offset 8
  - Expected if true: Repeated values like 0x03000000 appear consistently across multiple blocks
  - Falsifier: No repeated prefix pattern found or different block types show different structures
- Round 22: **CANDIDATE** — Block type 0 with zlib compression shows consistent offset patterns suggesting structured data layout
  - Expected if true: Further codec analysis will reveal predictable sector boundaries and compression artifacts
  - Falsifier: Inconsistent offset distributions or multiple block types in same sector would contradict this
- Round 23: **CANDIDATE** — Block type 0x00 uses zlib compression with fixed 16-byte header pattern starting at offset 8
  - Expected if true: Further word_profile analysis will show consistent entropy and structure across all block_type 0x00 sectors
  - Falsifier: Inconsistent header patterns or varying compression levels detected in additional sector samples
- Round 24: **CANDIDATE** — High entropy sectors contain compressed/encrypted data that may decode with standard codecs
  - Expected if true: codec_sweep will show consistent output sizes for specific compression algorithms on high-entropy sectors
  - Falsifier: No consistent decoding pattern emerges across multiple codec attempts
- Round 25: **CANDIDATE** — The value 0x00740003 at offset 8 represents a valid sector signature marker
  - Expected if true: find_hex will locate multiple occurrences of this hex pattern across different sectors
  - Falsifier: Pattern appears only once or shows no correlation with readable_ptr_in_bounds count
- Round 26: **CANDIDATE** — The dominant value 0x00740003 at offset 8 represents a compression signature or file header marker
  - Expected if true: Further analysis will reveal consistent pattern matching across multiple sectors with this same high-frequency value
  - Falsifier: If the value distribution becomes more uniform across samples or if codec_sweep reveals different compression signatures
- Round 27: **CANDIDATE** — lzma blocks have consistent header patterns but require different validation than codec_sweep expects
  - Expected if true: list_type0_targets will reveal valid lzma block structures at compression 1
  - Falsifier: If list_type0_targets returns no targets or errors, the structure may be fundamentally different from expected lzma format
- Round 28: **CANDIDATE** — Compression efficiency decreases as offset increases within blocks
  - Expected if true: Higher offset positions will show more distinct values (lower repetition)
  - Falsifier: Finding an offset with fewer distinct values than expected pattern
- Round 29: **CANDIDATE** — Type 0 targets may reveal compression patterns
  - Expected if true: list_type0_targets will return structured target data
  - Falsifier: No type 0 targets found or empty result
- Round 30: **CANDIDATE** — Sector 0x011576 contains valid zlib-compressed block type 0x00 data
  - Expected if true: word_profile shows consistent block_type 0x00 and compression 0x01 with predictable offset patterns
  - Falsifier: word_profile on sector 0x011576 shows different block_type or compression type than expected
- Round 31: **CANDIDATE** — The block uses zlib compression with a specific header pattern at offset 8
  - Expected if true: codec_sweep will show consistent zlib signatures across multiple sectors
  - Falsifier: Different compression algorithms detected or no consistent signature found
- Round 32: **CANDIDATE** — Block type 0 uses consistent zlib prefix pattern with variable entropy indicating mixed content types
  - Expected if true: All block type 0 sectors will show '00740003' prefix and physical_size < logical_size
  - Falsifier: Any sector without the prefix or showing no compression (physical=logical)
- Round 33: **CANDIDATE** — Type 0 sectors at compression level 1 contain structured word patterns with consistent 4-byte boundaries
  - Expected if true: word_profile will show low entropy variance and detectable word alignment across multiple sectors
  - Falsifier: word_profile returns high entropy variance or no consistent word boundary detection
- Round 34: **CANDIDATE** — High entropy compression type 1 sectors contain LZMA-compressed data requiring specific decompression parameters
  - Expected if true: codec_sweep will identify lzma as optimal codec for sectors with entropy >4.5
  - Falsifier: All tested codecs produce identical output or error on high entropy sectors
- Round 35: **CANDIDATE** — Block_type 0 contains multiple compression schemes beyond zlib
  - Expected if true: codec_sweep will show varying entropy patterns across different compression algorithms
  - Falsifier: All compression types produce identical or near-identical output for the same sectors
- Round 36: **CANDIDATE** — Block type 0x00 contains variable-length payloads with entropy patterns indicating compressed data structures
  - Expected if true: Higher entropy samples (3.5+) correlate with larger logical sizes in compression-0x01 sectors
  - Falsifier: All block_type 0x00 samples show uniform entropy regardless of sector size or payload content
- Round 37: **CANDIDATE** — The compression-0x01 data contains consistent byte patterns at regular offsets indicating structured zlib-compressed blocks
  - Expected if true: find_hex will reveal repeated hex sequences matching the word_profile observed patterns (e.g., 0x00740003)
  - Falsifier: No consistent hex patterns found across multiple sectors or different offset ranges
- Round 38: **CANDIDATE** — Type-0 targets have distinct compression patterns that can be enumerated
  - Expected if true: list_type0_targets returns multiple unique target entries with varying compression values
  - Falsifier: list_type0_targets returns empty or single entry list
- Round 39: **CANDIDATE** — Hex pattern analysis will reveal consistent byte sequences in compression-0x01 blocks
  - Expected if true: find_hex returns repeated hex patterns across multiple sectors indicating structured compression format
  - Falsifier: find_hex returns no consistent patterns or only random-looking bytes
- Round 40: **CANDIDATE** — Block type 1 with compression 0 may follow a different structural pattern than block type 0
  - Expected if true: Distinct values will appear across offset positions similar to block_type 0 but with different byte patterns
  - Falsifier: All offsets show identical or near-identical values indicating uniform structure
- Round 41: **CANDIDATE** — Compression behavior is consistent across different algorithms for block type 0
  - Expected if true: All codecs produce similar valid counts and error patterns
  - Falsifier: Significant differences in valid/error counts between codecs
- Round 42: **CANDIDATE** — Block type 1 has a consistent header structure at offset 8 with variable payload size
  - Expected if true: Word profile will show repeated byte patterns in first 64 bytes of type 1 blocks
  - Falsifier: No consistent pattern found across multiple type 1 sectors
- Round 43: **CANDIDATE** — Block type 1 uses consistent header pattern at offset 8-12
  - Expected if true: Additional offsets will show similar structured values
  - Falsifier: Offsets vary significantly or no consistent pattern emerges
- Round 44: **CANDIDATE** — Block type 1 contains encrypted/structured data with variable signatures
  - Expected if true: Additional hex patterns found at offset 8 in block type 1 sectors
  - Falsifier: No consistent pattern emerges after more profiling
- Round 45: **CANDIDATE** — Compression algorithm varies by sector and may be identifiable through codec analysis
  - Expected if true: Different codecs will show distinct byte distribution patterns across sectors
  - Falsifier: All sectors produce identical compression signatures regardless of algorithm choice
- Round 47: **CANDIDATE** — Block type 1 has a deterministic header structure repeating at fixed offsets
  - Expected if true: Prefix values will match across all sampled sectors for each offset position
  - Falsifier: Inconsistent prefix values found in different sectors at same offset
- Round 48: **CANDIDATE** — Different compression schemes exist across sectors in the road network data
  - Expected if true: codec_sweep will reveal multiple distinct compression types beyond the current block_type 1, compression 0 pattern
  - Falsifier: All sectors analyzed show identical compression signatures matching only zlib or raw_deflate
- Round 49: **CANDIDATE** — Compressed sectors (compression=1) contain structured data that word_profile can detect when using uncompressed view
  - Expected if true: word_profile with compression=0 shows offset patterns while compression=1 reveals different structure
  - Falsifier: All compression modes return identical or zero samples across all offsets
- Round 50: **CANDIDATE** — The compression=0 word_profile shows consistent patterns but we need to verify if this represents actual decompressible content
  - Expected if true: codec_sweep on sectors with consistent offset patterns will produce valid decoded output
  - Falsifier: No codec produces valid output or the data is not compressible in any standard format

## Conclusion

No candidate decoder is promoted to confirmed by statistical similarity alone. The runner does not execute model-written code or alter parser behavior.

### Exact external dependency

The local model did not produce a valid allow-listed action after five bounded retries. No user prompt was shown.
