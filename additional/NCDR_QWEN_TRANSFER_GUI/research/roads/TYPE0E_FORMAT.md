# Type 0x0E road-entry layout

## Strongly supported

{
  "record_width": 8,
  "list_start": 3872,
  "list_count": 185,
  "fields": [
    "uint16_be PSTR name",
    "uint8 place_bitemask",
    "uint8 language",
    "uint16_be PSTR region",
    "uint16_be PTR extended_info"
  ],
  "validation": {
    "all_entries_in_bounds": true,
    "named_entries": 185,
    "extended_info_ptrs_in_bounds": 185,
    "example_names": [
      "1 iy mikrorayon",
      "1 maya ulitsa",
      "1 sel'skokhozyaystvenniy proezd",
      "1 y ambulatorniy proezd",
      "1 y arkhivniy pereulok",
      "1 y avtozavodskiy proezd",
      "1 y bab'egorodskiy pereulok",
      "1 y baltiyskiy pereulok",
      "1 y basmanniy pereulok",
      "1 y belokamenniy proezd"
    ]
  }
}

The extended-info target is only a block-local PTR at this stage; it has not been parsed as a FAR_LIST or attributed external ownership.
