"""Build the local, offline NCDR project dashboard from saved evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import html
import json
from pathlib import Path
import sqlite3

from src.agent import project_scope, readiness


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT.parents[1] / "outputs" / "ncdr-dashboard.html"
PROJECT_OUTPUT_PATH = PROJECT_ROOT / "dashboard.html"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def load_state() -> dict:
    state_path = PROJECT_ROOT / "project_state.sqlite"
    with closing(sqlite3.connect(state_path)) as conn:
        conn.row_factory = sqlite3.Row
        task_rows = [dict(row) for row in conn.execute("SELECT id,stage,status,verdict,agent,next_action,result_json,budget_json FROM tasks ORDER BY stage,priority,id")]
        tasks = [row for row in task_rows if not project_scope.task_is_excluded(row)]
        gates = [dict(row) for row in conn.execute("SELECT stage,status,criteria_json,proof_json,updated_utc FROM stage_gates ORDER BY stage")]
        counts: dict[str, int] = {}
        for row in tasks:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        evidence_count = conn.execute("SELECT count(*) FROM evidence").fetchone()[0]
        model_run_count = conn.execute("SELECT count(*) FROM model_runs").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    for task in tasks:
        task["result"] = json.loads(task.pop("result_json") or "{}")
    for gate in gates:
        gate["criteria"] = json.loads(gate.pop("criteria_json") or "{}")
        gate["proof"] = json.loads(gate.pop("proof_json") or "{}")
    return {"tasks": tasks, "gates": gates, "counts": counts, "evidence_count": evidence_count,
            "model_run_count": model_run_count, "integrity": integrity}


def load_inventory() -> tuple[dict, dict, dict]:
    verification = json.loads((PROJECT_ROOT / "inventory" / "hash_verification.json").read_text(encoding="utf-8"))
    manifest = json.loads((PROJECT_ROOT / "inventory" / "discs_manifest.json").read_text(encoding="utf-8-sig"))
    region = json.loads((PROJECT_ROOT / "inventory" / "region_cross_diff.json").read_text(encoding="utf-8"))
    groups: dict[str, int] = {}
    for row in manifest:
        group = row["relative_path"].split("\\", 1)[0]
        groups[group] = groups.get(group, 0) + 1
    return verification, groups, region


def load_benchmark() -> dict:
    path = PROJECT_ROOT / "reports" / "model_benchmark.json"
    if not path.exists():
        return {"status": "NOT_RUN", "models": [], "recommended_model": None}
    return json.loads(path.read_text(encoding="utf-8"))


def load_product_acceptance() -> dict:
    path = PROJECT_ROOT / "reports" / "product_acceptance.json"
    if not path.exists():
        return {"checks": {}, "tracks": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"checks": {}, "tracks": {}}


def earned_progress(gates: list[dict], product: dict | None = None, writer: dict | None = None) -> tuple[int, int]:
    result = readiness.calculate_readiness(gates, product=product, writer=writer)
    return result["earned"], result["total"]


def render_tasks(tasks: list[dict]) -> str:
    rows = []
    labels = {"DONE": "Виконано", "PENDING": "У черзі", "LEASED": "В роботі", "BLOCKED": "Заблоковано"}
    for task in tasks:
        rows.append(
            "<tr>"
            f"<td><code>{esc(task['id'])}</code><br><small>{esc(task['stage'])} · {esc(task['agent'])}</small></td>"
            f"<td><span class=\"status {esc(task['status'].lower())}\">{esc(labels.get(task['status'], task['status']))}</span></td>"
            f"<td>{esc(task['next_action'])}</td>"
            "</tr>"
        )
    return "".join(rows) or '<tr><td colspan="3">Черга ще порожня.</td></tr>'


def render_gate_rows(gates: list[dict], scores: dict[str, dict[str, int]]) -> str:
    rows = []
    for gate in gates:
        score = scores.get(gate["stage"], {})
        possible, earned = score.get("total", 0), score.get("earned", 0)
        if not possible:
            continue
        rows.append(f"<tr><td>{esc(gate['stage'])}</td><td>{esc(gate['status'])}</td><td>{earned} / {possible}</td></tr>")
    return "".join(rows) or '<tr><td colspan="3">Активних оцінюваних воріт ще немає.</td></tr>'


def render_models(benchmark: dict) -> str:
    rows = benchmark.get("models", [])
    if not rows:
        return '<p class="muted">Порівняльний прогін ще не збережений.</p>'
    items = []
    for row in rows:
        task_rows = []
        for task in row.get("tasks", []):
            status = "PASS" if task.get("pass") else task.get("status", "FAIL")
            result = task.get("result", {})
            short_result = json.dumps(result, ensure_ascii=False)[:300]
            task_rows.append(f"<tr><td><code>{esc(task.get('task_id',''))}</code></td><td>{esc(status)}</td><td>{esc(short_result)}</td></tr>")
        items.append(
            f"<details><summary><strong>{esc(row.get('model','?'))}</strong> — {int(row.get('passed',0))}/{int(row.get('task_count',0))} перевірених відповідей; "
            f"{esc(row.get('verified_results_per_minute','—'))} корисних/хв; VRAM peak {esc(row.get('peak_vram_used_mib','—'))} MiB</summary>"
            "<div class=\"table-wrap\"><table><thead><tr><th>Завдання</th><th>Оцінка</th><th>Короткий результат</th></tr></thead><tbody>"
            + "".join(task_rows) + "</tbody></table></div></details>"
        )
    return "".join(items)


def build_html(project_local: bool = False) -> str:
    state = load_state()
    verification, groups, region = load_inventory()
    source_check_path = PROJECT_ROOT / "reports" / "original_source_verification.json"
    source_check = json.loads(source_check_path.read_text(encoding="utf-8")) if source_check_path.exists() else {"unchanged": False}
    benchmark = load_benchmark()
    product = load_product_acceptance()
    models = benchmark.get("models", [])
    model_lines = "".join(
        f"<li><code>{esc(name)}</code> — {esc(next((m.get('details',{}).get('parameter_size') for m in benchmark.get('model_metadata',[]) if m.get('name')==name), 'встановлена модель'))}</li>"
        for name in ("qwen3.5:4b", "qwen2.5-coder:7b", "qwen3.5:9b")
    )
    group_rows = "".join(f"<tr><td>{esc(name)}</td><td>{count:,}</td></tr>" for name, count in sorted(groups.items()))
    gate_rows = ""
    task_rows = render_tasks(state["tasks"])
    bench_status = benchmark.get("status", "NOT_RUN")
    recommended = benchmark.get("recommended_model") or "Ще не визначено"
    recommended_row = next((row for row in models if row.get("model") == recommended), {})
    code_task_ids = {"NCDR_CODE_U24_15", "NCDR_CODE_MP0_16"}
    code_tests = [task for model in models for task in model.get("tasks", []) if task.get("task_id") in code_task_ids]
    code_passes = sum(bool(task.get("pass")) for task in code_tests)
    code_summary = f"Перевірені кодові відповіді: {code_passes}/{len(code_tests)} пройшли обмежені тести."
    if code_tests and code_passes == 0:
        code_summary += " Жоден кандидат не допущений до генерації writer-коду."
    model_details = render_models(benchmark)
    writer_report = json.loads((PROJECT_ROOT / "reports" / "autonomous_writer_roundtrip.json").read_text(encoding="utf-8")) if (PROJECT_ROOT / "reports" / "autonomous_writer_roundtrip.json").exists() else {}
    progress = readiness.calculate_readiness(state["gates"], product=product, writer=writer_report)
    earned, possible = progress["earned"], progress["total"]
    gate_rows = render_gate_rows(state["gates"], progress["gates"])
    checks = {name: product.get("checks", {}).get(name, {}) for name in (
        "map_database_integrity", "versioned_osm_provenance", "city_search_and_connected_route", "original_media_unchanged")
        if name in product.get("checks", {})}
    passed_product_checks = sum(1 for check in checks.values() if check.get("pass") is True)
    total_product_checks = len(checks)
    product_rows = "".join(
        f"<tr><td>{esc(name)}</td><td><span class=\"status {'done' if check.get('pass') else 'blocked'}\">{'PASS' if check.get('pass') else 'НЕ ПІДТВЕРДЖЕНО'}</span></td><td>{esc(check.get('evidence',''))}</td></tr>"
        for name, check in checks.items()) or '<tr><td colspan="3">Приймальні докази ще не внесені.</td></tr>'
    active_product_tracks = {"OSM Ukraine", "NCDx container research", "NCDx writer"}
    track_rows = "".join(
        f"<tr><td>{esc(name)}</td><td>{esc(item.get('status','IN_PROGRESS'))}</td><td>{esc(item.get('verified',''))}<br><small>Артефакт: <code>{esc(item.get('artifact','—'))}</code></small><br><small>{esc(item.get('limitations',''))}</small></td></tr>"
        for name, item in product.get("tracks", {}).items() if name in active_product_tracks)
    if not track_rows:
        track_rows = '<tr><td colspan="3">Для активних напрямів ще немає внесених доказів.</td></tr>'
    progress_rows = "".join(
        f"<tr><td>{esc(name)}</td><td><progress max=\"100\" value=\"{item['percent']}\">{item['percent']}%</progress> <b>{item['percent']}%</b></td><td>{item['earned']} / {item['total']} доказових балів</td></tr>"
        for name, item in progress["components"].items())
    active_scope = project_scope.load_scope()
    report_links = [
        ("Аудит джерел", "reports/AUDIT_REPORT.md"),
        ("Матриця сумісності", "reports/COMPATIBILITY_MATRIX.md"),
        ("Фіксовані MP0 поля", "reports/FORMAT_SPEC.md"),
        ("Невідомі поля та обмеження", "reports/FORMAT_UNKNOWN.md"),
        ("Результат добору моделей", "reports/MODEL_SELECTION.md"),
        ("Перевірка незмінності джерел", "reports/original_source_verification.json"),
        ("Повний model benchmark", "reports/model_benchmark.json"),
        ("Повний SHA-256 маніфест CSV", "inventory/discs_manifest.csv"),
        ("Повний SHA-256 маніфест JSON", "inventory/discs_manifest.json"),
        ("Порівняння регіонів", "inventory/region_cross_diff.json"),
        ("Завдання benchmark", "src/agent/benchmark_tasks.json"),
        ("Перевірки OSM-даних для диска", "reports/product_acceptance.json"),
        ("Архів виключених програмних напрямів", "archive/excluded_tracks_2026-10-25/README.md"),
    ]
    link_prefix = "" if project_local else "../work/NCDR_MAP_RESEARCH/"
    link_html = "".join(f'<li><a href="{link_prefix}{esc(path)}">{esc(label)}</a></li>' for label, path in report_links)
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    free_gib = "—"
    resource_path = PROJECT_ROOT / "reports" / "model_benchmark.json"
    if models:
        gpu = next((row.get("baseline_resources", {}).get("gpu") for row in models if row.get("baseline_resources", {}).get("gpu")), None)
        if gpu:
            free_gib = f"{gpu.get('memory_free_mib', 0) / 1024:.1f} GiB вільно до прогону"

    tabs = [
        ("progress", "Прогрес"), ("evidence", "Докази"), ("formats", "Формати"),
        ("tasks", "Черга Codex"), ("qwen", "Виконавці Qwen"), ("resources", "Ресурси"),
        ("images", "Образи диска"), ("reports", "Звіти й архів"),
    ]
    nav = "".join(
        f'<button type="button" role="tab" id="tab-{key}" aria-controls="panel-{key}" aria-selected="{"true" if i == 0 else "false"}" class="tab{" active" if i == 0 else ""}">{esc(label)}</button>'
        for i, (key, label) in enumerate(tabs)
    )
    panels = {
        "progress": f'''<section id="panel-progress" role="tabpanel" aria-labelledby="tab-progress">
          <div class="hero"><div><p class="eyebrow">Активна ціль · {esc(now)}</p><h1>NCDR Ukraine · підготовка фізичного диска</h1><p>{esc(active_scope['global_goal'])}</p></div><div class="ready"><b>DISK_NOT_READY</b><span>PHYSICAL_COMPATIBILITY_NOT_TESTED</span></div></div>
          <div class="metrics"><article><small>Підтверджена готовність</small><b>{progress['percent']}%</b><span>{earned} / {possible} балів за активними критеріями</span></article><article><small>Перевірки даних для диска</small><b>{passed_product_checks} / {total_product_checks}</b><span>Ці перевірки не підтверджують NCDx-експорт</span></article><article><small>Оригінальні файли</small><b>{verification.get('files_hashed',0):,} / {verification.get('files_expected',0):,}</b><span>{esc(verification.get('files_failed',0))} помилок hash; джерела read-only</span></article></div>
          <h2>Готовність за напрямами</h2><div class="table-wrap"><table><thead><tr><th>Активний напрям</th><th>Підтверджено</th><th>Докази</th></tr></thead><tbody>{progress_rows}</tbody></table></div>
          <h2>Активні напрями</h2><p>OSM-пошук, дорожній граф і POI використовуються лише для підготовки та перевірки даних, призначених для фізичного диска. Кількість задач, моделей і статистичних профілів не додає прогресу.</p><div class="table-wrap"><table><thead><tr><th>Напрям</th><th>Стан</th><th>Доказ і межі перевірки</th></tr></thead><tbody>{track_rows}</tbody></table></div>
          <h2>Приймальні перевірки</h2><div class="table-wrap"><table><thead><tr><th>Критерій</th><th>Результат</th><th>Доказ</th></tr></thead><tbody>{product_rows}</tbody></table></div>
          <h2>Контрольні ворота NCDx</h2><div class="table-wrap"><table><thead><tr><th>Етап</th><th>Стан</th><th>Виконана вага</th></tr></thead><tbody>{gate_rows}</tbody></table></div>
          <p class="callout">Фізична сумісність не перевірена. Не підтверджено кінцевий образ або його приймання в сумісному автомобілі.</p>
        </section>''',
        "evidence": f'''<section id="panel-evidence" role="tabpanel" aria-labelledby="tab-evidence" hidden><h1>Інвентаризація та докази</h1><p>Джерело: <code>NCDR_SOURCE_ROOT (local configuration)</code>. Маніфест має {verification.get('files_hashed',0):,} файлів, {verification.get('files_failed',0)} помилок hash; SQLite evidence має {state['evidence_count']:,} рядків. Integrity check: <b>{esc(state['integrity'])}</b>.</p><div class="table-wrap"><table><thead><tr><th>Група</th><th>Файлів</th></tr></thead><tbody>{group_rows}</tbody></table></div><p>Після інвентаризації повторно порівняно шляхи, розміри й час останньої зміни: <b>{'джерело не змінене' if source_check.get('unchanged') else 'перевірка ще не пройдена'}</b> ({source_check.get('current_files',0):,} файлів).</p><p>Оригінали відкривалися тільки для читання; усі робочі артефакти створені окремо.</p><p>Попередні маніфести містили 9 історичних дисків; наявні три повні дерева: CD_7185 Italy, CD_7186 Scandinavia, CD_7190 EU. Зображень sector-level формату не знайдено.</p><p>DB_0 SHA-256: <code>c5f495efcd26a8bc49197c73b116fcbccf127a397e1d2751c1aa88a9ed8589ef</code>. Його форматні висновки застосовуються тільки до DB_0.</p></section>''',
        "formats": f'''<section id="panel-formats" role="tabpanel" aria-labelledby="tab-formats" hidden><h1>Відомі байти та невідомі формати</h1><div class="table-wrap"><table><thead><tr><th>Файл / offset</th><th>Спостереження</th><th>Межа висновку</th></tr></thead><tbody><tr><td><code>*Z.MP0 · 0x00</code></td><td>13 байтів <code>(*${""}SIEMENS&^)</code></td><td>Лише фіксований marker</td></tr><tr><td><code>*Z.MP0 · 0x10</code></td><td>Copyright 1998</td><td>ASCII поле</td></tr><tr><td><code>*Z.MP0 · 0x20</code></td><td>Внутрішня версія 2.0.0</td><td>ASCII поле</td></tr><tr><td><code>*Z.MP0 · 0x30</code></td><td>EU/I/SC code, NUL-terminated</td><td>Уточнено прямим підрахунком індексів байтів; записи payload невідомі</td></tr><tr><td><code>DB_0 · hash вище</code></td><td>Старий формат має окрему перевірену структуру</td><td>Не переносити на NCDx</td></tr></tbody></table></div><p>Регіональне порівняння: {region.get('matched_normalized_paths',0)} спільних імен; {region.get('same_sha256_count',0)} однакових та {region.get('different_sha256_count',0)} відмінних SHA-256. Це не доводить семантичну еквівалентність.</p></section>''',
        "tasks": f'''<section id="panel-tasks" role="tabpanel" aria-labelledby="tab-tasks" hidden><h1>Автономна черга задач</h1><p>Показані тільки задачі активної області; історичні Virtual CID і POI-задачі збережено в архіві. Lease, залежності, результати й події записуються у SQLite.</p><div class="table-wrap"><table><thead><tr><th>Задача</th><th>Стан</th><th>Наступна дія</th></tr></thead><tbody>{task_rows}</tbody></table></div></section>''',
        "qwen": f'''<section id="panel-qwen" role="tabpanel" aria-labelledby="tab-qwen" hidden><h1>Локальні виконавці</h1><p>Стан порівняння: <b>{esc(bench_status)}</b>. Найкращий кандидат за перевіреними відповідями за хвилину: <b>{esc(recommended)}</b> — {esc(recommended_row.get('passed',0))}/18 за {esc(recommended_row.get('duration_seconds','—'))} с.</p><p>{esc(code_summary)}</p><ul>{model_lines}</ul>{model_details}<p class="muted">Кожна модель отримала ті самі 18 NCDR завдань. Результат вимірюється одним послідовним прогоном; моделі вивантажуються після запуску. Вибір стосується лише локальних задач із зовнішньою перевіркою, а не довіри до невалідаваних форматних тверджень.</p></section>''',
        "resources": f'''<section id="panel-resources" role="tabpanel" aria-labelledby="tab-resources" hidden><h1>Локальні ресурси</h1><ul><li>Windows RAM: 32 GiB встановлено; на першому вимірі доступно 13.6 GiB.</li><li>NVIDIA RTX PRO 1000 Blackwell Laptop GPU: 8,151 MiB загалом; на першому вимірі вільно 7,247 MiB.</li><li>Ollama лімітовано одним завантаженим model; benchmark послідовний.</li></ul><p>{esc(free_gib)}. Значення залежать від інших активних програм на машині.</p><p>Лідер за виміряним пропуском: <b>{esc(recommended)}</b>. Найвища пікова VRAM у прогоні: {esc(max((row.get('peak_vram_used_mib') or 0 for row in models), default='—'))} MiB. Порівняння одноразове; швидкість може змінюватися разом із системним навантаженням.</p><p>{esc(code_summary)} Автоматично перевірені локальні відповіді не дають моделі права писати змінений диск.</p></section>''',
        "images": '''<section id="panel-images" role="tabpanel" aria-labelledby="tab-images" hidden><h1>Побудова образу</h1><p>Готового секторного образу немає. У джерелі знайдені три файлові дерева; TOC містить метадані, але не секторну геометрію. Тому кнопка/дія створення фінального образу заблокована.</p><p class="callout">Статус носія: DISK_NOT_READY. Потрібні точна модель пристрою, правильний секторний layout і реальне приймання диска.</p></section>''',
        "reports": f'''<section id="panel-reports" role="tabpanel" aria-labelledby="tab-reports" hidden><h1>Звіти та артефакти</h1><ul>{link_html}</ul><p>SQLite: {state['evidence_count']:,} evidence рядків; {state['model_run_count']} збережених model-run записів; цілісність {esc(state['integrity'])}.</p><p>Останнє формування Dashboard: {esc(now)}.</p></section>''',
    }
    panel_html = "".join(panels[key] for key, _ in tabs)
    return f'''<!doctype html>
<html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>NCDR Map Research Dashboard</title>
<style>
:root{{color-scheme:dark;--bg:#111820;--surface:#1a2530;--text:#e7edf3;--muted:#aab8c4;--line:#344351;--blue:#5fa8ff;--green:#65c89a;--yellow:#efc164;--red:#f07e77;--chip:#253543}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 "Segoe UI",system-ui,sans-serif}}main{{max-width:1180px;margin:auto;padding:24px}}h1{{font-size:1.55rem;line-height:1.25;margin:4px 0 12px}}h2{{font-size:1.1rem;margin:24px 0 10px}}p{{margin:10px 0}}small,.muted{{color:var(--muted)}}code{{font:0.9em Consolas,monospace;overflow-wrap:anywhere}}a{{color:var(--blue)}}.tabs{{display:flex;gap:6px;overflow:auto;padding:8px 0 16px;border-bottom:1px solid var(--line)}}.tab{{border:1px solid var(--line);background:var(--surface);color:var(--text);padding:9px 12px;border-radius:8px;white-space:nowrap;cursor:pointer}}.tab[aria-selected=true]{{background:#284663;border-color:#456789}}.panel{{padding:18px 0}}.hero{{display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap}}.eyebrow{{font-size:.8rem;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}}.ready{{display:flex;flex-direction:column;gap:2px;padding:12px 16px;border-radius:10px;background:#402523;color:#ffd5d0}}.ready span{{font-size:.86rem}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:20px 0}}.metrics article{{padding:14px;border-radius:10px;background:var(--surface);display:grid;gap:5px}}.metrics b{{font-size:1.35rem;font-variant-numeric:tabular-nums}}.metrics span,.metrics small{{color:var(--muted)}}.table-wrap{{width:100%;overflow:auto}}table{{width:100%;border-collapse:collapse;margin:12px 0 20px}}th,td{{padding:10px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{font-weight:600;color:#ccd7e0}}td small{{font-size:.82rem}}.status{{display:inline-block;padding:3px 9px;border-radius:99px;background:var(--chip);white-space:nowrap}}.status.done{{color:var(--green)}}.status.blocked{{color:var(--red)}}.status.pending{{color:var(--yellow)}}.status.leased{{color:var(--blue)}}.callout{{padding:12px 14px;border-left:3px solid var(--yellow);background:#29271f}}details{{margin:12px 0;border-bottom:1px solid var(--line);padding:4px 0 12px}}summary{{cursor:pointer;padding:8px 2px}}section[hidden]{{display:none}}@media(max-width:520px){{main{{padding:14px}}.tab{{padding:9px 10px}}th,td{{padding:8px 6px}}}}
</style></head><body><main>
<nav class="tabs" role="tablist" aria-label="Розділи Dashboard">{nav}</nav>
<div class="panel" aria-live="polite">{panel_html}</div>
<script>
document.querySelectorAll('[role="tab"]').forEach(function(tab){{tab.addEventListener('click',function(){{document.querySelectorAll('[role="tab"]').forEach(function(item){{item.setAttribute('aria-selected','false');item.classList.remove('active')}});document.querySelectorAll('[role="tabpanel"]').forEach(function(panel){{panel.hidden=true}});tab.setAttribute('aria-selected','true');tab.classList.add('active');document.getElementById(tab.getAttribute('aria-controls')).hidden=false}})}});
</script></main></body></html>'''


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(build_html(), encoding="utf-8")
    PROJECT_OUTPUT_PATH.write_text(build_html(project_local=True), encoding="utf-8")
    print(json.dumps({"dashboard": str(OUTPUT_PATH), "project_dashboard": str(PROJECT_OUTPUT_PATH), "bytes": OUTPUT_PATH.stat().st_size, "updated_local": datetime.now().astimezone().isoformat()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
