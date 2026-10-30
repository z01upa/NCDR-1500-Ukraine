# Поточний звіт NCDR DB_0

- Оновлено UTC: 2026-10-24T13:17:34.573660+00:00
- Запуск: `c5f495efcd26_20261024_160522`
- Статус: **BLOCKED_ORACLE**
- Етап: `FINISHED`
- Що відбувається: The local model did not produce a valid allow-listed action after five bounded retries. No user prompt was shown.
- Лічильники етапу: `{"model_actions": 33, "report": "reports\\FINAL_REPORT.md", "unique_actions": 39}`

## Поточні результати

### Індекс DB_0

`{"compression02_errors": [], "compression02_valid": 16371, "counts": {"type_00_comp_00": 196, "type_00_comp_01": 5240, "type_00_comp_02": 3036, "type_01_comp_00": 701, "type_01_comp_02": 1312, "type_02_comp_00": 808, "type_02_comp_02": 1591, "type_03_comp_00": 767, "type_03_comp_02": 1878, "type_04_comp_00": 66, "type_04_comp_02": 4101, "type_06_comp_00": 4624, "type_06_comp_02": 809, "type_07_comp_00": 1, "type_08_comp_00": 44, "type_09_comp_00": 5241, "type_09_comp_02": 250, "type_0a_comp_02": 1, "type_0b_comp_00": 1, "type_0c_comp_02": 213, "type_0d_comp_02": 1, "type_0e_comp_02": 861, "type_0f_comp_02": 106, "type_10_comp_02": 542, "type_11_comp_02": 50, "type_13_comp_02": 1, "type_14_comp_00": 410, "type_14_comp_01": 156, "type_14_comp_02": 19, "type_15_comp_00": 2262, "type_15_comp_01": 1218, "type_15_comp_02": 394, "type_16_comp_00": 8799, "type_16_comp_01": 4922, "type_16_comp_02": 269, "type_17_comp_02": 672, "type_18_comp_00": 14, "type_1c_comp_00": 1698, "type_1c_comp_01": 264, "type_1c_comp_02": 245, "type_1d_comp_00": 102, "type_1d_comp_01": 60, "type_1d_comp_02": 17, "type_1e_comp_00": 30, "type_1e_comp_01": 15, "type_1e_comp_02": 3}, "record_count": 54010, "reused": false, "source_sha256": "c5f495efcd26a8bc49197c73b116fcbccf127a397e1d2751c1aa88a9ed8589ef", "source_size": 252521472}`

### Корпус доріг

`{"F_invariant_slots": 190036, "NZ_slots": 190548, "Z_slots": 1420, "coverage": {"RR": 91176, "RU": 11173, "UR": 11378, "UU": 114101}, "duplicate_owned_offsets": 480264, "invalid_brif": 0, "invalid_ch_idx": 0, "multi_object_roads": 384191, "nodes_multi_target": 0, "nodes_one_target": 8177, "owned_objects": 2045228, "physical_nodes": 8177, "ptr_mod32_distinct_by_target": 1, "readable_objects": 1208221, "readable_ptr_in_bounds": 1208221, "readable_targets": 3036, "roads": 1203497, "status": "BUILT", "targets_multi_node": 0, "targets_one_node": 8177, "transition_occurrences": 227828, "unique_physical_pairs": 15758, "unique_readable_slots": 191968}`

## Невирішені питання

Compression `0x01` потребує незалежного еталонного логічного буфера; геометрія доріг також не підтверджена.
Статистичні збіги та гіпотези моделі не вважаються декодером без структурної перевірки.
