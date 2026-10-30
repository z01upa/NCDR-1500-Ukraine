"""Compact Windows panel for the existing persistent NCDR research worker."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from contextlib import closing
import json
import os
from pathlib import Path
import queue
import re
import sqlite3
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any
from urllib.parse import quote

from src.agent import autonomous_manager as manager
from src.agent import project_scope
from src.agent.autonomous_gui import PROJECT_ROOT, _read_json, verified_progress


COLORS = {"green": "#07845f", "yellow": "#b98200", "red": "#bd3932", "gray": "#7b8790"}
UI_STATE = PROJECT_ROOT / "work" / "autonomous_manager" / "gui_state.json"
MODEL_TEXT_SETTINGS = PROJECT_ROOT / "work" / "autonomous_manager" / "model_text_settings.json"
MAX_VISIBLE_LOG_LINES = 300


def _short(value: Any, limit: int = 62) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def derive_ai_status(state: dict[str, Any], *, now_utc: datetime | None = None,
                     stale_after_seconds: int = 180) -> dict[str, Any]:
    """Use actual request start/end/error events, never the Worker RUNNING flag."""
    now_utc = now_utc or datetime.now(timezone.utc)
    events = [row for row in state.get("events", []) if row.get("event") in {
        "ollama_request_started", "ollama_request_completed", "ollama_request_failed"}]
    latest = max(events, key=lambda row: int(row.get("id", 0)), default=None)
    models = state.get("ollama_models") or []
    status_known = state.get("ollama_status_known",
        "ollama_models" in state or "ollama_error" in state)
    detail = (latest.get("detail_json") or {}) if latest else {}
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            detail = {}
    name = str(latest.get("event", "")) if latest else ""
    base = {"model": detail.get("model"), "role": detail.get("role"),
        "last_activity": latest.get("created_utc") if latest else None,
        "request_id": detail.get("request_id")}
    health_error = str(state.get("ollama_error") or "")
    # A sandbox or Windows policy can deny the GUI's loopback health probe even
    # while the separate Worker has just completed a real Ollama call. That is
    # an unknown health state, not evidence that Ollama itself is down.
    restricted_probe = any(token in health_error.casefold() for token in
        ("winerror 10013", "access is denied", "operation not permitted", "запрещенн"))
    event_time = _parse_time(latest.get("created_utc")) if latest else None
    event_age = (max(0, int((now_utc - event_time).total_seconds()))
                 if event_time else stale_after_seconds + 1)
    if name == "ollama_request_started":
        started = _parse_time(detail.get("started_utc") or latest.get("created_utc"))
        age = int(max(0, (now_utc - started).total_seconds())) if started else stale_after_seconds + 1
        if age <= stale_after_seconds:
            return {**base, "level": "green", "label": "Модель виконує запит",
                "elapsed_seconds": age, "error": None}
        return {**base, "level": "gray", "label": "Телеметрія застаріла",
            "elapsed_seconds": age, "error": "Немає завершальної телеметрії"}
    if name == "ollama_request_failed" and event_age <= stale_after_seconds:
        return {**base, "level": "red", "label": "Помилка запиту моделі",
            "elapsed_seconds": (detail.get("elapsed_ms") or 0) / 1000,
            "error": detail.get("error") or detail.get("failure_kind")}
    if state.get("ollama_error") and restricted_probe:
        return {**base, "level": "gray", "label": "Доступність не встановлена",
            "elapsed_seconds": (detail.get("elapsed_ms") or 0) / 1000 if name == "ollama_request_completed" else None,
            "error": health_error}
    if not status_known:
        return {**base, "level": "gray", "label": "Немає актуальних даних",
            "elapsed_seconds": None, "error": None}
    if state.get("ollama_error"):
        return {**base, "level": "red", "label": "Ollama недоступна",
            "elapsed_seconds": None, "error": health_error}
    if not models:
        return {**base, "level": "red", "label": "Немає доступної моделі",
            "elapsed_seconds": None, "error": "Ollama не повернула встановлених моделей"}
    if not latest:
        return {"level": "yellow", "label": "Модель доступна · очікує", "model": None,
            "role": None, "elapsed_seconds": None, "error": None, "last_activity": None}
    if name == "ollama_request_failed":
        return {**base, "level": "yellow", "label": "Ollama доступна · останній виклик був невдалим",
            "elapsed_seconds": (detail.get("elapsed_ms") or 0) / 1000,
            "error": detail.get("error") or detail.get("failure_kind")}
    return {**base, "level": "yellow", "label": "Модель доступна · очікує",
        "elapsed_seconds": (detail.get("elapsed_ms") or 0) / 1000, "error": None}


def derive_research_status(state: dict[str, Any]) -> dict[str, str]:
    control = state.get("control", {})
    diagnosis = state.get("queue_diagnosis", {})
    current = str(control.get("current_task") or "")
    if control.get("desired_state") == "PAUSED":
        return {"level": "yellow", "label": "На паузі"}
    active_rows = [row for row in state.get("tasks", [])
                   if str(row.get("id")) == current and row.get("status") == "LEASED"]
    if current and active_rows:
        return {"level": "green", "label": "Виконує корисну задачу"}
    if current and control.get("desired_state") == "RUNNING":
        return {"level": "yellow", "label": "Звіряє стан поточної задачі"}
    if diagnosis.get("eligible_task_ids") or int(diagnosis.get("pending_count", 0)):
        return {"level": "yellow", "label": "Є заплановане продовження"}
    return {"level": "red", "label": "Заблоковано · придатних задач немає"}


def _redact(text: str) -> str:
    text = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1[приховано]", text)
    key = r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)"
    text = re.sub(rf'(?i)((?:"?{key}"?)\s*[:=]\s*")[^"\r\n]*(")',
                  r"\1[приховано]\2", text)
    text = re.sub(rf"(?i)((?:{key})\s*[:=]\s*)[^\s,;}}]+", r"\1[приховано]", text)
    return text[:12000]


def _read_only_dashboard_snapshot(*, include_model_telemetry: bool = True) -> dict[str, Any]:
    """Collect the compact panel's state using bounded, query-only SQLite reads."""
    database = manager.STATE_DB.resolve()
    uri = database.as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=2.0)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        control: dict[str, Any] = {}
        if "autonomy_control" in tables:
            row = conn.execute("SELECT * FROM autonomy_control WHERE singleton=1").fetchone()
            control = dict(row) if row else {}
        elif "coordinator_control" in tables:
            row = conn.execute("SELECT * FROM coordinator_control WHERE id=1").fetchone()
            control = dict(row) if row else {}

        task_rows: list[dict[str, Any]] = []
        active_task_rows: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        eligible: list[str] = []
        pending_count = leased_count = 0
        if "tasks" in tables:
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)")}
            wanted = ("id", "status", "stage", "agent", "hypothesis", "verdict", "attempts",
                      "retry_limit", "priority", "updated_utc", "budget_json",
                      "depends_on_json", "next_action", "heartbeat_utc")
            selected = [column for column in wanted if column in columns]
            all_rows = [dict(row) for row in conn.execute(
                f"SELECT {','.join(selected)} FROM tasks ORDER BY updated_utc DESC")]
            active_task_rows = [row for row in all_rows if not project_scope.task_is_excluded(row)]
            task_rows = active_task_rows[:600]
            for row in active_task_rows:
                status = str(row.get("status") or "UNKNOWN")
                counts[status] = counts.get(status, 0) + 1
            by_id = {str(row.get("id")): row for row in active_task_rows}
            pending_rows = [row for row in active_task_rows if row.get("status") == "PENDING"]
            pending_count = len(pending_rows)
            leased_count = sum(row.get("status") == "LEASED" for row in active_task_rows)
            for row in pending_rows:
                try:
                    deps = json.loads(row.get("depends_on_json") or "[]")
                except (TypeError, json.JSONDecodeError):
                    deps = ["invalid dependency record"]
                if isinstance(deps, list) and all(by_id.get(str(dep), {}).get("status") == "DONE" for dep in deps):
                    eligible.append(str(row.get("id")))
        diagnosis = {"pending_count": pending_count, "leased_count": leased_count,
                     "eligible_task_ids": eligible}
        if leased_count:
            diagnosis.update(status="RUNNING", message=f"Виконується {leased_count} орендована задача.")
        elif eligible:
            diagnosis.update(status="READY", message=f"Є {len(eligible)} придатних задач.")
        elif pending_count:
            diagnosis.update(status="WAITING_DEPENDENCY", message="Очікування підтвердженої залежності.")
        else:
            diagnosis.update(status="EMPTY", message="Черга порожня; Director перевіряє незавершені цілі.")

        events = []
        if "autonomy_events" in tables:
            event_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(autonomy_events)")}
            event_select = [name for name in ("id", "created_utc", "event", "severity", "task_id", "session_id")
                            if name in event_columns]
            if "detail_json" in event_columns:
                event_select.append("substr(detail_json,1,2400) AS detail_json")
            if event_select:
                events = [dict(row) for row in conn.execute(
                    f"SELECT {','.join(event_select)} FROM autonomy_events ORDER BY id DESC LIMIT 300")]
        artifacts = []
        if "autonomy_artifacts" in tables:
            artifacts = [dict(row) for row in conn.execute(
                "SELECT * FROM autonomy_artifacts ORDER BY created_utc DESC LIMIT 100")]
        stage_gates = []
        if "stage_gates" in tables:
            stage_gates = [dict(row) for row in conn.execute(
                "SELECT stage,status,criteria_json,proof_json,updated_utc FROM stage_gates ORDER BY stage")]
        evidence_count = conn.execute("SELECT count(*) FROM evidence").fetchone()[0] if "evidence" in tables else 0
        model_run_count = conn.execute("SELECT count(*) FROM model_runs").fetchone()[0] if "model_runs" in tables else 0
        model_telemetry: dict[str, Any] = {"available": False, "periods": {}, "recent_runs": []}
        if include_model_telemetry and "research_runs" in tables:
            try:
                from src.agent.coordinator_runtime import _model_telemetry
                model_telemetry = _model_telemetry(conn)
                model_telemetry["recent_runs"] = [row for row in model_telemetry.get("recent_runs", [])
                    if not project_scope.task_is_excluded(str(row.get("task_id") or ""))]
            except (sqlite3.Error, ValueError, TypeError) as exc:
                model_telemetry = {"available": False, "reason": f"{type(exc).__name__}: {exc}",
                                   "periods": {}, "recent_runs": []}
        director_state: dict[str, Any] = {"available": False, "config": {}, "decisions": []}
        if "director_scheduler_config" in tables:
            config_row = conn.execute(
                "SELECT * FROM director_scheduler_config WHERE singleton=1").fetchone()
            decision_rows = []
            if "director_decisions" in tables:
                decision_rows = [dict(row) for row in conn.execute(
                    "SELECT request_id,created_utc,decision,task_id,model,reason,evidence_fingerprint "
                    "FROM director_decisions ORDER BY id DESC LIMIT 100")]
            director_state = {"available": bool(config_row),
                "config": dict(config_row) if config_row else {}, "decisions": decision_rows}

    from src.agent.resource_probe import resource_snapshot
    try:
        national_osm_progress = manager._national_osm_dashboard_progress()
    except Exception as exc:
        national_osm_progress = {"phase": "ERROR", "message": f"{type(exc).__name__}: {exc}", "percent": 0}
    return {"control": control, "tasks": task_rows, "events": events, "artifacts": artifacts,
        "project": {"task_counts": counts, "stage_gates": stage_gates,
                    "evidence_count": evidence_count, "model_run_count": model_run_count},
        "resources": resource_snapshot(), "queue_diagnosis": diagnosis,
        "coordinator": {"model_telemetry": model_telemetry},
        "director": director_state,
        "national_osm_progress": national_osm_progress, "project_root": str(PROJECT_ROOT)}


class ManagerWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("NCDR Autonomous Research Manager")
        saved = _read_json(UI_STATE)
        width = min(1800, max(900, int(saved.get("width", 1000))))
        height = min(1200, max(540, int(saved.get("height", 600))))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(900, 540)
        self.root.configure(bg="#f3f6f8")
        self.closing = threading.Event()
        self.latest_state: dict[str, Any] | None = None
        self.snapshot_error = ""
        self.last_refresh = 0.0
        self.cpu_prior: tuple[int, int] | None = None
        self.text_results: queue.Queue[tuple[int, dict[str, str] | None, str]] = queue.Queue()
        self.director_action_results: queue.Queue[tuple[str, str]] = queue.Queue()
        self.text_request_id = 0
        self._geometry_after: str | None = None
        self.ai_rows: dict[str, dict[str, Any]] = {}
        self._queue_sort_column = "updated"
        self._queue_sort_reverse = True
        self._queue_sort_titles = {"#0": "Задача", "stage": "Етап", "status": "Стан",
                                   "attempts": "Спроби", "updated": "Оновлено"}
        self._control_mode = "BLOCKED"
        self._blink_phase = False
        self._blink_after_id: str | None = None
        self.current_task_full = ""
        self.ollama_models: list[str] = []
        self.ollama_error: str | None = None
        self.ollama_status_known = False
        self.cached_model_telemetry: dict[str, Any] = {"available": False, "periods": {}, "recent_runs": []}
        self._make_style()
        self._make_layout()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Configure>", self._schedule_save_geometry, add="+")
        self.poller = threading.Thread(target=self._poll_snapshot, name="ncdr-ui-read-only-snapshot", daemon=True)
        self.poller.start()
        self.ollama_poller = threading.Thread(target=self._poll_ollama, name="ncdr-ui-ollama-health", daemon=True)
        self.ollama_poller.start()
        self.root.after(100, self.refresh)

    def _make_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f6f8")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f3f6f8", foreground="#17212b", font=("Segoe UI", 9))
        style.configure("Hint.TLabel", foreground="#506372", font=("Segoe UI", 8))
        style.configure("Title.TLabel", foreground="#12334a", font=("Segoe UI", 14, "bold"))
        style.configure("Metric.TLabel", background="#ffffff", font=("Segoe UI", 9, "bold"), padding=(5, 3))
        style.configure("Treeview", rowheight=21, font=("Segoe UI", 8), background="#ffffff", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=("Segoe UI", 8, "bold"))
        style.configure("TNotebook", background="#f3f6f8", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(9, 4), font=("Segoe UI", 8, "bold"))
        style.configure("Compact.TButton", font=("Segoe UI", 8), padding=(6, 3))
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"), padding=(8, 4))
        style.configure("Danger.TButton", foreground="#a22220", font=("Segoe UI", 8, "bold"), padding=(6, 3))

    def _make_layout(self) -> None:
        shell = ttk.Frame(self.root, padding=8)
        shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell)
        header.pack(fill="x")
        ttk.Label(header, text="NCDR Autonomous Research Manager", style="Title.TLabel").pack(side="left")
        status_box = ttk.Frame(header)
        status_box.pack(side="right")
        self.worker_var, self.worker_dot = self._indicator(status_box, "Worker")
        self.ai_var, self.ai_dot = self._indicator(status_box, "Локальний ШІ")
        self.research_var, self.research_dot = self._indicator(status_box, "Дослідження")

        actions = ttk.Frame(shell, padding=(0, 4, 0, 3))
        actions.pack(fill="x")
        self.play_pause_button = tk.Button(actions, text="▶", command=self.toggle_research,
            font=("Segoe UI Symbol", 11, "bold"), width=3, relief="flat", bd=0,
            fg="#ffffff", bg=COLORS["green"], activeforeground="#ffffff",
            activebackground="#056b4c", cursor="hand2")
        self.play_pause_button.pack(side="left")
        _ToolTip(self.play_pause_button, "Запуск, пауза, продовження або діагностика визначаються за фактичним станом Worker і черги.")
        self.stop_button = tk.Button(actions, text="■", command=self.stop,
            font=("Segoe UI Symbol", 10, "bold"), width=3, relief="flat", bd=0,
            fg="#263746", bg="#e3e9ed", activebackground="#d2dce2", cursor="hand2")
        self.stop_button.pack(side="left", padx=(4, 0))
        _ToolTip(self.stop_button, "Зупинити після безпечного збереження поточного стану.")
        ttk.Button(actions, text="Аварія", style="Danger.TButton", command=self.emergency_stop).pack(side="left", padx=(4, 0))
        self.control_reason = tk.StringVar(value="Стан перевіряється…")
        ttk.Label(actions, textvariable=self.control_reason, style="Hint.TLabel", anchor="w").pack(side="left", padx=(8, 0), fill="x", expand=True)
        ttk.Button(actions, text="Результати", style="Compact.TButton", command=self.open_results).pack(side="right")
        self.command_status = tk.StringVar(value="Стан перевіряється…")
        ttk.Label(shell, textvariable=self.command_status, style="Hint.TLabel", anchor="w").pack(fill="x", pady=(0, 4))

        metrics = ttk.Frame(shell)
        metrics.pack(fill="x", pady=(0, 5))
        self.metric_vars = [tk.StringVar(value="—") for _ in range(4)]
        self.current_task_full = ""
        for idx, title in enumerate(("Черга", "Поточна задача", "Ресурси", "AI")):
            card = ttk.Frame(metrics, style="Card.TFrame", padding=(6, 3))
            card.pack(side="left", fill="both", expand=True, padx=(0 if idx == 0 else 5, 0))
            ttk.Label(card, text=title.upper(), style="Hint.TLabel").pack(anchor="w")
            label = ttk.Label(card, textvariable=self.metric_vars[idx], style="Metric.TLabel",
                              wraplength=205, justify="left", anchor="w")
            label.pack(fill="both", expand=True)
            if idx == 1:
                self.current_task_label = label
                label.bind("<Button-1>", lambda _event: self._show_task_detail(self.current_task_full))
                _ToolTip(label, "Натисніть, щоб відкрити повну назву, гіпотезу й стан задачі.")

        self._make_readiness(shell)
        self.tabs = ttk.Notebook(shell)
        self.tabs.pack(fill="both", expand=True)
        self.queue_tab = ttk.Frame(self.tabs, padding=5)
        self.logs_tab = ttk.Frame(self.tabs, padding=5)
        self.evidence_tab = ttk.Frame(self.tabs, padding=5)
        self.reports_tab = ttk.Frame(self.tabs, padding=5)
        self.ai_tab = ttk.Frame(self.tabs, padding=5)
        for page, label in ((self.queue_tab, "Черга завдань"), (self.logs_tab, "Журнал"),
                            (self.evidence_tab, "Докази й артефакти"),
                            (self.reports_tab, "Звіти AI Supervisor"), (self.ai_tab, "ШІ-монітор")):
            self.tabs.add(page, text=label)
        self._make_queue()
        self._make_logs()
        self._make_evidence()
        self._make_reports()
        self._make_ai_monitor()

        footer = ttk.Frame(shell)
        footer.pack(side="bottom", fill="x", pady=(3, 0))
        # Pack the fixed-height footer first in Tk's geometry order so the
        # expanding notebook cannot push the heartbeat row below the window.
        footer.pack_configure(before=self.tabs)
        self.footer_var = tk.StringVar(value="Worker PID · heartbeat · остання задача · останній виклик ШІ")
        ttk.Label(footer, textvariable=self.footer_var, style="Hint.TLabel").pack(side="left", fill="x", expand=True)
        _ToolTip(footer, "Оригінальні джерела Opel читаються без запису; повна фізична сумісність досі не перевірена.")

    @staticmethod
    def _indicator(parent: ttk.Frame, title: str) -> tuple[tk.StringVar, tk.Label]:
        frame = ttk.Frame(parent)
        frame.pack(side="left", padx=(7, 0))
        dot = tk.Label(frame, text="●", fg=COLORS["gray"], background="#f3f6f8", font=("Segoe UI", 9, "bold"))
        dot.pack(side="left", padx=(0, 3))
        value = tk.StringVar(value=f"{title}: —")
        ttk.Label(frame, textvariable=value, font=("Segoe UI", 8, "bold")).pack(side="left")
        return value, dot

    def _make_readiness(self, shell: ttk.Frame) -> None:
        self.progress_frame = ttk.Frame(shell, style="Card.TFrame", padding=(8, 4))
        self.progress_frame.pack(fill="x", pady=(0, 4))
        self.progress_title = tk.StringVar(value="Готовність · сумісність Opel не перевірено")
        ttk.Label(self.progress_frame, textvariable=self.progress_title,
                  font=("Segoe UI", 9, "bold"), background="#ffffff").grid(row=0, column=0, columnspan=6, sticky="w")
        _ToolTip(self.progress_frame, "Показники обчислені з приймальних доказів. 100% внутрішніх тестів не означає, що дорожній Writer або навігаційний диск перевірений на Opel NCDR.")
        self.progress_bars: dict[str, tk.Canvas] = {}
        self.progress_values: dict[str, tk.StringVar] = {}
        names = ["Загалом", *project_scope.load_scope()["readiness_policy"]["progress_components"].keys()]
        for index, name in enumerate(names):
            row, side = divmod(index, 2)
            base = side * 3
            label = ttk.Label(self.progress_frame, text=name, background="#ffffff", width=22)
            label.grid(row=row + 1, column=base, sticky="w", padx=(0, 4), pady=1)
            _ToolTip(label, "Показник формується тільки з відповідних збережених приймальних доказів.")
            bar = tk.Canvas(self.progress_frame, height=7, highlightthickness=0, bd=0, background="#dce8ed")
            bar.grid(row=row + 1, column=base + 1, sticky="ew", pady=1)
            value = tk.StringVar(value="0%")
            ttk.Label(self.progress_frame, textvariable=value, background="#ffffff", width=11,
                      anchor="e", font=("Segoe UI", 8)).grid(row=row + 1, column=base + 2, sticky="e", padx=(3, 5))
            self.progress_bars[name] = bar
            self.progress_values[name] = value
            bar.bind("<Configure>", lambda _e, n=name: self._draw_progress(n))
        self.progress_frame.columnconfigure(1, weight=1)
        self.progress_frame.columnconfigure(4, weight=1)
        self.physical_note = tk.StringVar(value="Фізична сумісність: не перевірено")
        ttk.Label(self.progress_frame, text="Нац. OSM", background="#ffffff", width=22).grid(row=5, column=0, sticky="w", padx=(0, 4))
        self.osm_bar = tk.Canvas(self.progress_frame, height=7, highlightthickness=0, bd=0, background="#dce8ed")
        self.osm_bar.grid(row=5, column=1, sticky="ew")
        self.osm_value = tk.StringVar(value="Ще не запущено")
        ttk.Label(self.progress_frame, textvariable=self.osm_value, background="#ffffff",
                  font=("Segoe UI", 8), anchor="e").grid(row=5, column=2, columnspan=4, sticky="e", padx=5)

    def _draw_progress(self, name: str, value: float | None = None) -> None:
        if value is not None:
            self.progress_bars[name].progress_value = max(0.0, min(100.0, float(value)))
        canvas = self.progress_bars[name]
        progress = float(getattr(canvas, "progress_value", 0.0))
        canvas.delete("all")
        width = max(2, canvas.winfo_width())
        height = max(4, canvas.winfo_height())
        canvas.create_rectangle(0, 0, width, height, fill="#dce8ed", outline="")
        if progress:
            canvas.create_rectangle(0, 0, max(1, width * progress / 100), height, fill=COLORS["green"], outline="")

    def _set_osm_progress(self, value: float) -> None:
        width = max(2, self.osm_bar.winfo_width())
        height = max(4, self.osm_bar.winfo_height())
        self.osm_bar.delete("all")
        self.osm_bar.create_rectangle(0, 0, width, height, fill="#dce8ed", outline="")
        if value > 0:
            self.osm_bar.create_rectangle(0, 0, max(1, width * min(100, value) / 100), height, fill=COLORS["green"], outline="")

    def _make_queue(self) -> None:
        self.queue = ttk.Treeview(self.queue_tab, columns=("stage", "status", "attempts", "updated"), show="tree headings")
        for column, title, width in (("#0", "Задача", 360), ("stage", "Етап", 55),
                                    ("status", "Стан", 105), ("attempts", "Спроби", 70), ("updated", "Оновлено", 135)):
            self.queue.heading(column, text=title, command=lambda col=column: self._sort_queue(col))
            self.queue.column(column, width=width, anchor="w" if column == "#0" else "center")
        self.queue_scroll = ttk.Scrollbar(self.queue_tab, orient="vertical", command=self.queue.yview)
        self.queue.configure(yscrollcommand=self.queue_scroll.set)
        self.queue.pack(side="left", fill="both", expand=True)
        self.queue_scroll.pack(side="right", fill="y")
        self.queue.bind("<Double-1>", lambda _event: self._show_selected_task())
        ttk.Label(self.queue_tab, text="Подвійне натискання відкриває повний опис задачі.", style="Hint.TLabel").pack(anchor="w", pady=(3, 0))
        for status, color in (("BLOCKED", "#99342d"), ("DONE", "#216d4d"), ("LEASED", "#9a6a00")):
            self.queue.tag_configure(status, foreground=color)

    def _make_logs(self) -> None:
        ttk.Label(self.logs_tab, text="Останні події Worker (на екрані максимум 300 рядків).", style="Hint.TLabel").pack(anchor="w", pady=(0, 3))
        self.log_text = tk.Text(self.logs_tab, height=12, wrap="none", font=("Consolas", 8), bg="#ffffff", fg="#243444", state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def _make_evidence(self) -> None:
        self.evidence_text = tk.Text(self.evidence_tab, height=12, wrap="word", font=("Segoe UI", 8), bg="#ffffff", fg="#243444", state="disabled")
        self.evidence_text.pack(fill="both", expand=True)

    def _make_reports(self) -> None:
        toolbar = ttk.Frame(self.reports_tab)
        toolbar.pack(fill="x", pady=(0, 4))
        ttk.Label(toolbar, text="Збережені звіти й незалежні перевірки.", style="Hint.TLabel").pack(side="left")
        ttk.Button(toolbar, text="Відкрити", style="Compact.TButton", command=self.open_selected_report).pack(side="right")
        ttk.Button(toolbar, text="Експортувати копію…", style="Compact.TButton", command=self.export_selected_report).pack(side="right", padx=4)
        self.reports = ttk.Treeview(self.reports_tab, columns=("period", "created", "file"), show="headings")
        for col, title, width in (("period", "Період", 80), ("created", "Створено", 150), ("file", "Звіт", 550)):
            self.reports.heading(col, text=title)
            self.reports.column(col, width=width, anchor="w" if col == "file" else "center")
        self.reports.pack(fill="both", expand=True)

    def _make_ai_monitor(self) -> None:
        self.ai_pages = ttk.Notebook(self.ai_tab)
        self.ai_pages.pack(fill="both", expand=True)
        self.director_tab = ttk.Frame(self.ai_pages, padding=4)
        self.ai_history_tab = ttk.Frame(self.ai_pages, padding=4)
        self.ai_pages.add(self.director_tab, text="AI Director")
        self.ai_pages.add(self.ai_history_tab, text="Історія моделей")

        director_bar = ttk.Frame(self.director_tab)
        director_bar.pack(fill="x", pady=(0, 4))
        self.director_button = ttk.Button(director_bar, text="Проаналізувати та продовжити",
            style="Accent.TButton", command=self.request_director_analysis)
        self.director_button.pack(side="left")
        self.director_auto = tk.BooleanVar(value=True)
        self.director_interval = tk.StringVar(value="30 хвилин")
        self.director_intervals = {"5 хвилин": 300, "15 хвилин": 900, "30 хвилин": 1800,
            "60 хвилин": 3600, "120 хвилин": 7200, "6 годин": 21600}
        self.director_auto_check = ttk.Checkbutton(director_bar, text="Автоматично",
            variable=self.director_auto, command=self._save_director_settings)
        self.director_auto_check.pack(side="left", padx=(12, 3))
        self.director_interval_combo = ttk.Combobox(director_bar, textvariable=self.director_interval,
            state="readonly", width=12, values=tuple(self.director_intervals))
        self.director_interval_combo.pack(side="left")
        self.director_interval_combo.bind("<<ComboboxSelected>>", lambda _e: self._save_director_settings())
        ttk.Label(director_bar, text="Фільтр").pack(side="left", padx=(12, 3))
        self.director_decision_filter = tk.StringVar(value="Усі")
        self.director_filter_combo = ttk.Combobox(director_bar, textvariable=self.director_decision_filter,
            state="readonly", width=19, values=("Усі", "CREATED", "EXECUTED", "REJECTED",
                "NO_NEW_EVIDENCE", "MISSING_HANDLER", "BLOCKED_EXTERNAL", "ERROR"))
        self.director_filter_combo.pack(side="left")
        self.director_filter_combo.bind("<<ComboboxSelected>>", lambda _e: self._render_director_decisions())
        self.director_summary = tk.StringVar(value="Director: очікується стан планувальника")
        ttk.Label(self.director_tab, textvariable=self.director_summary, style="Hint.TLabel",
                  wraplength=900, justify="left").pack(fill="x", anchor="w", pady=(0, 4))
        decisions_box = ttk.Frame(self.director_tab)
        decisions_box.pack(fill="both", expand=True)
        self.director_decisions = ttk.Treeview(decisions_box,
            columns=("time", "decision", "task", "model", "reason"), show="headings", height=8)
        for col, title, width, anchor in (("time", "Час", 130, "center"),
                ("decision", "Рішення", 145, "center"), ("task", "Задача", 250, "w"),
                ("model", "Модель", 120, "w"), ("reason", "Причина / пояснення", 390, "w")):
            self.director_decisions.heading(col, text=title)
            self.director_decisions.column(col, width=width, anchor=anchor, stretch=(col == "reason"))
        self.director_decisions.pack(side="left", fill="both", expand=True)
        director_scroll = ttk.Scrollbar(decisions_box, orient="vertical", command=self.director_decisions.yview)
        director_scroll.pack(side="right", fill="y")
        self.director_decisions.configure(yscrollcommand=director_scroll.set)
        self.director_decision_rows: list[dict[str, Any]] = []

        toolbar = ttk.Frame(self.ai_history_tab)
        toolbar.pack(fill="x", pady=(0, 3))
        self.ai_model_filter = tk.StringVar(value="Усі")
        self.ai_status_filter = tk.StringVar(value="Усі")
        self.ai_period_filter = tk.StringVar(value="Усі доступні")
        ttk.Label(toolbar, text="Модель").pack(side="left")
        self.ai_model_combo = ttk.Combobox(toolbar, textvariable=self.ai_model_filter, state="readonly", width=19, values=("Усі",))
        self.ai_model_combo.pack(side="left", padx=(3, 7))
        self.ai_model_combo.bind("<<ComboboxSelected>>", lambda _event: self._render_ai_runs())
        ttk.Label(toolbar, text="Стан").pack(side="left")
        self.ai_status_combo = ttk.Combobox(toolbar, textvariable=self.ai_status_filter, state="readonly", width=10,
            values=("Усі", "OK", "INVALID", "FAILED"))
        self.ai_status_combo.pack(side="left", padx=(3, 7))
        self.ai_status_combo.bind("<<ComboboxSelected>>", lambda _event: self._render_ai_runs())
        ttk.Label(toolbar, text="Період").pack(side="left")
        self.ai_period_combo = ttk.Combobox(toolbar, textvariable=self.ai_period_filter, state="readonly", width=13,
            values=("Сьогодні", "7 днів", "Усі доступні"))
        self.ai_period_combo.pack(side="left", padx=(3, 7))
        self.ai_period_combo.bind("<<ComboboxSelected>>", lambda _event: self._render_ai_runs())
        self.ai_model_role = tk.StringVar(value="Активна модель і роль: —")
        ttk.Label(self.ai_history_tab, textvariable=self.ai_model_role, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 3))
        self.ai_stat_vars = {name: tk.StringVar(value=f"{name}: —") for name in ("Сьогодні", "7 днів", "Увесь період")}
        stats = ttk.Frame(self.ai_history_tab)
        stats.pack(fill="x", pady=(0, 2))
        for index, name in enumerate(self.ai_stat_vars):
            ttk.Label(stats, textvariable=self.ai_stat_vars[name], background="#ffffff", padding=(4, 2),
                      font=("Segoe UI", 8), wraplength=300, justify="left").grid(
                          row=0, column=index, sticky="ew", padx=(0, 4))
            stats.columnconfigure(index, weight=1)
        self.ai_activity = tk.StringVar(value="Остання активність: —")
        ttk.Label(self.ai_history_tab, textvariable=self.ai_activity, style="Hint.TLabel").pack(anchor="w", pady=(0, 3))
        table = ttk.Frame(self.ai_history_tab)
        self.ai_runs = ttk.Treeview(table,
            columns=("time", "model", "role", "task", "duration", "status", "tokens"), show="headings")
        definitions = (("time", "Час", 125, "center"), ("model", "Модель", 140, "w"),
            ("role", "Роль", 100, "w"), ("task", "Дослідницька задача", 270, "w"),
            ("duration", "Тривалість", 80, "e"), ("status", "Стан", 70, "center"),
            ("tokens", "Токени in/out", 90, "e"))
        for col, title, width, anchor in definitions:
            self.ai_runs.heading(col, text=title)
            self.ai_runs.column(col, width=width, anchor=anchor, stretch=(col == "task"))
        self.ai_runs.bind("<<TreeviewSelect>>", self._load_selected_model_text)
        self.ai_runs.tag_configure("FAILED", foreground="#99342d")
        self.ai_runs.tag_configure("INVALID", foreground="#9a6a00")
        details = ttk.Frame(self.ai_history_tab)
        details.pack(side="bottom", fill="x", pady=(2, 0))
        text_toolbar = ttk.Frame(details)
        self.show_model_text = tk.BooleanVar(value=False)
        view_text = ttk.Checkbutton(text_toolbar, text="Перегляд тексту виклику", variable=self.show_model_text,
                                    command=self._load_selected_model_text)
        view_text.pack(side="left")
        _ToolTip(view_text, "Читає тільки фактично збережений запис research_runs з відкриттям на вимогу.")
        self.store_model_text = tk.BooleanVar(value=self._model_text_setting())
        store_text = ttk.Checkbutton(text_toolbar, text="Зберігати майбутні тексти (опційно)",
                                     variable=self.store_model_text, command=self._save_model_text_setting)
        store_text.pack(side="right")
        _ToolTip(store_text, "За замовчуванням нові виклики зберігають лише метадані. Опція діє для майбутніх записів, обмежує обсяг і приховує поширені секрети; старі записи не змінює.")
        text_toolbar.pack(fill="x", pady=(2, 1))
        self.ai_text_status = tk.StringVar(value="Тексти приховано; вміст не вигадується, якщо його немає в базі.")
        ttk.Label(details, textvariable=self.ai_text_status, style="Hint.TLabel").pack(fill="x", anchor="e")
        panes = ttk.Frame(details)
        panes.pack(fill="x")
        # Keep enough vertical room for the run history at the compact default
        # window size; full selected text remains scrollable in these panes.
        self.ai_request_text = tk.Text(panes, height=1, wrap="word", font=("Consolas", 8), bg="#ffffff", state="disabled")
        self.ai_response_text = tk.Text(panes, height=1, wrap="word", font=("Consolas", 8), bg="#ffffff", state="disabled")
        panes.columnconfigure(0, weight=1)
        panes.columnconfigure(1, weight=1)
        self.ai_request_text.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        self.ai_response_text.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        table.pack(fill="both", expand=True)
        self.ai_runs.pack(side="left", fill="both", expand=True)
        ai_scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.ai_runs.yview)
        ai_scrollbar.pack(side="right", fill="y")
        self.ai_runs.configure(yscrollcommand=ai_scrollbar.set)

    def _poll_snapshot(self) -> None:
        next_telemetry = 0.0
        while not self.closing.is_set():
            try:
                now = time.monotonic()
                include_telemetry = now >= next_telemetry
                state = _read_only_dashboard_snapshot(include_model_telemetry=include_telemetry)
                if include_telemetry:
                    self.cached_model_telemetry = state.get("coordinator", {}).get("model_telemetry", {})
                    next_telemetry = now + 15.0
                else:
                    state.setdefault("coordinator", {})["model_telemetry"] = self.cached_model_telemetry
                state["ollama_models"] = list(self.ollama_models)
                state["ollama_error"] = self.ollama_error
                state["ollama_status_known"] = self.ollama_status_known
                self.latest_state = state
                self.snapshot_error = ""
            except Exception as exc:
                self.snapshot_error = f"{type(exc).__name__}: {exc}"
            self.closing.wait(2.0)

    def _poll_ollama(self) -> None:
        while not self.closing.is_set():
            try:
                models, error = manager.available_models()
                self.ollama_models = list(models)
                self.ollama_error = error
                self.ollama_status_known = True
            except Exception as exc:
                self.ollama_models = []
                self.ollama_error = f"{type(exc).__name__}: {exc}"
                self.ollama_status_known = True
            self.closing.wait(20.0)

    @staticmethod
    def _model_text_setting() -> bool:
        try:
            setting = json.loads(MODEL_TEXT_SETTINGS.read_text(encoding="utf-8"))
            return isinstance(setting, dict) and setting.get("store_model_text") is True
        except (OSError, json.JSONDecodeError):
            return False

    def _save_model_text_setting(self) -> None:
        MODEL_TEXT_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        temporary = MODEL_TEXT_SETTINGS.with_suffix(".json.tmp")
        try:
            payload = json.dumps({"store_model_text": bool(self.store_model_text.get())},
                                 indent=2, ensure_ascii=False) + "\n"
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, MODEL_TEXT_SETTINGS)
            self.ai_text_status.set("Майбутні тексти зберігаються з обмеженням і фільтром секретів." \
                if self.store_model_text.get() else "Нові виклики зберігають лише метадані; старі записи не змінено.")
        except OSError as exc:
            self.store_model_text.set(not self.store_model_text.get())
            self.ai_text_status.set(f"Налаштування не збережено: {type(exc).__name__}: {exc}")

    def _schedule_save_geometry(self, event: Any = None) -> None:
        if event and event.widget is not self.root:
            return
        if self._geometry_after:
            try:
                self.root.after_cancel(self._geometry_after)
            except tk.TclError:
                pass
        self._geometry_after = self.root.after(600, self._save_geometry)

    def _save_geometry(self) -> None:
        self._geometry_after = None
        if not self.root.winfo_exists() or self.root.state() == "iconic":
            return
        UI_STATE.parent.mkdir(parents=True, exist_ok=True)
        UI_STATE.write_text(json.dumps({"width": self.root.winfo_width(), "height": self.root.winfo_height()}, indent=2) + "\n", encoding="utf-8")

    def _system_cpu(self) -> str:
        if os.name != "nt":
            return "CPU —"
        try:
            import ctypes
            from src.agent.autonomous_gui import _FILETIME, _filetime
            kernel = ctypes.windll.kernel32
            idle, ktime, utime = _FILETIME(), _FILETIME(), _FILETIME()
            if not kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(ktime), ctypes.byref(utime)):
                return "CPU —"
            current = (_filetime(idle), _filetime(ktime) + _filetime(utime))
            previous, self.cpu_prior = self.cpu_prior, current
            if previous is None or current[1] <= previous[1]:
                return "CPU —"
            total = current[1] - previous[1]
            return f"CPU {max(0, min(100, round((total - current[0] + previous[0]) * 100 / total)))}%"
        except Exception:
            return "CPU —"

    @staticmethod
    def _gb(value: Any) -> str:
        try:
            return f"{int(value) / (1024 ** 3):.1f}"
        except (TypeError, ValueError):
            return "—"

    @staticmethod
    def _mib_to_gb(value: Any) -> str:
        try:
            return f"{float(value) / 1024:.1f}"
        except (TypeError, ValueError):
            return "—"

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.configure(state="disabled")

    def _set_lamp(self, variable: tk.StringVar, dot: tk.Label, title: str,
                  level: str, label: str, detail: str = "") -> None:
        variable.set(f"{title}: {label}")
        dot.configure(fg=COLORS.get(level, COLORS["gray"]))
        if detail:
            dot.bind("<Enter>", lambda _event, d=detail: self._show_lamp_tip(dot, d))
            dot.bind("<Leave>", lambda _event: self._hide_lamp_tip())

    def _show_lamp_tip(self, widget: tk.Widget, detail: str) -> None:
        self._hide_lamp_tip()
        self.lamp_tip = tip = tk.Toplevel(widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{widget.winfo_rootx()+10}+{widget.winfo_rooty()+22}")
        tk.Label(tip, text=detail[:700], justify="left", wraplength=420,
                 bg="#fffbe6", fg="#263746", relief="solid", borderwidth=1,
                 padx=7, pady=5, font=("Segoe UI", 8)).pack()

    def _hide_lamp_tip(self) -> None:
        tip = getattr(self, "lamp_tip", None)
        if tip:
            tip.destroy()
            self.lamp_tip = None

    def _render_queue(self, rows: list[dict[str, Any]]) -> None:
        selected = self.queue.selection()
        try:
            yview = self.queue.yview()
        except tk.TclError:
            yview = (0.0, 1.0)
        for item in self.queue.get_children():
            self.queue.delete(item)
        sorted_rows = sorted(rows[-600:], key=lambda row: self._queue_sort_key(row, self._queue_sort_column),
                             reverse=self._queue_sort_reverse)
        for row in sorted_rows:
            status = str(row.get("status", ""))
            self.queue.insert("", "end", iid=str(row.get("id")), text=row.get("id", ""),
                values=(row.get("stage", ""), status,
                    f"{row.get('attempts', 0)}/{row.get('retry_limit', 0)}",
                    str(row.get("updated_utc", ""))[:16].replace("T", " ")), tags=(status,))
        if selected and self.queue.exists(selected[0]):
            self.queue.selection_set(selected[0])
        if yview:
            self.queue.yview_moveto(yview[0])

    @staticmethod
    def _queue_status_rank(value: Any) -> tuple[int, str]:
        status = str(value or "").upper()
        if status == "DONE": return (0, status)
        if status in {"RUNNING", "LEASED", "IN_PROGRESS"}: return (1, status)
        if status == "PENDING": return (2, status)
        if status == "BLOCKED": return (3, status)
        if status.startswith("WAITING") or status.startswith("WAIT_"): return (4, status)
        return (5, status)

    @classmethod
    def _queue_sort_key(cls, row: dict[str, Any], column: str) -> Any:
        if column == "#0":
            return (str(row.get("id") or "").casefold(), str(row.get("agent") or "").casefold())
        if column == "stage":
            return str(row.get("stage") or "").casefold()
        if column == "status":
            return cls._queue_status_rank(row.get("status"))
        if column == "attempts":
            try: return int(row.get("attempts") or 0)
            except (TypeError, ValueError): return -1
        if column == "updated":
            return _parse_time(row.get("updated_utc")) or datetime.min.replace(tzinfo=timezone.utc)
        return str(row.get(column) or "").casefold()

    def _sort_queue(self, column: str) -> None:
        if column == self._queue_sort_column:
            self._queue_sort_reverse = not self._queue_sort_reverse
        else:
            self._queue_sort_column = column
            self._queue_sort_reverse = False
        for key, title in self._queue_sort_titles.items():
            suffix = (" ▼" if self._queue_sort_reverse else " ▲") if key == column else ""
            self.queue.heading(key, text=title + suffix, command=lambda col=key: self._sort_queue(col))
        self._render_queue((self.latest_state or {}).get("tasks", []))

    def _render_logs(self, events: list[dict[str, Any]]) -> None:
        lines = []
        for row in reversed(events[-MAX_VISIBLE_LOG_LINES:]):
            detail = row.get("detail_json", "{}")
            try:
                detail = json.dumps(json.loads(detail), ensure_ascii=False, separators=(",", ": "))
            except (TypeError, json.JSONDecodeError):
                pass
            lines.append(f"{str(row.get('created_utc',''))[:19]} {row.get('severity','INFO'):<7} {row.get('event','')} {row.get('task_id') or ''} {detail}")
        self._set_text(self.log_text, "\n".join(lines))
        self.log_text.see("end")

    def _render_evidence(self, state: dict[str, Any]) -> None:
        project = state.get("project", {})
        lines = ["ДОКАЗИ ПРОЄКТУ", f"Інвентаризованих джерел: {project.get('evidence_count', 0)}",
            f"Результатів моделей: {project.get('model_run_count', 0)}", "", "ВОРОТА F0–F9"]
        lines.extend(f"{row.get('stage')}: {row.get('status')}" for row in project.get("stage_gates", []))
        lines.extend(["", "ЗБЕРЕЖЕНІ АРТЕФАКТИ"])
        for item in state.get("artifacts", [])[:50]:
            lines.append(f"[{item.get('acceptance')}] {item.get('path')} · SHA-256 {item.get('sha256')}")
        if len(lines) <= 9:
            lines.append("Підтверджених артефактів поки немає.")
        self._set_text(self.evidence_text, "\n".join(lines))

    def _render_reports(self) -> None:
        for item in self.reports.get_children():
            self.reports.delete(item)
        root = PROJECT_ROOT / "reports" / "periodic"
        rows = []
        for period in ("daily", "weekly", "monthly"):
            folder = root / period
            if folder.is_dir():
                rows.extend((period, p.stat().st_mtime, p) for p in folder.glob("*.md"))
                rows.extend((period, p.stat().st_mtime, p) for p in folder.glob("*.json"))
        for period, modified, path in sorted(rows, key=lambda row: row[1], reverse=True)[:200]:
            relative = str(path.relative_to(PROJECT_ROOT))
            self.reports.insert("", "end", iid=relative, values=(period,
                datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M"), relative))

    def _render_ai(self, state: dict[str, Any]) -> None:
        coordinator = state.get("coordinator", {})
        telemetry = coordinator.get("model_telemetry", {})
        derived = derive_ai_status(state)
        name = derived.get("model") or ((telemetry.get("recent_runs") or [{}])[0].get("model"))
        role = derived.get("role") or ((telemetry.get("recent_runs") or [{}])[0].get("role"))
        self.ai_model_role.set(f"Активна/остання модель: {name or '—'} · роль: {role or '—'} · {derived['label']}")
        periods = telemetry.get("periods", {})
        for label, key in (("Сьогодні", "today"), ("7 днів", "seven_days"), ("Увесь період", "all")):
            stats = periods.get(key, {})
            in_tokens, out_tokens = stats.get("input_tokens"), stats.get("output_tokens")
            tokens = f"{in_tokens if in_tokens is not None else '—'}/{out_tokens if out_tokens is not None else '—'}"
            self.ai_stat_vars[label].set(
                f"{label}: {stats.get('requests', 0)} зап. / {stats.get('responses', 0)} відп. · "
                f"усп. {stats.get('successful', 0)} · пом. {stats.get('failed', 0)}\n"
                f"сер. {self._duration(stats.get('average_ms'))} · макс. {self._duration(stats.get('maximum_ms'))} · in/out {tokens}")
        self.ai_activity.set(f"Остання активність: {telemetry.get('last_activity_utc') or '—'}")
        models = ["Усі"] + sorted({str(row.get("model")) for row in telemetry.get("recent_runs", []) if row.get("model")})
        if tuple(self.ai_model_combo["values"]) != tuple(models):
            self.ai_model_combo["values"] = models
        self.ai_rows = {str(row.get("id")): row for row in telemetry.get("recent_runs", [])}
        self._render_ai_runs()
        self._render_director(state, derived)

    def _render_director(self, state: dict[str, Any], ai: dict[str, Any]) -> None:
        director = state.get("director", {})
        config = director.get("config", {})
        if config and not getattr(self, "_director_settings_pending", False):
            self.director_auto.set(bool(config.get("enabled", 1)))
            seconds = int(config.get("interval_seconds") or 1800)
            self.director_interval.set(next((label for label, value in self.director_intervals.items()
                                             if value == seconds), "30 хвилин"))
        last_run = _parse_time(config.get("last_run_utc"))
        next_run = _parse_time(config.get("next_run_utc"))
        last_label = last_run.astimezone().strftime("%Y-%m-%d %H:%M") if last_run else "ще не запускався"
        next_label = next_run.astimezone().strftime("%Y-%m-%d %H:%M") if next_run else "вимкнено"
        reason = _short(config.get("last_reason") or "Очікується запит або запланований інтервал.", 145)
        worker_task_id = (state.get("control") or {}).get("current_task") or ""
        worker_task = next((row for row in state.get("tasks", []) if str(row.get("id")) == str(worker_task_id)), {})
        director_task = (worker_task_id if "director" in str(worker_task.get("agent") or "").casefold()
                         else config.get("last_task_id") or "немає")
        self.director_summary.set(
            f"Ollama: {ai.get('label','—')} · поточна задача Director: {_short(director_task,30)} · "
            f"останнє рішення: {config.get('last_result','NOT_RUN')} ({last_label}) · "
            f"наступний аналіз: {next_label} · {reason}")
        self.director_decision_rows = list(director.get("decisions", []))
        self._render_director_decisions()

    def _render_director_decisions(self) -> None:
        selected = self.director_decisions.selection()
        try:
            yview = self.director_decisions.yview()
        except tk.TclError:
            yview = (0.0, 1.0)
        for item in self.director_decisions.get_children():
            self.director_decisions.delete(item)
        status_filter = self.director_decision_filter.get()
        for index, row in enumerate(self.director_decision_rows):
            if status_filter != "Усі" and row.get("decision") != status_filter:
                continue
            iid = str(row.get("request_id") or index)
            timestamp = _parse_time(row.get("created_utc"))
            displayed_time = timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S") if timestamp else str(row.get("created_utc") or "")
            self.director_decisions.insert("", "end", iid=iid, values=(displayed_time,
                row.get("decision", ""), _short(row.get("task_id"), 44), row.get("model") or "—",
                _short(row.get("reason"), 150)))
        if selected and self.director_decisions.exists(selected[0]):
            self.director_decisions.selection_set(selected[0])
        if yview:
            self.director_decisions.yview_moveto(yview[0])

    def _save_director_settings(self) -> None:
        if getattr(self, "_director_settings_pending", False):
            return
        self._director_settings_pending = True
        enabled = self.director_auto.get()
        interval = self.director_intervals.get(self.director_interval.get(), 1800)

        def save() -> None:
            try:
                from src.agent import director_scheduler
                director_scheduler.configure(enabled, interval, db_path=manager.STATE_DB)
                result = "Автоматичне планування увімкнено" if enabled else "Автоматичне планування вимкнено"
            except Exception as exc:
                result = f"Не вдалося зберегти налаштування Director: {type(exc).__name__}: {exc}"
            self.director_action_results.put(("settings", result))

        threading.Thread(target=save, name="ncdr-save-director-settings", daemon=True).start()

    def request_director_analysis(self) -> None:
        if getattr(self, "_director_request_pending", False):
            return
        self._director_request_pending = True
        self.director_button.configure(state="disabled")

        def request() -> None:
            try:
                from src.agent import director_scheduler
                request_id = director_scheduler.request_manual(db_path=manager.STATE_DB)
                control = manager._control()
                if control.get("desired_state") != "RUNNING":
                    manager.set_control("RUNNING")
                launched = self._spawn_worker() if not manager.worker_lock_held() else None
                message = (f"Запит {request_id} збережено; Director обробить його у Worker" +
                           (f" PID {launched.pid}" if launched else "."))
                self.director_action_results.put(("request", message))
            except Exception as exc:
                self.director_action_results.put(("request_error",
                    f"Запит не поставлено: {type(exc).__name__}: {exc}"))

        threading.Thread(target=request, name="ncdr-director-manual-request", daemon=True).start()

    def _process_director_action_results(self) -> None:
        while True:
            try:
                kind, message = self.director_action_results.get_nowait()
            except queue.Empty:
                return
            if kind == "settings":
                self._director_settings_pending = False
            if kind in {"request", "request_error"}:
                self._director_request_pending = False
                self.director_button.configure(state="normal")
            self.command_status.set(message)

    @staticmethod
    def _duration(value: Any) -> str:
        if value is None:
            return "—"
        return f"{float(value)/1000:.1f}s"

    def _render_ai_runs(self) -> None:
        selected = self.ai_runs.selection()
        try:
            yview = self.ai_runs.yview()
        except tk.TclError:
            yview = (0.0, 1.0)
        for item in self.ai_runs.get_children():
            self.ai_runs.delete(item)
        model_filter = self.ai_model_filter.get()
        status_filter = self.ai_status_filter.get()
        period = self.ai_period_filter.get()
        now = datetime.now(timezone.utc)
        rendered: set[str] = set()
        for iid, row in list(self.ai_rows.items())[:300]:
            created = _parse_time(row.get("created_utc"))
            if period == "Сьогодні" and (not created or created.date() != now.date()):
                continue
            if period == "7 днів" and (not created or created < now - timedelta(days=7)):
                continue
            if model_filter != "Усі" and row.get("model") != model_filter:
                continue
            if status_filter != "Усі" and row.get("status") != status_filter:
                continue
            tokens = f"{row.get('input_tokens') if row.get('input_tokens') is not None else '—'}/" \
                     f"{row.get('output_tokens') if row.get('output_tokens') is not None else '—'}"
            task = str(row.get("task_id") or "")
            self.ai_runs.insert("", "end", iid=iid, values=(str(row.get("created_utc", ""))[:16].replace("T", " "),
                row.get("model", ""), row.get("role", ""), _short(task, 52),
                self._duration(row.get("elapsed_ms")), row.get("status", ""), tokens), tags=(row.get("status", ""),))
            rendered.add(iid)
        if selected and selected[0] in rendered:
            self.ai_runs.selection_set(selected)
            self.ai_runs.focus(selected[0])
            self.ai_runs.yview_moveto(yview[0])
            if self.show_model_text.get():
                self._load_selected_model_text()

    def _load_selected_model_text(self, _event: Any = None) -> None:
        selection = self.ai_runs.selection()
        if not self.show_model_text.get():
            self.ai_text_status.set("Тексти приховано; у базі є лише фактично збережені значення.")
            self._set_text(self.ai_request_text, "Запит не відкрито")
            self._set_text(self.ai_response_text, "Відповідь не відкрита")
            return
        if not selection:
            return
        selected_row = self.ai_rows.get(selection[0], {})
        if not selected_row.get("text_available"):
            self.ai_text_status.set("Для цього виклику збереглися лише метадані; повного тексту немає.")
            self._set_text(self.ai_request_text, "Повний запит не зберігався.")
            self._set_text(self.ai_response_text, "Повна відповідь не зберігалася.")
            return
        try:
            record_id = int(selection[0])
        except ValueError:
            return
        self.text_request_id += 1
        request_id = self.text_request_id
        self.ai_text_status.set("Читаю вибраний запис…")
        threading.Thread(target=self._read_model_text, args=(request_id, record_id), daemon=True).start()

    def _read_model_text(self, request_id: int, record_id: int) -> None:
        try:
            db = manager.STATE_DB.resolve()
            uri = "file:" + quote(db.as_posix(), safe="/:\\") + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=3)) as conn:
                conn.execute("PRAGMA query_only=ON")
                columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(research_runs)")}
                needed = {"input_json", "response_text", "parsed_json"}
                if not needed <= columns:
                    raise RuntimeError("Фактична схема не має полів повного тексту")
                row = conn.execute("SELECT input_json,response_text,parsed_json FROM research_runs WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise RuntimeError("Запис не знайдено")
            try:
                input_value = json.loads(row[0] or "{}")
                request = str(input_value.get("prompt", "")) if isinstance(input_value, dict) else ""
            except json.JSONDecodeError:
                request = ""
            response = str(row[1] or "")
            if not response and row[2]:
                response = str(row[2])
            payload = {"request": _redact(request) if request else "Повний запит не зберігався.",
                       "response": _redact(response) if response else "Повна відповідь не зберігалася."}
            self.text_results.put((request_id, payload, "Текст прочитано локально; типові секрети приховано."))
        except Exception as exc:
            self.text_results.put((request_id, None, f"Не вдалося прочитати: {type(exc).__name__}: {exc}"))

    def _process_text_results(self) -> None:
        latest = None
        while True:
            try:
                latest = self.text_results.get_nowait()
            except queue.Empty:
                break
        if not latest or latest[0] != self.text_request_id:
            return
        _, data, message = latest
        self.ai_text_status.set(message)
        if data:
            self._set_text(self.ai_request_text, data["request"])
            self._set_text(self.ai_response_text, data["response"])

    def _refresh_progress(self, state: dict[str, Any]) -> None:
        progress = verified_progress(state)
        self.progress_values["Загалом"].set(f"{progress['percent']}% · {progress['earned']}/{progress['total']}")
        self._draw_progress("Загалом", progress["percent"])
        for name, item in progress["components"].items():
            if name in self.progress_bars:
                self.progress_values[name].set(f"{item['percent']}% · {item['earned']}/{item['total']}")
                self._draw_progress(name, item["percent"])
        self.physical_note.set("Фізична сумісність: не перевірено")
        osm = state.get("national_osm_progress", {})
        self._set_osm_progress(osm.get("percent", 0))
        self.osm_value.set(str(osm.get("message", "Стан OSM недоступний")))

    def _refresh_command(self, state: dict[str, Any], worker_alive: bool) -> None:
        control = state.get("control", {})
        desired = control.get("desired_state", "STOPPED")
        task = str(control.get("current_task") or "")
        diagnosis = state.get("queue_diagnosis", {})
        if task:
            self.command_status.set(f"Виконується {task} · checkpoint зберігається у SQLite")
        elif desired == "RUNNING" and worker_alive and diagnosis.get("eligible_task_ids"):
            self.command_status.set("Worker активний · заплановано наступну доступну задачу")
        elif desired == "RUNNING" and worker_alive:
            self.command_status.set("Очікування продовження: " + _short(diagnosis.get("message", "планувальник перевіряє цілі"), 140))
        elif desired == "PAUSED":
            if worker_alive and task:
                self.command_status.set("Пауза запитана · поточна задача завершує checkpoint")
            else:
                self.command_status.set("Дослідження на паузі · черга і результати збережені")
        elif desired == "STOPPED":
            self.command_status.set("Worker зупинений · дослідження можна відновити")
        else:
            self.command_status.set("Worker завершує поточне завдання")

    def _refresh_control_button(self, state: dict[str, Any], worker_alive: bool) -> None:
        control = state.get("control", {})
        diagnosis = state.get("queue_diagnosis", {})
        desired = str(control.get("desired_state") or "STOPPED")
        current_id = str(control.get("current_task") or "")
        rows = state.get("tasks", [])
        current = next((row for row in rows if str(row.get("id")) == current_id), None)
        active_task = bool(current and current.get("status") == "LEASED")
        if desired == "PAUSED" and worker_alive and active_task:
            mode, reason = "RUNNING", "Пауза запитана · поточна задача завершує checkpoint"
        elif desired == "PAUSED":
            mode, reason = "PAUSED", "Дослідження на паузі · checkpoint збережено"
        elif desired == "RUNNING" and not worker_alive:
            mode, reason = "ERROR", str(control.get("last_error") or "Worker не тримає активне блокування")
        elif desired == "RUNNING" and worker_alive and (active_task or diagnosis.get("eligible_task_ids")):
            mode = "RUNNING"
            reason = (f"Виконується {_short(current_id, 48)}" if active_task else "Worker підбирає доступну задачу")
        elif desired == "RUNNING" and worker_alive:
            mode = "BLOCKED"
            reason = str(control.get("last_error") or diagnosis.get("message") or "Немає придатних задач")
        elif desired == "STOPPING":
            mode, reason = "ERROR", "Worker завершує задачу та зберігає стан"
        elif diagnosis.get("eligible_task_ids"):
            mode, reason = "READY", "Є придатна задача · натисніть ▶ для запуску"
        elif desired == "STOPPED":
            mode, reason = "STOPPED", "Worker зупинений · ▶ відновить його для роботи або діагностики"
        else:
            mode = "BLOCKED"
            reason = str(control.get("last_error") or diagnosis.get("message") or "Немає підтвердженої наступної задачі")
        self._control_mode = mode
        self.control_reason.set(_short(reason, 92))
        if mode == "RUNNING":
            self.play_pause_button.configure(text="⏸", bg="#bd3932", activebackground="#9f2e29")
        elif mode == "PAUSED":
            self.play_pause_button.configure(text="▶", bg="#d69a12", activebackground="#b98200")
        elif mode in {"READY", "STOPPED"}:
            self.play_pause_button.configure(text="▶", bg="#07845f", activebackground="#056b4c")
        else:
            self.play_pause_button.configure(text="▶", bg="#bd3932", activebackground="#9f2e29")
        should_blink = mode == "RUNNING" and active_task and worker_alive
        if should_blink and not self._blink_after_id:
            self._blink_phase = False
            self._blink_after_id = self.root.after(500, self._animate_play_pause)
        elif not should_blink and self._blink_after_id:
            try:
                self.root.after_cancel(self._blink_after_id)
            except tk.TclError:
                pass
            self._blink_after_id = None
        if not should_blink:
            if mode == "RUNNING":
                self.play_pause_button.configure(bg="#bd3932", activebackground="#9f2e29")
            elif mode == "PAUSED":
                self.play_pause_button.configure(bg="#d69a12", activebackground="#b98200")
            elif mode in {"READY", "STOPPED"}:
                self.play_pause_button.configure(bg="#07845f", activebackground="#056b4c")
            else:
                self.play_pause_button.configure(bg="#bd3932", activebackground="#9f2e29")
        self.stop_button.configure(state="normal" if worker_alive or desired in {"RUNNING", "PAUSED", "STOPPING"} else "disabled")

    def _animate_play_pause(self) -> None:
        self._blink_after_id = None
        if self.closing.is_set() or self._control_mode != "RUNNING":
            return
        current = (self.latest_state or {}).get("control", {}).get("current_task")
        active = any(row.get("id") == current and row.get("status") == "LEASED"
                     for row in (self.latest_state or {}).get("tasks", []))
        if not active or not manager.worker_lock_held():
            self.play_pause_button.configure(bg="#bd3932", activebackground="#9f2e29")
            return
        self._blink_phase = not self._blink_phase
        color = "#e77770" if self._blink_phase else "#bd3932"
        self.play_pause_button.configure(bg=color, activebackground="#9f2e29")
        self._blink_after_id = self.root.after(650, self._animate_play_pause)

    def refresh(self) -> None:
        now = time.monotonic()
        self._process_text_results()
        self._process_director_action_results()
        state = self.latest_state
        if state is None:
            if self.snapshot_error:
                self.command_status.set("Не вдалося оновити стан: " + _short(self.snapshot_error, 140))
            self.root.after(700, self.refresh)
            return
        control = state.get("control", {})
        desired = control.get("desired_state", "STOPPED")
        pid = control.get("worker_pid")
        worker_alive = manager.worker_lock_held()
        worker_level = "green" if worker_alive and desired in {"RUNNING", "STOPPING"} else "red"
        worker_label = ("працює" if worker_level == "green" else
                        "на паузі" if worker_alive and desired == "PAUSED" else "зупинений")
        self._set_lamp(self.worker_var, self.worker_dot, "Worker", worker_level, worker_label,
                       f"Worker PID: {pid or 'невідомий'}")
        ai = derive_ai_status(state)
        ai_short = {"green": "запит", "yellow": "очікує", "red": "помилка", "gray": "невідомо"}.get(ai["level"], ai["label"])
        self._set_lamp(self.ai_var, self.ai_dot, "Локальний ШІ", ai["level"], ai_short,
                       str(ai.get("error") or ai["label"]))
        research_state = dict(state)
        research_state["worker_lock_held"] = worker_alive
        research = derive_research_status(research_state)
        research_short = {"green": "виконує", "yellow": "планування", "red": "заблоковано"}.get(
            research["level"], research["label"])
        self._set_lamp(self.research_var, self.research_dot, "Дослідження", research["level"],
                       research_short, research["label"])

        counts = state.get("project", {}).get("task_counts", {})
        self.metric_vars[0].set(" · ".join(f"{name} {counts.get(name, 0)}" for name in ("DONE", "BLOCKED", "PENDING", "LEASED")))
        tasks = state.get("tasks", [])
        current_id = str(control.get("current_task") or "")
        task_row = next((row for row in tasks if row.get("id") == current_id), None)
        if current_id:
            full = current_id + (f"\n{task_row.get('hypothesis','')}" if task_row else "")
        else:
            full = str(state.get("queue_diagnosis", {}).get("message", "Черга перевірена"))
        self.current_task_full = full
        short_title = _short(current_id, 34) if current_id else _short(full, 34)
        short_action = _short(task_row.get("hypothesis") if task_row else
                              state.get("queue_diagnosis", {}).get("status", ""), 34)
        self.metric_vars[1].set(short_title + "\n" + short_action)
        resources = state.get("resources", {})
        ram, gpu = resources.get("ram", {}), resources.get("gpu") or {}
        gpu_memory = (f"{self._mib_to_gb(gpu.get('memory_used_mib'))}/{self._mib_to_gb(gpu.get('memory_total_mib'))} GB"
                      if gpu else "—/— GB")
        self.metric_vars[2].set(f"{self._system_cpu()} · RAM {self._gb(ram.get('used_bytes'))}/{self._gb(ram.get('total_bytes'))} GB · GPU {gpu_memory}")
        model_name = ai.get("model") or (state.get("coordinator", {}).get("model_telemetry", {}).get("recent_runs") or [{}])[0].get("model")
        elapsed = ai.get("elapsed_seconds")
        self.metric_vars[3].set(f"{model_name or 'Ollama'} · {ai['label']}" + (f" · {int(elapsed)}s" if elapsed is not None else ""))
        self._refresh_command(state, worker_alive)

        if now - self.last_refresh >= 2:
            self._render_queue(tasks)
            self._render_logs(state.get("events", []))
            self._render_evidence(state)
            self._render_reports()
            self._render_ai(state)
            self._refresh_progress(state)
            self.last_refresh = now
        self._refresh_control_button(state, worker_alive)
        heartbeat = (task_row.get("heartbeat_utc") if task_row else None) or control.get("updated_utc")
        completed = next((row for row in tasks if row.get("status") == "DONE"), None)
        telemetry = state.get("coordinator", {}).get("model_telemetry", {})
        heartbeat_time = _parse_time(heartbeat)
        ai_time = _parse_time(telemetry.get("last_activity_utc"))
        heartbeat_label = heartbeat_time.strftime("%H:%M UTC") if heartbeat_time else "—"
        ai_label = ai_time.strftime("%H:%M UTC") if ai_time else "—"
        completed_label = _short(completed.get("id"), 36) if completed else "—"
        self.footer_var.set(f"PID {pid or '—'} · heartbeat {heartbeat_label} · DONE {completed_label} · AI {ai_label}")
        self.root.after(1000, self.refresh)

    def _system_cpu(self) -> str:
        if os.name != "nt":
            return "CPU —"
        try:
            import ctypes
            from src.agent.autonomous_gui import _FILETIME, _filetime
            kernel = ctypes.windll.kernel32
            idle, kernel_time, user_time = _FILETIME(), _FILETIME(), _FILETIME()
            if not kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel_time), ctypes.byref(user_time)):
                return "CPU —"
            current = (_filetime(idle), _filetime(kernel_time) + _filetime(user_time))
            prior, self.cpu_prior = self.cpu_prior, current
            if prior is None or current[1] <= prior[1]:
                return "CPU —"
            total = current[1] - prior[1]
            return f"CPU {max(0, min(100, round((total - current[0] + prior[0]) * 100 / total)))}%"
        except Exception:
            return "CPU —"

    def _selected_report(self) -> Path | None:
        selection = self.reports.selection()
        if not selection:
            messagebox.showinfo("Звіт не вибрано", "Виберіть звіт у списку.", parent=self.root)
            return None
        path = (PROJECT_ROOT / self.reports.item(selection[0], "values")[2]).resolve()
        reports_root = (PROJECT_ROOT / "reports").resolve()
        if (path != reports_root and reports_root not in path.parents) or not path.is_file():
            messagebox.showerror("Некоректний шлях", "Звіт не знайдено в папці результатів.", parent=self.root)
            return None
        return path

    def open_selected_report(self) -> None:
        path = self._selected_report()
        if path:
            try:
                os.startfile(str(path))
            except (AttributeError, OSError) as exc:
                messagebox.showerror("Не вдалося відкрити звіт", str(exc), parent=self.root)

    def export_selected_report(self) -> None:
        source = self._selected_report()
        if not source:
            return
        destination = filedialog.asksaveasfilename(parent=self.root, initialfile=source.name,
            defaultextension=source.suffix, filetypes=[("Звіт", "*.md *.json"), ("Усі файли", "*.*")])
        if destination:
            try:
                import shutil
                shutil.copy2(source, destination)
                self.command_status.set("Експортовано копію звіту")
            except OSError as exc:
                messagebox.showerror("Не вдалося експортувати", str(exc), parent=self.root)

    def _show_task_detail(self, text: str) -> None:
        if text:
            messagebox.showinfo("Повна назва / стан задачі", text, parent=self.root)

    def _show_selected_task(self) -> None:
        selected = self.queue.selection()
        if not selected:
            return
        row = next((item for item in (self.latest_state or {}).get("tasks", []) if item.get("id") == selected[0]), None)
        self._show_task_detail(json.dumps(row, ensure_ascii=False, indent=2) if row else str(selected[0]))

    def _spawn_worker(self):
        control = manager._control()
        if manager.worker_lock_held():
            return None
        log_path = PROJECT_ROOT / "work" / "autonomous_manager" / "worker_console.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            flags = (getattr(__import__("subprocess"), "DETACHED_PROCESS", 0) |
                     getattr(__import__("subprocess"), "CREATE_NEW_PROCESS_GROUP", 0) |
                     getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0))
            process = __import__("subprocess").Popen([__import__("sys").executable, "-X", "utf8", "-B", "-m", "src.agent.autonomous_manager", "worker"],
                cwd=PROJECT_ROOT, stdin=__import__("subprocess").DEVNULL, stdout=handle,
                stderr=__import__("subprocess").STDOUT, creationflags=flags, close_fds=True,
                env=manager.python_utf8_environment())
        return process

    def start(self) -> None:
        try:
            prepared = manager.prepare_research_request()
            control = manager._control()
            if control.get("desired_state") != "RUNNING":
                manager.set_control("RUNNING")
            if manager.worker_lock_held():
                self.command_status.set("Worker уже працює; дубль не запускався")
                return
            process = self._spawn_worker()
            queue_state = prepared.get("queue", {})
            if not prepared.get("can_run"):
                self.command_status.set("Worker запускається для діагностики: " +
                    _short(queue_state.get("message") or "черга без готових задач", 140))
            else:
                self.command_status.set(f"Створено Worker PID {process.pid}" if process else
                    f"Worker уже працює · PID {control.get('worker_pid')}")
        except Exception as exc:
            self.command_status.set(f"Запуск не пройшов: {type(exc).__name__}: {exc}")
            messagebox.showerror("Не вдалося запустити дослідження", str(exc), parent=self.root)

    def pause(self) -> None:
        manager.set_control("PAUSED")

    def resume(self) -> None:
        manager.set_control("RUNNING")
        if not manager.worker_lock_held():
            process = self._spawn_worker()
            self.command_status.set(f"Відновлено Worker PID {process.pid}" if process else "Worker уже працює")
        else:
            self.command_status.set("Дослідження продовжено з останнього checkpoint")

    def toggle_research(self) -> None:
        if self._control_mode == "RUNNING":
            self.pause()
        elif self._control_mode == "PAUSED":
            self.resume()
        elif self._control_mode in {"READY", "STOPPED"}:
            self.start()
        else:
            self.request_director_analysis()

    def stop(self) -> None:
        manager.set_control("STOPPING")
        if not manager._control().get("worker_pid"):
            manager.set_control("STOPPED")

    def emergency_stop(self) -> None:
        manager.set_control("STOPPING", emergency=True)
        if not manager._control().get("worker_pid"):
            manager.set_control("STOPPED", emergency=True)
        messagebox.showwarning("Аварійне зупинення",
            "Worker перериває активний процес і повертає checkpoint у чергу.", parent=self.root)

    def open_results(self) -> None:
        target = manager.REPORT_PATH if manager.REPORT_PATH.is_file() else PROJECT_ROOT / "reports"
        try:
            os.startfile(str(target))
        except (AttributeError, OSError) as exc:
            messagebox.showerror("Не вдалося відкрити результати", str(exc), parent=self.root)

    def close(self) -> None:
        self.closing.set()
        if self._blink_after_id:
            try:
                self.root.after_cancel(self._blink_after_id)
            except tk.TclError:
                pass
            self._blink_after_id = None
        self.root.destroy()


class _ToolTip:
    def __init__(self, widget: tk.Widget, text: str):
        self.widget, self.text, self.window = widget, text, None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _event: Any = None) -> None:
        if self.window or not self.text:
            return
        self.window = tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{self.widget.winfo_rootx()+10}+{self.widget.winfo_rooty()+20}")
        tk.Label(tip, text=self.text, wraplength=400, justify="left", bg="#fffbe6", fg="#263746",
                 relief="solid", borderwidth=1, padx=7, pady=5, font=("Segoe UI", 8)).pack()

    def hide(self, _event: Any = None) -> None:
        if self.window:
            self.window.destroy()
            self.window = None
