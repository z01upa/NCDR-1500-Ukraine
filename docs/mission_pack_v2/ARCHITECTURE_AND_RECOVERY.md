# Архітектура автономного дослідження

## Глобальний автомат стану

`TASK_PROPOSED -> VALIDATING -> READY -> LEASED -> EXECUTING -> VERIFYING -> (DONE | REPAIR_NEEDED | WAITING_LOCAL | WAITING_CODEX_QUOTA | WAITING_EXTERNAL | FAILED_PERMANENT)`.

`REPAIR_NEEDED -> VERIFIED_CAPABILITY_SPEC -> LOCAL_QWEN_CODER_SANDBOX -> INDEPENDENT_TESTS -> (PROMOTE_AND_CHECKPOINT | LOCAL_FAILED) -> (CODEX_QUOTA_GATE | NEXT_LOCAL_TASK)`.

`READY=0 && GOALS_UNMET` завжди ініціює `planner_tick` за cooldown, навіть якщо останній виконавець нічого не робив. Система не повинна зайняти нескінченний цикл безпідставних задач: потрібні score, novelty hash, acceptance та evidence delta. Якщо немає змістовних задач, стан `WAITING_EXTERNAL` із причиною, альтернативами й повідомленням про потрібний доказ.

### Компоненти

- Windows Worker/Service: детермінований двигун, планувальник подій, SQLite, lock, lease, watchdog. Він працює без GUI та Codex; Ollama потрібна для планування/генерації, але checkpointed задачі та інші інструменти можуть тривати окремо.
- Director через Ollama `/api/chat` постійно закріплений за `qwen3.5:9b` і видає тільки структуровані пропозиції задач. Worker виконує перевірені інструменти; Director не виконує довільний shell, не змінює оригінали або стан DB.
- Local coder закріплений за `qwen2.5-coder:7b`. Він повертає обмежений diff для точно дозволених файлів. Будь-який код запускається лише в disposable sandbox; незалежні тестові файли визначають прийняття, а promotion перевіряє незмінність джерел і hash кандидата.
- Verifier: запускає інструментальні тести, independent reader/CRC/hash. Reviewer може допомогти, але ніякий текстовий PASS не замінює фактичний deterministic test.
- Capability Broker: спершу зберігає перевірювану специфікацію (reproducer, точний scope, очікування й незалежні тести), потім робить одну локальну спробу. Лише після записаної невдачі local tools або для критичної архітектури дозволено один Codex-виклик у межах денного й per-request бюджету. Rate-limit лишає задачу у `WAITING_CODEX_QUOTA` без циклічних спроб; локальна черга й дослідження тривають.
- Checkpoint: після кожного незалежно підтвердженого результату результат, checksum, evidence і наступний крок фіксуються у SQLite/артефакті. Після падіння Worker відновлюється з checkpoint; порожня черга викликає Director з novelty/backoff.
- Event bus: SQLite outbox/notifications + optional `TASKS/INBOX` і `RESULTS/NEW`. JSON файл спершу пишеться у temp і atomically перейменовується; транзакції/idempotency/digest запобігають дублюванню.
- Reporter: щоденний/тижневий/місячний snapshot з реального DB, evidence та artifacts, без дублювання статичного тексту.

## Тригери

- Task completed or failed -> Verifier -> Director if meaningful delta, else select next known task.
- Queue empty -> Director every 2-5 minutes з backoff; спершу продовження tasks з checkpoints.
- Runtime OOM -> rootcause task + streaming/shard plan + retry only after code/data change.
- Timeout -> ensure task is killed cleanly, checkpoint commit validation, separate batches, continue smaller scope.
- Tool missing -> перевірена capability specification -> локальна спроба -> незалежні acceptance tests; Codex only після обґрунтованої локальної невдачі.
- Codex quota/rate-limit -> `WAITING_CODEX_QUOTA`, збережена причина й денний бюджет; автоматичного retry немає, інші local lanes продовжують.
- Shutdown/reboot -> unfinished leases recovered with transaction check; stale PID not trusted.

## OSM: безпечний національний імпорт

1. З’ясуй поточний формат джерела. Для `.osm.pbf` використовуй streaming pyosmium/libosmium, для XML `iterparse` із `elem.clear()` за умови коректної обробки залежностей. Не завантажуй 112 млн вузлів у Python dict або DOM.
2. Перевір, чи немає JobObject/per-process memory cap (OOM може виникати навіть за вільної загальної RAM).
3. Попередня обробка: багатопрохідне збирання потрібних node IDs/ways/relations або дискова індексація. Обробка по географічних shards має зберігати повноту ways, які перетинають межі, та залежності relations.
4. Використовуй покроковий профіль пам’яті; спочатку невелика область, далі кілька областей, лише потім національний імпорт.
5. Шарди записуй у `work/osm/staging/TILE_ID.tmp`, `fsync` за потреби, checksum, перейменовуй у `TILE_ID.done` тільки після незалежного verify. Resume не повинен повторювати вже завершені тайли.
6. Уникай беззмістовного зменшення timeout і неконтрольованого його збільшення. Timebox окремого shard, heartbeat після checkpoint, поділ shard за потреби.
7. Обмеження RAM, disk, temp files, GPU, watchdog і автовідновлення перевіряються під навантаженням.

## Справжній реверс-інжиніринг

Локальна модель не «знає» формат файлу із суфікса. Будь-яка гіпотеза повинна пройти: byte offsets -> контрольні файли -> незалежний декодер/парсер -> контрприклад -> запис у verified evidence.

Пріоритет - дослідження коду firmware, який розкриває алгоритми роботи з таблицями, а не безкінечне сканування 20KB вікон. До повного формату MP0 решту доведених відомостей не поширювати.

## Codex без людського чергування

Codex CLI `codex exec --sandbox workspace-write` не є штатним рушієм. Заявка дозволена лише після локального failure evidence чи позначеної critical architecture, з денним бюджетом і одним викликом на request. Rate-limit checkpoint-иться у `WAITING_CODEX_QUOTA` до наступної UTC доби. Кожен запит має failing log, reproducer, narrow scope, acceptance tests та output path. Оригінальні диски ніколи не відкриваються на запис, токени не логуються.

## Автозапуск та нагляд

Windows Task Scheduler `ONLOGON` для user-mode Ollama і Worker, `ONSTART` якщо сервісна конфігурація коректно протестована. Перевір те, що завдання реально виконується з робочою директорією, профілем та доступом до моделей. Watchdog може перезапускати Worker, але не створює другий процес. GUI не відповідає за життєвий цикл Worker.
