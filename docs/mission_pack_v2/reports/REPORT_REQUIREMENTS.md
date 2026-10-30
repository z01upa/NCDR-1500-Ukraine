# Звіти та вимірювання

Окремо вести:
- research activity: tasks DONE, blocked, model calls, cost/time;
- format proof: нові семантичні структури з cross-disc independent validation;
- working code: decoder/writer/OSM importer tests і commit SHA;
- release readiness: gates G0-G5 та hardware status.

Daily: реальні нові семантичні факти, продуктово корисні артефакти, помилки/root cause, hardware dependencies, план на наступну добу.
Weekly: обсяг підтвердженого reader, writer, OSM, інтеграції, нові code changes/tests, нові blockers, evidence chain.
Monthly: порівняння з попереднім місяцем по прийнятих gates, ризики, hardware needs, контрольні хеші, конкретна дорога до диска.

Кожний звіт містить `generated_at`, `project_commit`, `db_checkpoint_sha`, `task_ids`, `artifact_paths/hashes`, `source_hashes`, `test_logs`, `claim_scope`, `unverified_items`.

Заборонено: зараховувати 564 DONE за 564 корисні відкриття або 35% UI за 35% готового диска.
