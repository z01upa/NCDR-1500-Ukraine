from __future__ import annotations

import json
import os
import csv
import sqlite3
import subprocess
import sys
import tkinter as tk
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
REPORTS = ROOT / "reports"
STATUS_PATH = WORK / "status.json"
LOCK_PATH = WORK / "runner.lock"
STATE_DB = WORK / "analysis.sqlite"
CONTROL_PATH = WORK / "control.json"
FINAL_STATUSES = {"EXPERIMENTS_EXHAUSTED", "BLOCKED_ORACLE", "ACTION_QUEUE_EXHAUSTED", "DECODER_CANDIDATE_REQUIRES_REVIEW"}
RUNNING_STATUSES = {"STARTING", "RUNNING", "WAITING_OLLAMA"}
LEGACY_MODEL_OUTPUT_DETAIL = "The local model did not produce a valid allow-listed action"


def is_legacy_model_output_stop(status: dict) -> bool:
    if status.get("status") != "BLOCKED_ORACLE":
        return False
    detail = str(status.get("detail", ""))
    if LEGACY_MODEL_OUTPUT_DETAIL in detail:
        return True
    report_path = REPORTS / "FINAL_REPORT.md"
    try:
        report = report_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    run_id = status.get("run_id")
    report_run = "- Run: " + chr(96) + str(run_id) + chr(96)
    return (LEGACY_MODEL_OUTPUT_DETAIL in report and
            (not run_id or report_run in report))

BG = "#F2F5FA"
CARD = "#FFFFFF"
INK = "#14213D"
MUTED = "#64748B"
BLUE = "#306CE8"
GREEN = "#16805D"
AMBER = "#B7791F"
RED = "#B9384B"
LINE = "#DCE3EE"


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def read_control_command() -> str:
    value = read_json(CONTROL_PATH)
    command = value.get("command", "RUN")
    return command if command in {"RUN", "PAUSE", "STOP"} else "RUN"


def write_control_command(command: str) -> None:
    if command not in {"RUN", "PAUSE", "STOP"}:
        raise ValueError("Unknown runner control command")
    write_json(CONTROL_PATH, {"command": command})


