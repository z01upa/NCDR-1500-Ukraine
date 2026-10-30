# Підтверджені фрагменти формату

## NCDx `*Z.MP0` заголовок (часткова специфікація)

Перевірено на повних оригінальних `EUZ.MP0`, `IZ.MP0`, `SCZ.MP0`; кожен повний файл перевірено SHA-256. Незалежні TOC-дані — CD_7190, CD_7185 та CD_7186.

| Offset | Байти/поле | Приклад | Висновок |
|---:|---|---|---|
| `0x00` | 13 ASCII байтів | `(*$SIEMENS&^)` | Спільний marker трьох MP0 файлів |
| `0x10` | NUL-terminated ASCII у 16 байтах | `Copyright 1998` | Видимий текстовий header field |
| `0x20` | NUL-terminated ASCII у 16 байтах | `2.0.0` | Видиме внутрішнє version field |
| `0x30` | NUL-terminated ASCII у 16 байтах | `EU44420940.82` | Регіональний dataset code; буквально зіставляється з TOC |

Parser перевіряє межі, кодування, marker і формат коду; він читає файл у `rb`, рахує його SHA-256 і нічого не змінює. Усі байти після цієї частини заголовка залишаються opaque.

## DB_0 (окрема, несумісність не припускається)

Попередні звіти й `research/FORMAT.md` підтверджують для конкретного DB_0: 512-байтові фізичні сектори; байти 0–2 — uint24 big-endian sector identifier; байт 3 — physical span; байти 4–7 мають BL_HEAD/alignment/type/compression/logical-size значення; compression 0x02 — zlib; MULCOORD для декодованих координат. Compression 0x01 має невирішені logical-buffer references.

Ця DB_0 специфікація не застосовується до `EUZ.*`, `IZ.*`, `SCZ.*`.
