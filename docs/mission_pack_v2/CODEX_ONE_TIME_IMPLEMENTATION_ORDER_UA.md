# ОДНОРАЗОВЕ ЗАВДАННЯ ДЛЯ CODEX: NCDR AUTONOMOUS LAB 2.0

ЦЕ НЕ ЗАВДАННЯ НА ЧЕРГОВИЙ ЗВІТ. ЦЕ ЗАВДАННЯ НА РЕАЛЬНУ ЗМІНУ ДІЮЧОЇ WINDOWS-СИСТЕМИ З ПРОХОДЖЕННЯМ E2E ТЕСТІВ.

## Вихідна мета

Створити фізично працездатний навігаційний диск з актуальною картою України, українськими топонімами якщо дозволяє пристрій, для точно визначеної штатної навігації Opel NCDR. Для цього розшифрувати реальні формати CD_7185/7186/7190, написати reader/writer, конвертувати перевірений OSM-набір і зібрати валідний образ. Останній статус COMPLETE виключно після фізичного приймання.

## Що Codex робить ПЕРШИМ (один раз)

1. Прочитай усі файли цього пакета, зокрема `plans/task_backlog.json`, `ARCHITECTURE_AND_RECOVERY.md`, `tests/ACCEPTANCE_TEST_PLAN.md`.
2. Знайди поточний установленний NCDR Autonomous Research Manager, активний репозиторій та checkpoint-и. Виявляй шляхи з реального оточення, а не припускай, що старий проект у ZIP актуальний. Оригінальні джерела `Desktop\crz\NCDR` мають бути read-only.
3. Зроби backup робочого проєкту та SQLite, git checkpoint. Перевір цілісність відновлення перед міграцією. Не перераховуй повторно хеші всіх 5600 файлів, якщо вони збігаються з маніфестом і метаданими.
4. Виправ реальну помилку `AUTO_OSM_NATIONAL_CONVERSION_01`: ParseError out of memory, можливий попередній timeout 3600s. Діагностуй точно, переведи PBF/XML ingest на streaming/shard/checkpoint, перевір повторний запуск без OOM. Не скидай completed partitions.
5. Реалізуй класичні компоненти Director, Execution Worker, Independent Verifier, Capability Gap Broker, Artifact Registry, Daily/Weekly/Monthly Reporter на базі поточного менеджера.
6. Бери глобальний план і готовність із SQLite, а локальній моделі передавай **тільки компактні витяги** із verified evidence і незавершених цілей. Не подавай їй весь 11-ГБ корпус чи всі журнали щотика.
7. Створи typed `tasks` і `results` file bridge: атомарні файли + одночасна транзакція з SQLite, єдина авторитетна база стану. Не давати LLM безпосередньо редагувати SQLite.
8. Коли pipeline потребує функції, якої немає у Worker, Director формує `CAPABILITY_REQUEST` зі scope, repro, expected behavior, acceptance; Broker автоматично викликає доступний Codex CLI (`codex exec`, мінімальні дозволи, sandbox worktree), приймає patch тільки через tests/review. За вичерпання ліміту залишає `WAITING_CODEX` і виконує інші задачі.
9. Впровадь task backlog з `plans/task_backlog.json`, але не вставляй дублікати виконаного. Імпорт є ідемпотентним, базується на canonical task IDs та verified evidence. `PROPOSED` не означає, що задача ще не виконана реально - спочатку reconcile.
10. На Windows створюй належний автозапуск Worker (Task Scheduler ONLOGON або service згідно з правами) з delayed retry, single-instance lock і watchdog. GUI повинен приєднуватись до worker, а не створювати другий процес. Після restart/kill Worker сам відновлює корисні завдання.
11. У разі `0 PENDING` Director мусить викликатися через planner tick (за наявності недосягнутих цілей), підбирати наступну перевірювану незалежну задачу, а не залишати Worker в `RUNNING/IDLE` назавжди.
12. У разі OOM/TIMEOUT/invalid script/відсутнього інструмента видавай діагностику, підзадачу виправлення, E2E retest і продовжуй з checkpoint. Retry без нових даних заборонено.
13. Не присвоюй % готовності з кількості `DONE`. Reader/writer readiness повинен рахуватися з доведених мінімальних семантичних функцій, а не з byte readback. Усю дискову сумісність зберігай як NOT_TESTED до фізичного тесту.
14. Прибери активні Virtual CID GUI та окремий POI editor із планування (архівувати, не видаляти). Залиш POI і routing як обов'язкові дискові дані.
15. Пріоритетні real-product deliverables: Ghidra/firmware I/O path -> decoder semantics -> minimal NCDx writer -> OSM Ukraine streaming IR -> minimal OSM-to-NCDx -> full candidate image -> physical acceptance. Паралелізуй OSM і NCDx там, де немає залежностей.

## Як працювати після цього

Основним безкоштовним Director є локальний `qwen3.5:9b` або інша встановлена модель, яка виграла **тест планування на реальному NCDx**. Supervisor незалежно перевіряє детермінованими тестами, модель не має права самостійно засвідчувати свої результати. Codex використовується як інженер лише за запитом із готовим repro. Одночасно у 8-ГБ VRAM не тримати кілька великих моделей.

## Обов'язкові тести перед твердженням «готово»

Виконай `tests/ACCEPTANCE_TEST_PLAN.md` на цільовому Windows 11. Покажи реальний повний цикл `EMPTY QUEUE -> DIRECTOR -> TASK -> EXECUTOR -> VERIFY -> NEXT TASK` на NCDx або OSM, включно з автоматичним capability request Codex. Перерви Windows Worker під час chunk-processing та доведи відновлення. Проведи окремий тест запуску після logon/restart. Запусти GUI. Надай робочий code commit, шлях до встановленої програми, артефакти, доказ проходження тестів.

**Не зупиняй роботу після створення README, тестових файлів, красивого Dashboard або чергових 100 DONE. Головна умова - продуктово корисні підтверджені артефакти та їх незалежне приймання.** Якщо лишилися об'єктивні зовнішні залежності, зафіксуй їх і продовжуй усі незалежні роботи. Не імітуй нескінченну роботу заради заповнення лічильника.
