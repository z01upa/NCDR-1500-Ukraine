NCDR Qwen Research - відновлення запуску
========================================
1. Розпакуйте цей архів у будь-яку папку Windows 11.
2. Запустіть START_DIAGNOSIS.cmd подвійним клацанням.
3. На Робочому столі з'явиться папка NCDR_REPAIR_дата_час.
4. Якщо REPORT.json -> status = IMPORTS_PASS_LAUNCHER_READY,
   запустіть START_NCDR_WITH_FIXED_PATH.cmd у створеній папці.
   Вона запустить оригінальний GUI з правильним PYTHONPATH і робочою папкою.
5. Якщо пакет або GUI не знайдений, надішліть сюди REPORT.json та,
   після перевірки на секрети, NCDR_SOURCE_FOR_FIX.zip.

Якщо проєкт не в стандартних папках:
   START_DIAGNOSIS.cmd --root "D:\MyProjects\NCDR_QWEN_TRANSFER_GUI"
Якщо GUI не вдалося визначити автоматично:
   START_DIAGNOSIS.cmd --root "D:\MyProjects\NCDR_QWEN_TRANSFER_GUI" --gui "D:\MyProjects\NCDR_QWEN_TRANSFER_GUI\mygui.exe"

Не потребує адміністратора. Нічого не встановлює. Не змінює вихідні файли.
Не запускає багаторазово падаючий runner. Не приховує відсутність модулів.

Важливо: це виправляє неправильний PYTHONPATH при наявних справних модулях.
Інші причини і збої самого GUI потребують виправлення його вихідного коду.
