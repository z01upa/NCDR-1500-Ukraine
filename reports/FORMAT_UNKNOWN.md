# Невідомі фрагменти формату

- Формат записів і таблиць після MP0 заголовка; структура `FEA`, `RD`, `MG1`–`MG3`, `RL`, `RT`, `CTY`, `IL`, `IOF` та інших суфіксів.
- Endianness і checksum для NCDx map records; індекси, routing graph, road geometry, addresses, POI і їхні взаємні посилання.
- Зв'язок ідентифікатора в заголовку MP0 з об'єктним форматом. Перевірено лише буквальний збіг регіону/версії з текстовим TOC.
- Фізична структура CD (трекове розташування, CD mode, boot/layout validation) для target NCDR.
- Відповідність трьох наявних дисків точній моделі штатного пристрою конкретного авто.
- Підтримка українських назв, кодова сторінка CID, голосові assets та hardware display mode.
- Поточна compatibility DB_0 ↔ NCDx; попередній звіт називає лише weak similarity під sampled probes.
