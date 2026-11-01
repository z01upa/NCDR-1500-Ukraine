# Невирішені питання

Цей файл зводить відкриті залежності зі збережених звітів; він не є новим результатом реверс-інжинірингу.

## Формат карти й нові ребра

- **UNVERIFIED:** чи потрібні для нового ребра записи Section 6, 7 або 8, і як виклик передає ідентифікатор ребра в споживач.
- **UNVERIFIED:** чи нульовий збіг у Section 7/8 приймається, чи викликає fallback або помилку.
- **UNVERIFIED:** чи потрібні Section 9 записи для нового ребра, хоча у вихідному блоці їх немає.
- **UNVERIFIED:** семантика routing-атрибутів Section 5, напрямок, вартість, клас дороги, індекси відхилення/масок і безпечна перенумерація суміжностей.
- **UNVERIFIED:** залежності файлів EUZ.RT та EUZ.RL від Section 5 і нової геометрії.
- **UNVERIFIED:** сумісність експериментального MP0 з пристроєм, включно з перевірками завантажувача й повним читанням файлової системи.

## Прошивка й адреси

- **UNVERIFIED:** позитивний контроль Windows CE ROM потрібен для тлумачення кандидатних записів LK841 та зіставлення адрес із байтовими діапазонами.
- **UNVERIFIED:** структура ROMHDR/TOC і VA-to-file mapping для NK.BIN не відновлені; модулі NavigationRem.dll та nmicore_ce.dll не вилучені валідованим способом.
- **UNVERIFIED:** власник маршрутизації, GUID/service identities та фактичний шлях читання Section 4/5 не встановлені.

## Середовище й походження

- У публікаційній копії історичні домашні шляхи замінено на `%USERPROFILE%`, `$HOME`, `${NCDR_SOURCE_ROOT}` або `${NCDR_WORK_ROOT}`. Першоджерела не входять у Git; для запуску скриптів задавайте `NCDR_SOURCE_ROOT` на своїй машині. Оригінали в цій локальній копії не змінювалися.

- У наданому `pyproject.toml` базові залежності порожні; окремі дослідницькі скрипти мають власні залежності (наприклад `pypcode==2.0.0`). Залежності всіх історичних запусків не були централізовані.
- Переданий комплект не містив `.git`, тому попередню Git-комітну історію з цього знімка відновити неможливо.
- **UNVERIFIED:** права на публікацію оригінальних файлів і похідних бінарних образів. Вони залишаються локально; не додавати до Git без підтвердження користувача.
- GitHub remote, push і clone-перевірка очікують на GitHub CLI, Git LFS та HTTPS-авторизацію.

## Додатковий NCDR-том

- [Вибірка матеріалів і їх походження](CRZ_VOLUME_IMPORT.md): 570 нових файлів пройшли SHA-256 дедуплікацію. Додатковий аудит не відтворювався; його твердження лишаються історичними.
- Для зовнішнього пакета кілька файлів з персональними локальними шляхами або можливим персональним ідентифікатором вилучені з копії; список збережений лише в локальному ігнорованому маніфесті.
- У знайдених вихідних копіях є 16 записів `DB_0`, у тому числі окремий OUTPUT_C варіант іншого розміру. Публікація будь-яких таких файлів очікує підтвердження прав; лише два примірники хешовані для окремих записів у локальному списку.
- Матеріали стороннього AI review і prompt-файли не включені як підтверджені дослідження.
- Права на публікацію оригінальних карт/firmware та похідних бінарних корпусів не підтверджені. Вони залишаються поза Git; перелік і причини наведено в [DEFERRED_MATERIALS.md](DEFERRED_MATERIALS.md).

## Routing evidence updates (bounded, 2026-10-30)

- **CONFIRMED locally:** the `0x0308C1F0` selected-bit result skips the current packed candidate in its traced caller. This does not establish a global road ban, route cost, travel direction, or hardware behavior. See [v47 evidence](../research/geometry_breakthrough/cover_routing_v47/EVIDENCE.md).
- **UNKNOWN:** meaning/domain of the context-derived selector; producers and semantics of the separate `0x34` and `0x58` tables; targets and bodies of callbacks at `context+0x3C/+0x40`; semantics of output at `context+0x4C`.
- **UNKNOWN:** whether Section 7 or Section 8 is required, optional, or accepted empty; the upper caller of `0x01000E2C` was not identified in Astra-022's bounded search. Do not label either table REQUIRED/OPTIONAL.
- **NOT VERIFIED:** complete route search, real-device execution, or acceptance by the navigation application. Original maps, firmware, recovered section images, and raw replay traces remain withheld.
- See focused [routing XREFs](../research/geometry_breakthrough/cover_routing_v47/ROUTING_XREF_INDEX.md), [callback relationships](../research/geometry_breakthrough/cover_routing_v47/CALLBACK_TARGETS.md), and [Section 7/8 consumer status](../research/geometry_breakthrough/cover_routing_v47/SECTION789_CONSUMERS.md).

## Джерела

- [Astra transfer handoff](TRANSFER_HANDOFF.md)
- [Перевірка Section 7/8/9 та залежностей edge706](../research/geometry_breakthrough/EDGE_DEPENDENCIES.md)
- [Невідомі gates незалежного валідатора](../research/geometry_breakthrough/independent_validator_v18/UNRESOLVED.md)
