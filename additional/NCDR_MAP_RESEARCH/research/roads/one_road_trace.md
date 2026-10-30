# Isolated road trace

{
  "0F_sector": 6937,
  "logical_offset": 18960,
  "raw_ch_idx": "0031a01f31010f2000b90000",
  "key": "1",
  "index_flag": 1,
  "target_0E_sector": 12704,
  "target_span": 31,
  "target_type": "0x0e",
  "list_ptr_into_0E": 3872,
  "list_count": 185,
  "conclusion": "CH_IDX identifies a list inside the 0x0E block through its LIST ptr/count, not merely the block."
}

{
  "item_index": 0,
  "item_start_offset": 3872,
  "item_end_offset": 3880,
  "name_pointer": 37159,
  "name": "1 iy mikrorayon",
  "place_bitemask": 0,
  "language": 21,
  "region_pointer": 37175,
  "region": "matushkino savelki",
  "extended_info_ptr": 8094,
  "raw_hex": "9127001591371f9e"
}

Controls using the same parser:

[
  {
    "0F_offset": 18972,
    "0E_sector": 12735,
    "item_offset": 48,
    "name": "2 oy mikrorayon",
    "raw_hex": "5798001557a80ad0"
  },
  {
    "0F_offset": 19068,
    "0E_sector": 12760,
    "item_offset": 48,
    "name": "a. ulitsa kosmodem'yanskikh z. i",
    "raw_hex": "4d6c101500000740"
  },
  {
    "0F_offset": 19080,
    "0E_sector": 12783,
    "item_offset": 48,
    "name": "b afanas'evskiy pereulok",
    "raw_hex": "8f0c001500000f38"
  },
  {
    "0F_offset": 19104,
    "0E_sector": 12823,
    "item_offset": 48,
    "name": "d'yakovo gorodishche 1 ya ulitsa",
    "raw_hex": "6d2800156d490b48"
  },
  {
    "0F_offset": 19140,
    "0E_sector": 12854,
    "item_offset": 48,
    "name": "gabrichevskogo ulitsa",
    "raw_hex": "85281015853e0e18"
  }
]