def prepare_runner_runtime() -> tuple[str | None, dict[str, str], str | None]:
    required_files = (
        ROOT / "DB_0",
        ROOT / "schema.sql",
        ROOT / "prompts" / "system_prompt.txt",
        ROOT / "research" / "roads" / "build_authoritative_corpus.py",
        ROOT / "ncdqwen" / "__init__.py",
        ROOT / "ncdqwen" / "runner.py",
        ROOT / "ncdqwen" / "db0.py",
        ROOT / "ncdqwen" / "ollama_client.py",
    )
    missing_files = [str(path) for path in required_files if not path.is_file()]
    if missing_files:
        details = "Research preflight failed; required file(s) missing:\n" + "\n".join(missing_files)
        return None, {}, details

    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(ROOT) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    setup = read_json(WORK / "machine_setup.json")
    base_executable = getattr(sys, "_base_executable", None)
    current_executable = None if getattr(sys, "frozen", False) else sys.executable
    candidates = (setup.get("python"), base_executable, current_executable)
    import_probe = (
        "import importlib,sys; "
        "assert sys.version_info >= (3,10), f'Python 3.10+ required; found {sys.version}'; "
        "[importlib.import_module(name) for name in ("
        "'sqlite3','ctypes','mmap','hashlib','statistics','bz2','gzip','lzma','zlib',"
        "'ncdqwen.db0','ncdqwen.ollama_client','ncdqwen.runner')]; "
        "print(sys.executable)"
    )
    failures: list[str] = []
    seen: set[str] = set()
    for raw_candidate in candidates:
        if not isinstance(raw_candidate, str) or not raw_candidate.strip():
            continue
        candidate = Path(raw_candidate).expanduser()
        if os.name == "nt" and candidate.name.lower() not in {"python.exe", "pythonw.exe"}:
            failures.append(f"{candidate}: rejected because it is not a Python interpreter executable")
            continue
        if candidate.name.lower() == "pythonw.exe":
            console_candidate = candidate.with_name("python.exe")
            if console_candidate.is_file():
                candidate = console_candidate
        candidate = candidate.resolve()
        candidate_text = str(candidate)
        if candidate_text in seen:
            continue
        seen.add(candidate_text)
        if not candidate.is_file():
            failures.append(f"{candidate_text}: Python executable not found")
            continue
        try:
            checked = subprocess.run(
                [candidate_text, "-c", import_probe], cwd=ROOT, env=environment,
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(f"{candidate_text}: {type(exc).__name__}: {exc}")
            continue
        if checked.returncode == 0:
            if setup.get("python") != candidate_text:
                setup["python"] = candidate_text
                write_json(WORK / "machine_setup.json", setup)
            return candidate_text, environment, None
        diagnostic = (checked.stderr or checked.stdout or "Python import check failed").strip()
        failures.append(f"{candidate_text}:\n{diagnostic[-1800:]}")
    details = "Python/runtime preflight failed. The research process was not started.\n\n" + "\n\n".join(failures)
    return None, environment, details


def active_runner_pid() -> int | None:
    status = read_json(STATUS_PATH)
    settled_statuses = FINAL_STATUSES | {"MODEL_OUTPUT_INVALID", "RESEARCH_BUDGET_EXHAUSTED"}
    if status.get("stage") == "FINISHED" and status.get("status") in settled_statuses:
        try:
            stale_final = time.time() - STATUS_PATH.stat().st_mtime > 5
        except OSError:
            stale_final = False
        if stale_final:
            try:
                # A final status is written after all runner work is committed.
                # Clear an orphaned lock so Start cannot stay disabled forever.
                LOCK_PATH.unlink(missing_ok=True)
                return None
            except OSError:
                pass
    try:
        pid = int(read_json(LOCK_PATH).get("pid", 0))
        if pid <= 0:
            return None
        if os.name == "nt":
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                if kernel.GetLastError() == 5:
                    return pid
                return None
            kernel.CloseHandle(ctypes.c_void_p(handle))
            return pid
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def open_path(path: Path) -> None:
    if not path.exists():
        return
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Dashboard:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("NCDR · дослідження бази DB_0")
        self.root.geometry("1180x820")
        self.root.minsize(980, 680)
        self.root.configure(bg=BG)
        self.process: subprocess.Popen | None = None
        self.worker_log = None
        self.model_process: subprocess.Popen | None = None
        self.model_log = None
        self.preparing_model = False
        self.preparing_detail = "Перевіряється доступність локальної моделі."
        self.status: dict = {}
        self.inventory: dict = {}
        self.road: dict = {}
        self.map_signature = None
        self.map_nodes: dict[str, tuple[float, float]] = {}
        self.map_edges: set[tuple[str, str]] = set()
        self.last_notice = "Підготовка локального робочого місця."
        self.last_stage = ""
        self.indeterminate = False
        self.auto_start_done = False
        self._build_style()
        self._build_ui()
        self.refresh()
        self.root.after(1200, self.auto_start)
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)

    def _build_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=CARD, foreground=INK, font=("Segoe UI", 10))
        style.configure("Muted.Card.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=INK, font=("Segoe UI Semibold", 21))
        style.configure("Metric.TLabel", background=CARD, foreground=INK, font=("Segoe UI Semibold", 22))
        style.configure("MetricName.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Section.TLabel", background=CARD, foreground=INK, font=("Segoe UI Semibold", 12))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI Semibold", 10))
        style.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", BLUE)])
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 9), background=CARD,
                        fieldbackground=CARD, foreground=INK, bordercolor=LINE)
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9), background="#EAF0F8",
                        foreground=INK, relief="flat")
        style.configure("Primary.TButton", font=("Segoe UI Semibold", 10), padding=(14, 9),
                        background=BLUE, foreground="white")
        style.map("Primary.TButton", background=[("active", "#2458C7"), ("disabled", "#A9BCE6")])
        style.configure("TButton", font=("Segoe UI Semibold", 9), padding=(11, 8))
        style.configure("Horizontal.TProgressbar", troughcolor="#E4EAF3", background=BLUE, thickness=12)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(22, 18, 22, 16))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="NCDR · DB_0", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="Локальне дослідження форматів навігаційної бази",
                  foreground=MUTED).pack(side="left", padx=(14, 0), pady=(8, 0))
        self.model_label = ttk.Label(header, text="Локальна модель: визначається…", foreground=MUTED)
        self.model_label.pack(side="right", pady=(8, 0))

        hero = ttk.Frame(outer, style="Card.TFrame", padding=(18, 14))
        hero.pack(fill="x", pady=(0, 12))
        hero.grid_columnconfigure(0, weight=1)
        self.state_label = tk.Label(hero, text="Підготовка", bg=CARD, fg=BLUE,
                                    font=("Segoe UI Semibold", 17), anchor="w")
        self.state_label.grid(row=0, column=0, sticky="w")
        self.stage_label = ttk.Label(hero, text="Очікування першого запуску", style="Muted.Card.TLabel")
        self.stage_label.grid(row=1, column=0, sticky="w", pady=(3, 8))
        self.progress = ttk.Progressbar(hero, mode="determinate", maximum=100)
        self.progress.grid(row=2, column=0, sticky="ew", padx=(0, 14))
        self.progress_hint = ttk.Label(hero, text="Етап 0 з 5", style="Muted.Card.TLabel")
        self.progress_hint.grid(row=2, column=1, sticky="e")
        self.detail_label = ttk.Label(hero, text="Підготовка локального робочого місця.", style="Muted.Card.TLabel")
        self.detail_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(7, 0))

        control_bar = ttk.Frame(hero, style="Card.TFrame")
        control_bar.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(11, 0))
        self.start_button = ttk.Button(control_bar, text="Запуск / продовжити", style="Primary.TButton",
                                       command=self.ensure_model_and_start)
        self.start_button.pack(side="left")
        self.pause_button = ttk.Button(control_bar, text="Пауза", command=self.pause_run)
        self.pause_button.pack(side="left", padx=(6, 0))
        self.stop_button = ttk.Button(control_bar, text="Зупинити", command=self.stop_run)
        self.stop_button.pack(side="left", padx=(6, 0))
        self.notice_label = ttk.Label(control_bar, text="", style="Muted.Card.TLabel")
        self.notice_label.pack(side="right", padx=(12, 0))

        self.pipeline = tk.Canvas(outer, height=88, bg=BG, highlightthickness=0)
        self.pipeline.pack(fill="x", pady=(0, 12))
        self.pipeline.bind("<Configure>", lambda _event: self.draw_pipeline())

        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        self.overview_tab = ttk.Frame(self.tabs, padding=2)
        self.map_tab = ttk.Frame(self.tabs, padding=2)
        self.details_tab = ttk.Frame(self.tabs, padding=2)
        self.tabs.add(self.overview_tab, text="Огляд")
        self.tabs.add(self.map_tab, text="Граф координат")
        self.tabs.add(self.details_tab, text="Перевірки й журнал")
        self._build_overview()
        self._build_map()
        self._build_details()

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Button(footer, text="Поточний звіт", command=lambda: open_path(REPORTS / "PROGRESS_REPORT.md")).pack(side="left", padx=(8, 0))
        ttk.Button(footer, text="Підсумковий звіт", command=lambda: open_path(REPORTS / "FINAL_REPORT.md")).pack(side="left", padx=(8, 0))
        ttk.Button(footer, text="Папка проєкту", command=lambda: open_path(ROOT)).pack(side="left", padx=(8, 0))

    def _build_overview(self) -> None:
        for column in range(4):
            self.overview_tab.grid_columnconfigure(column, weight=1, uniform="metric")
        self.overview_tab.grid_rowconfigure(1, weight=1)
        metrics = [
            ("records", "Перевірені блоки"),
            ("roads", "Дороги · підтверджений корпус"),
            ("objects", "Входження об'єктів"),
            ("experiments", "Виконано перевірок"),
        ]
        self.metric_values = {}
        for column, (key, label) in enumerate(metrics):
            card = ttk.Frame(self.overview_tab, style="Card.TFrame", padding=(14, 12))
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0), pady=(0, 10))
            ttk.Label(card, text=label, style="MetricName.TLabel").pack(anchor="w")
            value = ttk.Label(card, text="—", style="Metric.TLabel")
            value.pack(anchor="w", pady=(3, 0))
            self.metric_values[key] = value

        chart_card = ttk.Frame(self.overview_tab, style="Card.TFrame", padding=(14, 12))
        chart_card.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=(0, 8), pady=(0, 8))
        ttk.Label(chart_card, text="Структура блоків за типом і стисненням", style="Section.TLabel").pack(anchor="w")
        self.chart = tk.Canvas(chart_card, bg=CARD, height=280, highlightthickness=0)
        self.chart.pack(fill="both", expand=True, pady=(8, 0))
        self.chart.bind("<Configure>", lambda _event: self.draw_chart())

        facts_card = ttk.Frame(self.overview_tab, style="Card.TFrame", padding=(14, 12))
        facts_card.grid(row=1, column=2, columnspan=2, sticky="nsew", padx=(8, 0), pady=(0, 8))
        ttk.Label(facts_card, text="Що вже відомо", style="Section.TLabel").pack(anchor="w")
        self.facts_text = tk.Text(facts_card, wrap="word", bg=CARD, fg=INK, relief="flat",
                                  font=("Segoe UI", 10), padx=0, pady=8, height=8)
        self.facts_text.pack(fill="both", expand=True)
        self.facts_text.configure(state="disabled")

    def _build_details(self) -> None:
        self.details_tab.grid_columnconfigure(0, weight=1)
        for row in range(3):
            self.details_tab.grid_rowconfigure(row, weight=1)
        experiments_frame = ttk.Frame(self.details_tab, style="Card.TFrame", padding=(12, 10))
        experiments_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 7))
        experiments_frame.grid_columnconfigure(0, weight=1)
        experiments_frame.grid_rowconfigure(1, weight=1)
        ttk.Label(experiments_frame, text="Останні виконані перевірки", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.experiments = ttk.Treeview(experiments_frame, columns=("round", "tool", "result"), show="headings", height=7)
        self.experiments.heading("round", text="Крок")
        self.experiments.heading("tool", text="Перевірка")
        self.experiments.heading("result", text="Результат")
        self.experiments.column("round", width=70, anchor="center", stretch=False)
        self.experiments.column("tool", width=190, stretch=False)
        self.experiments.column("result", width=650)
        self.experiments.grid(row=1, column=0, sticky="nsew")

        hypotheses_frame = ttk.Frame(self.details_tab, style="Card.TFrame", padding=(12, 10))
        hypotheses_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 7))
        hypotheses_frame.grid_columnconfigure(0, weight=1)
        hypotheses_frame.grid_rowconfigure(1, weight=1)
        ttk.Label(hypotheses_frame, text="Гіпотези Qwen · ще не підтверджені", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.hypotheses = ttk.Treeview(hypotheses_frame,
                                      columns=("round", "claim", "expected", "falsifier"),
                                      show="headings", height=4)
        for key, title in (("round", "Крок"), ("claim", "Гіпотеза"),
                           ("expected", "Що має спостерігатися"), ("falsifier", "Що її спростує")):
            self.hypotheses.heading(key, text=title)
        self.hypotheses.column("round", width=60, anchor="center", stretch=False)
        self.hypotheses.column("claim", width=320)
        self.hypotheses.column("expected", width=320)
        self.hypotheses.column("falsifier", width=320)
        self.hypotheses.grid(row=1, column=0, sticky="nsew")

        log_frame = ttk.Frame(self.details_tab, style="Card.TFrame", padding=(12, 10))
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_header = ttk.Frame(log_frame, style="Card.TFrame")
        log_header.pack(fill="x", pady=(0, 8))
        ttk.Label(log_header, text="Журнал роботи", style="Section.TLabel").pack(side="left")
        ttk.Button(log_header, text="Експорт журналу", command=self.export_logs).pack(side="right")
        self.log_text = ScrolledText(log_frame, height=9, wrap="word", bg="#F8FAFD", fg=INK,
                                     relief="flat", font=("Consolas", 9), padx=10, pady=8)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

    def _build_map(self) -> None:
        self.map_tab.grid_columnconfigure(0, weight=1)
        self.map_tab.grid_rowconfigure(0, weight=1)
        card = ttk.Frame(self.map_tab, style="Card.TFrame", padding=(14, 12))
        card.grid(row=0, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)
        ttk.Label(card, text="Координатні вузли та переходи у списках доріг",
                  style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.map_canvas = tk.Canvas(card, bg="#FBFCFE", highlightthickness=1,
                                    highlightbackground=LINE, height=520)
        self.map_canvas.grid(row=1, column=0, sticky="nsew", pady=(10, 8))
        self.map_canvas.bind("<Configure>", lambda _event: self.draw_map())
        self.map_info = ttk.Label(card, text="Очікування дорожніх даних…", style="Muted.Card.TLabel")
        self.map_info.grid(row=2, column=0, sticky="w")
        self.map_caption = ttk.Label(
            card,
            text="Точки — підтверджені координати MULCOORD. Лінії — сусідні записи у дорожніх списках; це не відновлена геометрія доріг.",
            style="Muted.Card.TLabel",
        )
        self.map_caption.grid(row=3, column=0, sticky="w", pady=(5, 0))

    def status_text(self) -> tuple[str, str, str]:
        status = self.status.get("status", "READY")
        stage = self.status.get("stage", "READY")
        detail = self.status.get("detail", "Очікує запуску")
        if is_legacy_model_output_stop(self.status):
            status = "MODEL_OUTPUT_INVALID"
            detail = "Натисніть «Запуск / продовжити», щоб відновити збережений запуск. Еталонний буфер для цього не потрібен."
        labels = {
            "READY": "Готово до запуску", "STARTING": "Запуск", "RUNNING": "Виконується",
            "WAITING_OLLAMA": "Очікує локальну модель", "BLOCKED_ORACLE": "Потрібен зовнішній еталон",
            "MODEL_OUTPUT_INVALID": "Проблема у відповіді Qwen",
            "ACTION_QUEUE_EXHAUSTED": "Вичерпано різні перевірки",
            "RESEARCH_BUDGET_EXHAUSTED": "Дослідження можна продовжити",
            "PAUSED": "На паузі", "STOPPED_BY_USER": "Зупинено за запитом",
            "EXPERIMENTS_EXHAUSTED": "Перевірки вичерпано", "DECODER_CANDIDATE_REQUIRES_REVIEW": "Є кандидат для перевірки",
            "FAILED": "Зупинено через помилку",
        }
        stage_labels = {
            "READY": "Очікування першого запуску", "STARTING": "Підготовка та перевірка контрольної суми DB_0",
            "HASH_DB0": "Перевіряється цілісність DB_0",
            "INDEX_DB0": "Індексуються блоки та перевіряється відомий формат",
            "AUTHORITATIVE_ROADS": "Перебудовується підтверджений корпус доріг",
            "BASELINE_PROBES": "Виконуються базові контрольні перевірки",
            "QWEN_RESEARCH": "Qwen пропонує наступні обмежені перевірки",
            "MODEL_LOOP": "Підготовка локальної моделі", "FINISHED": "Формується підсумок",
            "ERROR": "Помилка під час роботи",
        }
        if active_runner_pid() and status not in FINAL_STATUSES:
            if status == "READY":
                status = "RUNNING"
                detail = "Фоновий процес продовжує аналіз"
        return labels.get(status, status.replace("_", " ")), stage_labels.get(stage, stage.replace("_", " ")), detail

    def _step_index(self) -> int:
        stage = self.status.get("stage", "READY")
        mapping = {"READY": -1, "HASH_DB0": 0, "INDEX_DB0": 0, "AUTHORITATIVE_ROADS": 1,
                   "BASELINE_PROBES": 2, "QWEN_RESEARCH": 3, "MODEL_LOOP": 3,
                   "FINISHED": 4, "ERROR": 4}
        if self.status.get("status") in FINAL_STATUSES:
            return 4
        return mapping.get(stage, -1)

    def draw_pipeline(self) -> None:
        canvas = self.pipeline
        width = max(canvas.winfo_width(), 500)
        canvas.delete("all")
        steps = ["Перевірка DB_0", "Корпус доріг", "Контрольні тести", "Локальний Qwen", "Звіт"]
        active = self._step_index()
        margin = 8
        gap = 12
        box_width = (width - margin * 2 - gap * (len(steps) - 1)) / len(steps)
        y0, y1 = 13, 70
        for index, title in enumerate(steps):
            x0 = margin + index * (box_width + gap)
            x1 = x0 + box_width
            if index < active:
                color, marker = "#E3F3EC", "✓"
                text_color = GREEN
            elif index == active:
                if self.status.get("status") in {"BLOCKED_ORACLE", "MODEL_OUTPUT_INVALID", "FAILED"}:
                    color, marker, text_color = "#FCE8EA", "!", RED
                elif self.status.get("status") in {"PAUSED", "STOPPED_BY_USER"}:
                    color, marker, text_color = "#FFF3D6", "Ⅱ", AMBER
                elif self.status.get("status") in {"EXPERIMENTS_EXHAUSTED", "ACTION_QUEUE_EXHAUSTED", "RESEARCH_BUDGET_EXHAUSTED", "DECODER_CANDIDATE_REQUIRES_REVIEW"}:
                    color, marker, text_color = "#FFF3D6", "!", AMBER
                else:
                    color, marker, text_color = "#E8F0FF", "●", BLUE
            else:
                color, marker, text_color = "#E8EDF4", str(index + 1), MUTED
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline=color, width=1)
            canvas.create_oval(x0 + 11, y0 + 16, x0 + 35, y0 + 40, fill="white", outline="white")
            canvas.create_text(x0 + 23, y0 + 28, text=marker, fill=text_color,
                               font=("Segoe UI Semibold", 10))
            canvas.create_text(x0 + 44, y0 + 28, text=title, fill=text_color,
                               anchor="w", font=("Segoe UI Semibold", 9))
            if index < len(steps) - 1:
                line_color = GREEN if index < active else LINE
                canvas.create_line(x1 + 1, 42, x1 + gap - 2, 42, fill=line_color, width=2)

    def _percent(self) -> tuple[float, str]:
        stage = self.status.get("stage", "READY")
        progress = self.status.get("progress", {})
        status = self.status.get("status")
        if is_legacy_model_output_stop(self.status) or status == "MODEL_OUTPUT_INVALID":
            return 78.0, "Зупинено через формат відповіді Qwen; еталон не потрібен"
        if status == "BLOCKED_ORACLE":
            return 78.0, "Потрібен логічний буфер 11 776 байтів для сектора 0x11576"
        if status == "EXPERIMENTS_EXHAUSTED":
            return 94.0, "Перевірки завершено; формат не підтверджено"
        if status == "ACTION_QUEUE_EXHAUSTED":
            return 94.0, "Qwen повторює виконані перевірки; чергу збережено"
        if status == "RESEARCH_BUDGET_EXHAUSTED":
            return 94.0, "Ліміт циклу досягнуто; дані збережено для продовження"
        if status == "DECODER_CANDIDATE_REQUIRES_REVIEW":
            return 94.0, "Кандидат очікує структурної перевірки"
        if stage in {"FINISHED"}:
            return 100.0, "Етап 5 з 5"
        if stage == "READY":
            return 0.0, "Етап 0 з 5"
        if stage in {"HASH_DB0", "INDEX_DB0"}:
            done = int(progress.get("records", 0) or 0)
            total = int(progress.get("total", 54010) or 54010)
            fraction = min(1.0, done / max(1, total))
            return 5 + fraction * 25, f"Етап 1 з 5 · {done:,} / {total:,} блоків"
        if stage == "AUTHORITATIVE_ROADS":
            return 32.0, "Етап 2 з 5 · побудова корпусу доріг"
        if stage == "BASELINE_PROBES":
            round_no = int(progress.get("round", 0) or 0)
            fraction = min(1.0, round_no / 6)
            return 35 + fraction * 15, f"Етап 3 з 5 · {round_no} базових перевірок"
        if stage in {"QWEN_RESEARCH", "MODEL_LOOP"}:
            round_no = int(progress.get("round", 0) or 0)
            total = int(progress.get("max_rounds", 200) or 200)
            fraction = min(1.0, round_no / max(1, total))
            return 50 + fraction * 45, f"Етап 4 з 5 · локальний аналіз, крок {round_no}"
        if stage == "ERROR":
            return 100.0, "Зупинено з помилкою"
        return 0.0, "Підготовка"

    def refresh(self) -> None:
        self.status = read_json(STATUS_PATH)
        self.inventory = read_json(WORK / "inventory_summary.json")
        self.road = read_json(WORK / "road_summary.json")
        display_status, display_stage, detail = self.status_text()
        state = self.status.get("status", "READY")
        if self.preparing_model:
            display_status = "Підготовка локальної моделі"
            display_stage = "Завантаження Qwen для роботи без хмари"
            detail = self.preparing_detail
            state = "PREPARING_MODEL"
        state_color = GREEN if state == "EXPERIMENTS_EXHAUSTED" else (
            AMBER if state == "DECODER_CANDIDATE_REQUIRES_REVIEW" else
            RED if state in {"BLOCKED_ORACLE", "FAILED"} else BLUE)
        self.state_label.configure(text=display_status, fg=state_color)
        self.stage_label.configure(text=display_stage)
        self.detail_label.configure(text=detail)
        percent, hint = self._percent()
        if self.preparing_model:
            hint = "Підготовка локальної моделі"
        self.progress_hint.configure(text=hint)
        if self.preparing_model or (self.status.get("stage") == "AUTHORITATIVE_ROADS" and state == "RUNNING"):
            if not self.indeterminate:
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
                self.indeterminate = True
        else:
            if self.indeterminate:
                self.progress.stop()
                self.progress.configure(mode="determinate")
                self.indeterminate = False
            self.progress["value"] = percent
        self.draw_pipeline()
        self.update_metrics()
        self.update_chart()
        self.update_map()
        self.update_facts()
        self.update_experiments()
        self.update_logs()
        self.update_controls()
        setup = read_json(WORK / "machine_setup.json")
        model = setup.get("selected_model") or self.status.get("model") or "не визначено"
        source = setup.get("model_source", "")
        source_label = "· вже встановлена" if source.startswith("reused") else "· локально"
        self.model_label.configure(text=f"Модель: {model} {source_label}")
        self.notice_label.configure(text=self.last_notice)
        self.root.after(1200, self.refresh)

    def update_metrics(self) -> None:
        counts = self.inventory.get("counts", {})
        experiments = self.query("SELECT count(*) FROM experiments", one=True)
        self.metric_values["records"].configure(text=f"{self.inventory.get('record_count', 0):,}" if self.inventory else "—")
        self.metric_values["roads"].configure(text=f"{self.road.get('roads', 0):,}" if self.road else "—")
        self.metric_values["objects"].configure(text=f"{self.road.get('owned_objects', 0):,}" if self.road else "—")
        self.metric_values["experiments"].configure(text=f"{experiments[0]:,}" if experiments else "0")

    def update_chart(self) -> None:
        canvas = self.chart
        canvas.delete("all")
        counts = self.inventory.get("counts", {})
        if not counts:
            canvas.create_text(18, 35, text="Діаграма з'явиться після індексації бази.",
                               anchor="w", fill=MUTED, font=("Segoe UI", 10))
            return
        items = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]
        width = max(canvas.winfo_width(), 360)
        label_w = 135
        right_pad = 44
        bar_w = max(80, width - label_w - right_pad - 18)
        top = 14
        row_h = 29
        max_value = max(value for _, value in items) or 1
        palette = [BLUE, GREEN, "#7D64D8", "#D28A23", "#278EA5", "#CF5B75", "#60758B", "#A1663A"]
        for index, (name, value) in enumerate(items):
            y = top + index * row_h
            label = name.replace("type_", "тип ").replace("_comp_", " · comp ")
            canvas.create_text(2, y + 9, text=label, anchor="w", fill=MUTED, font=("Segoe UI", 9))
            canvas.create_rectangle(label_w, y + 1, label_w + bar_w, y + 18, fill="#EEF2F8", outline="")
            fill_w = max(2, bar_w * value / max_value)
            canvas.create_rectangle(label_w, y + 1, label_w + fill_w, y + 18,
                                    fill=palette[index % len(palette)], outline="")
            canvas.create_text(label_w + bar_w + 8, y + 9, text=f"{value:,}", anchor="w",
                               fill=INK, font=("Segoe UI Semibold", 9))

    def map_source(self, filename: str) -> Path | None:
        live = WORK / "authoritative_road_corpus" / filename
        bundled = ROOT / "research" / "roads" / filename
        complete = WORK / "authoritative_road_corpus" / "authoritative_summary.json"
        if live.is_file() and complete.is_file():
            return live
        if bundled.is_file():
            return bundled
        return None

    def update_map(self) -> None:
        objects_path = self.map_source("authoritative_road_objects.csv")
        transitions_path = self.map_source("authoritative_transitions.csv")
        signature = tuple(
            (str(path), path.stat().st_mtime_ns, path.stat().st_size) if path else None
            for path in (objects_path, transitions_path)
        )
        if signature == self.map_signature:
            return
        self.map_signature = signature
        self.map_nodes = {}
        self.map_edges = set()
        if objects_path:
            try:
                with objects_path.open("r", encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        node = row.get("physical_node_id", "")
                        try:
                            lon, lat = float(row["lon"]), float(row["lat"])
                        except (KeyError, TypeError, ValueError):
                            continue
                        if node and -180 <= lon <= 180 and -90 <= lat <= 90:
                            self.map_nodes.setdefault(node, (lon, lat))
            except OSError:
                pass
        if transitions_path and self.map_nodes:
            try:
                with transitions_path.open("r", encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        a, b = row.get("P_node", ""), row.get("Q_node", "")
                        if a in self.map_nodes and b in self.map_nodes and a != b:
                            self.map_edges.add(tuple(sorted((a, b))))
            except OSError:
                pass
        self.draw_map()

    def draw_map(self) -> None:
        canvas = getattr(self, "map_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 420), max(canvas.winfo_height(), 300)
        if not self.map_nodes:
            canvas.create_text(width / 2, height / 2,
                               text="Граф з'явиться після завантаження дорожнього корпусу.",
                               fill=MUTED, font=("Segoe UI", 11))
            self.map_info.configure(text="Дорожні координати ще не знайдені.")
            return
        longitudes = [point[0] for point in self.map_nodes.values()]
        latitudes = [point[1] for point in self.map_nodes.values()]
        min_lon, max_lon = min(longitudes), max(longitudes)
        min_lat, max_lat = min(latitudes), max(latitudes)
        lon_span = max(max_lon - min_lon, 0.01)
        lat_span = max(max_lat - min_lat, 0.01)
        left, right, top, bottom = 42, width - 20, 25, height - 38
        scale = min((right - left) / lon_span, (bottom - top) / lat_span)
        plot_w, plot_h = lon_span * scale, lat_span * scale
        x_pad = (right - left - plot_w) / 2
        y_pad = (bottom - top - plot_h) / 2

        def xy(node: str) -> tuple[float, float]:
            lon, lat = self.map_nodes[node]
            x = left + x_pad + (lon - min_lon) * scale
            y = bottom - y_pad - (lat - min_lat) * scale
            return x, y

        canvas.create_rectangle(left, top, right, bottom, outline=LINE, width=1)
        for a, b in self.map_edges:
            x1, y1 = xy(a)
            x2, y2 = xy(b)
            canvas.create_line(x1, y1, x2, y2, fill="#C9D6E8", width=1)
        for node in self.map_nodes:
            x, y = xy(node)
            radius = 2.8
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius,
                               fill=BLUE, outline="white", width=0.7)
        canvas.create_text(left, bottom + 17, text=f"{min_lon:.2f}° довгота",
                           anchor="w", fill=MUTED, font=("Segoe UI", 8))
        canvas.create_text(right, top - 8, text=f"{max_lat:.2f}° широта",
                           anchor="e", fill=MUTED, font=("Segoe UI", 8))
        self.map_info.configure(text=f"{len(self.map_nodes):,} унікальних координатних вузлів · {len(self.map_edges):,} унікальних переходів")

    def update_facts(self) -> None:
        comp02 = self.inventory.get("compression02_valid")
        lines = [
            "ПІДТВЕРДЖЕНО",
            "• DB_0: ланцюжок із 54 010 блоків по 512 байтів.",
            "• Compression 0x02: zlib-потік починається з +8; розмір перевіряється за заголовком.",
            "• Підтверджений корпус у 52 секторах: 33 381 дорога та 95 119 входжень об'єктів.",
        ]
        if comp02 is not None:
            lines.append(f"• У цьому запуску перевірено блоків 0x02: {comp02:,}.")
        lines.extend([
            "",
            "ЩЕ НЕ РОЗКОДОВАНО",
            "• Для декодування compression 0x01 потрібен незалежно перевірений логічний буфер сектора 0x11576 (11 776 байтів); помилки формату Qwen його не потребують.",
            "• Геометрія доріг: формат окремих структур поки не підтверджений.",
        ])
        self.facts_text.configure(state="normal")
        self.facts_text.delete("1.0", "end")
        self.facts_text.insert("1.0", "\n".join(lines))
        self.facts_text.configure(state="disabled")

    def query(self, sql: str, params: tuple = (), one: bool = False):
        if not STATE_DB.is_file():
            return None
        try:
            path = quote(STATE_DB.resolve().as_posix(), safe=":/")
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.3)
            try:
                row = conn.execute(sql, params).fetchone() if one else conn.execute(sql, params).fetchall()
                return row
            finally:
                conn.close()
        except sqlite3.Error:
            return None

    def update_experiments(self) -> None:
        for item in self.experiments.get_children():
            self.experiments.delete(item)
        rows = self.query("SELECT round_no,tool,result_json FROM experiments ORDER BY round_no DESC LIMIT 8") or []
        for round_no, tool, result_json in rows:
            try:
                result = json.loads(result_json)
                summary = json.dumps(result, ensure_ascii=False)
            except (ValueError, TypeError):
                summary = str(result_json)
            summary = summary.replace("\n", " ")
            if len(summary) > 180:
                summary = summary[:177] + "…"
            self.experiments.insert("", "end", values=(round_no, tool, summary))
        for item in self.hypotheses.get_children():
            self.hypotheses.delete(item)
        hypotheses = self.query(
            "SELECT round_no,claim,expected_if_true,falsifier FROM hypotheses ORDER BY id DESC LIMIT 6"
        ) or []
        for round_no, claim, expected, falsifier in hypotheses:
            short = [str(value).replace("\n", " ") for value in (claim, expected, falsifier)]
            short = [value[:97] + "…" if len(value) > 100 else value for value in short]
            self.hypotheses.insert("", "end", values=(round_no, *short))

    def update_logs(self) -> None:
        lines = []
        for path in (WORK / "runner.log", WORK / "desktop_app_worker.log", WORK / "model_pull.log"):
            try:
                if path.is_file():
                    lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines()[-35:])
            except OSError:
                pass
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", "\n".join(lines[-55:]) or "Журнал з'явиться після запуску.")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def export_logs(self) -> None:
        suggested = f"NCDR_DB0_logs_{datetime.now():%Y%m%d_%H%M%S}.zip"
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Зберегти журнали NCDR",
            initialfile=suggested,
            defaultextension=".zip",
            filetypes=[("ZIP-архів", "*.zip")],
        )
        if not destination:
            return

        sources = (
            ("logs/runner.log", WORK / "runner.log"),
            ("logs/desktop_app_worker.log", WORK / "desktop_app_worker.log"),
            ("logs/model_pull.log", WORK / "model_pull.log"),
            ("logs/road_corpus.stdout.log", WORK / "road_corpus.stdout.log"),
            ("logs/road_corpus.stderr.log", WORK / "road_corpus.stderr.log"),
            ("status.json", STATUS_PATH),
            ("reports/PROGRESS_REPORT.md", REPORTS / "PROGRESS_REPORT.md"),
        )
        included = 0
        temporary = Path(destination).with_suffix(Path(destination).suffix + ".tmp")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for archive_name, source in sources:
                    if source.is_file():
                        archive.write(source, arcname=archive_name)
                        included += 1
            if included:
                temporary.replace(destination)
            else:
                temporary.unlink(missing_ok=True)
            if included:
                messagebox.showinfo("Експорт готовий", f"Збережено {included} файлів журналу:\n{destination}", parent=self.root)
            else:
                messagebox.showwarning("Журналів немає", "У папці проєкту ще немає файлів журналу.", parent=self.root)
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            temporary.unlink(missing_ok=True)
            messagebox.showerror("Помилка експорту", f"Не вдалося зберегти журнали:\n{exc}", parent=self.root)

    def update_controls(self) -> None:
        active = active_runner_pid() is not None
        command = read_control_command()
        paused = self.status.get("status") == "PAUSED" or command == "PAUSE"
        stopping = active and command == "STOP"
        final = self.status.get("status") in FINAL_STATUSES and not is_legacy_model_output_stop(self.status)
        can_start = not final and not self.preparing_model and (not active or paused) and not stopping
        self.start_button.configure(
            text="Продовжити" if paused or self.status.get("status") in {"PAUSED", "STOPPED_BY_USER"} or is_legacy_model_output_stop(self.status) else "Запуск / продовжити",
            state="normal" if can_start else "disabled",
        )
        self.pause_button.configure(state="normal" if active and not paused and not stopping else "disabled")
        self.stop_button.configure(state="normal" if active and not stopping else "disabled")

    def pause_run(self) -> None:
        if active_runner_pid() is None:
            self.last_notice = "Немає активного запуску для паузи."
            return
        if read_control_command() == "STOP":
            self.last_notice = "Зупинення вже очікує найближчої контрольної точки."
            return
        write_control_command("PAUSE")
        self.last_notice = "Пауза застосовується після поточного кроку або відповіді Qwen."

    def stop_run(self) -> None:
        if active_runner_pid() is None:
            self.last_notice = "Немає активного запуску для зупинки."
            return
        write_control_command("STOP")
        self.last_notice = "Зупинення на найближчій контрольній точці; збережені результати лишаться."

    def auto_start(self) -> None:
        if self.auto_start_done:
            return
        self.auto_start_done = True
        manual_hold = self.status.get("status") in {"PAUSED", "STOPPED_BY_USER", "FAILED"} or read_control_command() == "PAUSE"
        if active_runner_pid() is None and not manual_hold and self.status.get("status") not in FINAL_STATUSES:
            self.ensure_model_and_start(silent=True)

    def installed_models(self) -> list[str]:
        request = urllib.request.Request("http://localhost:11434/api/tags")
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                data = json.loads(response.read().decode("utf-8"))
            return [name for row in data.get("models", [])
                    for name in [row.get("name") or row.get("model")]
                    if isinstance(name, str) and name]
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return []

    @staticmethod
    def choose_installed_qwen(names: list[str], preferred: str) -> str | None:
        local_qwen = [name for name in names
                      if name.lower().rsplit("/", 1)[-1].startswith("qwen")
                      and ":cloud" not in name.lower()]
        if not local_qwen:
            return None
        orders = {
            "qwen3.5:9b": ("qwen3.5:9b", "qwen3.5:4b", "qwen3.5:2b", "qwen3.5:0.8b"),
            "qwen3.5:4b": ("qwen3.5:4b", "qwen3.5:2b", "qwen3.5:0.8b", "qwen3.5:9b"),
            "qwen3.5:2b": ("qwen3.5:2b", "qwen3.5:0.8b", "qwen3.5:4b", "qwen3.5:9b"),
        }
        order = orders.get(preferred, ("qwen3.5:0.8b", "qwen3.5:2b", "qwen3.5:4b", "qwen3.5:9b"))
        for base in order:
            for name in sorted(local_qwen):
                leaf = name.lower().rsplit("/", 1)[-1]
                if leaf == base or leaf.startswith(base + "-"):
                    return name
        qwen35 = sorted(name for name in local_qwen
                        if name.lower().rsplit("/", 1)[-1].startswith("qwen3.5:"))
        return qwen35[0] if qwen35 else sorted(local_qwen)[0]

    def ensure_model_and_start(self, silent: bool = False) -> None:
        if active_runner_pid() is not None:
            if self.status.get("status") == "PAUSED" or read_control_command() == "PAUSE":
                write_control_command("RUN")
                self.last_notice = "Продовжую з найближчої контрольної точки."
                return
            if read_control_command() == "STOP":
                self.last_notice = "Зупинення вже виконується; дочекайтеся підтвердження зупинки."
                return
            self.last_notice = "Дослідження вже працює у фоні."
            return
        write_control_command("RUN")
        db0 = ROOT / "DB_0"
        if not db0.is_file():
            self.last_notice = "Не знайдено DB_0 у папці програми."
            return
        python_exe, worker_env, preflight_error = prepare_runner_runtime()
        if preflight_error:
            self.preparing_model = False
            self.preparing_detail = "Перевірка залежностей не пройдена; дослідження не запускалося."
            self.last_notice = "Дослідження не запущено: перевірте конкретну причину помилки."
            try:
                with (WORK / "desktop_app_worker.log").open("a", encoding="utf-8") as log:
                    log.write("\n" + preflight_error + "\n")
            except OSError:
                pass
            if not silent:
                messagebox.showerror("Не вдалося підготувати дослідження", preflight_error, parent=self.root)
            return
        setup = read_json(WORK / "machine_setup.json")
        model = setup.get("selected_model", "qwen3.5:4b")
        if self.model_process and self.model_process.poll() is None:
            self.preparing_model = True
            self.preparing_detail = "Модель уже завантажується у фоновому режимі."
            return
        installed = self.installed_models()
        if model not in installed:
            existing_qwen = self.choose_installed_qwen(installed, model)
            if existing_qwen:
                model = existing_qwen
                setup["selected_model"] = model
                setup["model_source"] = "reused installed local Qwen"
                write_json(WORK / "machine_setup.json", setup)
                self.last_notice = f"Використовую вже встановлену модель {model}."
        if model in installed:
            self.launch_worker(model, silent, (python_exe, worker_env))
            return
        ollama = setup.get("ollama", "ollama")
        WORK.mkdir(parents=True, exist_ok=True)
        log_path = WORK / "model_pull.log"
        try:
            self.model_log = log_path.open("a", encoding="utf-8")
            self.model_process = subprocess.Popen(
                [ollama, "pull", model], cwd=ROOT, stdout=self.model_log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.preparing_model = True
            self.preparing_detail = f"Завантажується {model}. Перший запуск потребує інтернету; після цього модель працюватиме локально."
            self.last_notice = "Завантажується локальна модель."
            self.root.after(1000, lambda: self.poll_model_download(model, silent))
        except OSError as exc:
            self.last_notice = f"Не вдалося запустити процес: {exc}"

    def poll_model_download(self, model: str, silent: bool) -> None:
        if not self.model_process:
            self.preparing_model = False
            return
        if self.model_process.poll() is None:
            try:
                tail = (WORK / "model_pull.log").read_text(encoding="utf-8", errors="replace").splitlines()[-1:]
                if tail:
                    self.preparing_detail = f"Завантажується {model}. {tail[0].strip()[:180]}"
            except OSError:
                pass
            self.root.after(1000, lambda: self.poll_model_download(model, silent))
            return
        return_code = self.model_process.returncode
        if self.model_log:
            try:
                self.model_log.flush()
                self.model_log.close()
            except OSError:
                pass
        self.model_log = None
        self.model_process = None
        if return_code == 0 and model in self.installed_models():
            self.preparing_model = False
            self.last_notice = f"{model} готова. Запускається аналіз."
            self.launch_worker(model, silent)
        else:
            self.preparing_model = False
            self.preparing_detail = "Завантаження не завершилося. Перевірте інтернет і натисніть «Почати / продовжити» ще раз."
            self.last_notice = "Модель не завантажена; аналіз не запускався."

    def launch_worker(
        self, model: str, silent: bool = False,
        runtime: tuple[str, dict[str, str]] | None = None,
    ) -> None:
        db0 = ROOT / "DB_0"
        if active_runner_pid() is not None:
            self.last_notice = "Дослідження вже працює у фоні."
            return
        if runtime is None:
            python_exe, worker_env, preflight_error = prepare_runner_runtime()
            if preflight_error:
                self.preparing_model = False
                self.preparing_detail = "Перевірка залежностей не пройдена; дослідження не запускалося."
                self.last_notice = "Дослідження не запущено: перевірте конкретну причину помилки."
                try:
                    with (WORK / "desktop_app_worker.log").open("a", encoding="utf-8") as log:
                        log.write("\n" + preflight_error + "\n")
                except OSError:
                    pass
                if not silent:
                    messagebox.showerror("Не вдалося підготувати дослідження", preflight_error, parent=self.root)
                return
            runtime = (python_exe, worker_env)
        write_control_command("RUN")
        log_path = WORK / "desktop_app_worker.log"
        python_exe, worker_env = runtime
        try:
            if self.worker_log:
                self.worker_log.close()
            runner_command = [
                python_exe, str(ROOT / "ncdqwen" / "runner.py"), "--db0", str(db0),
                "--model", model, "--max-rounds", "200",
            ]
            resume_saved_model_stop = not silent and is_legacy_model_output_stop(self.status)
            if resume_saved_model_stop:
                runner_command.append("--resume-final")
            self.worker_log = log_path.open("a", encoding="utf-8")
            self.worker_log.write(
                f"\n[{datetime.now().astimezone().isoformat()}] Starting DB_0 worker\n"
                f"python={python_exe}\nroot={ROOT}\ncwd={ROOT}\n"
                f"PYTHONPATH={worker_env.get('PYTHONPATH', '')}\n"
                f"argv={runner_command!r}\n"
            )
            self.worker_log.flush()
            self.process = subprocess.Popen(
                runner_command, cwd=ROOT, stdout=self.worker_log, stderr=subprocess.STDOUT,
                env=worker_env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.last_notice = "Аналіз запущено у фоні." if not silent else "Відновлено фоновий аналіз."
            process = self.process
            self.root.after(700, lambda: self.check_worker_startup(process, silent))
        except OSError as exc:
            self.last_notice = f"Не вдалося запустити процес: {exc}"
            details = f"Не вдалося запустити дослідницький процес.\n\nPython: {python_exe}\nРобоча папка: {ROOT}\n{type(exc).__name__}: {exc}"
            if not silent:
                messagebox.showerror("Дослідження не запустилося", details, parent=self.root)

    def check_worker_startup(self, process: subprocess.Popen, silent: bool) -> None:
        if process is not self.process:
            return
        return_code = process.poll()
        if return_code is None:
            self.root.after(700, lambda: self.check_worker_startup(process, silent))
            return
        if return_code == 0:
            self.refresh()
            return
        try:
            lines = (WORK / "desktop_app_worker.log").read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            tail = "\n".join(lines[-14:])[-2600:]
        except OSError:
            tail = "Докладний журнал недоступний."
        self.last_notice = "Робочий процес завершився з помилкою; подробиці показані у вікні."
        if not silent:
            messagebox.showerror(
                "Дослідження не запустилося",
                f"Фоновий процес завершився з кодом {process.returncode}.\n\n{tail}",
                parent=self.root,
            )
        self.refresh()

    def close_window(self) -> None:
        if self.worker_log:
            try:
                self.worker_log.flush()
                self.worker_log.close()
            except OSError:
                pass
        if self.model_log:
            try:
                self.model_log.flush()
                self.model_log.close()
            except OSError:
                pass
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
