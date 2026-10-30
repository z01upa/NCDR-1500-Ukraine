"""Windows desktop control panel for the resumable NCDR worker."""

from __future__ import annotations

import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import autonomous_manager as manager
from src.agent import project_scope, readiness


class VisualProgressScale(tk.Canvas):
    """A high-contrast progress track that stays visible across Windows themes."""

    def __init__(self, master: tk.Misc, *, height: int = 18, **kwargs: Any):
        super().__init__(master, height=height, highlightthickness=0, bd=0,
                         background="#ffffff", **kwargs)
        self._value = 0.0
        self._height = height
        self.bind("<Configure>", self._draw)
        self._draw()

    def set(self, value: float) -> None:
        self._value = max(0.0, min(100.0, float(value)))
        self._draw()

    def _draw(self, _event: Any = None) -> None:
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height() or self._height)
        inset = 2
        left, top, right, bottom = inset, inset, width - inset, height - inset
        self.delete("all")
        if right <= left or bottom <= top:
            return
        radius = min((bottom - top) / 2, 8)
        self.create_oval(left, top, left + 2 * radius, bottom, fill="#dce8ed", outline="")
        self.create_rectangle(left + radius, top, right - radius, bottom, fill="#dce8ed", outline="")
        self.create_oval(right - 2 * radius, top, right, bottom, fill="#dce8ed", outline="")
        filled_right = left + (right - left) * self._value / 100.0
        filled_width = filled_right - left
        if filled_width >= 1:
            if filled_width <= 2 * radius:
                self.create_rectangle(left, top, filled_right, bottom, fill="#07845f", outline="")
                return
            self.create_oval(left, top, left + 2 * radius, bottom, fill="#07845f", outline="")
            self.create_rectangle(left + radius, top, min(filled_right, right), bottom,
                                  fill="#07845f", outline="")
            if self._value >= 100:
                self.create_oval(right - 2 * radius, top, right, bottom, fill="#07845f", outline="")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def verified_progress(state: dict[str, Any], project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Completion uses only active-scope, substantive acceptance evidence."""
    product = _read_json(project_root / "reports" / "product_acceptance.json")
    writer = _read_json(project_root / "reports" / "autonomous_writer_roundtrip.json")
    result = readiness.calculate_readiness(
        state.get("project", {}).get("stage_gates", []), product=product, writer=writer)
    result["physical_compatibility"] = "НЕ ПЕРЕВІРЕНО · потрібне випробування в сумісному автомобілі"
    return result


class _FILETIME(ctypes.Structure):
    _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]


def _filetime(value: _FILETIME) -> int:
    return (int(value.high) << 32) | int(value.low)


class ManagerWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("NCDR Autonomous Research Manager")
        self.root.geometry("1180x760")
        self.root.minsize(980, 620)
        self.root.configure(bg="#f3f6f8")
        self.last_cpu: tuple[int, int] | None = None
        self.last_refresh = 0.0
        self.latest_state: dict[str, Any] | None = None
        self.snapshot_error = ""
        self.closing = threading.Event()
        self._make_style()
        self._make_layout()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poller = threading.Thread(target=self._poll_snapshot, name="ncdr-ui-refresh", daemon=True)
        self.poller.start()
        self.root.after(80, self.refresh)

    def _poll_snapshot(self) -> None:
        while not self.closing.is_set():
            try:
                state = manager.snapshot()
                self.latest_state = state
                self.snapshot_error = ""
            except Exception as exc:
                self.snapshot_error = f"{type(exc).__name__}: {exc}"
            self.closing.wait(1.5)

    def _make_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f6f8")
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("TLabel", background="#f3f6f8", foreground="#17212b", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground="#12334a")
        style.configure("Hint.TLabel", foreground="#506372", font=("Segoe UI", 9))
        style.configure("Metric.TLabel", background="#ffffff", font=("Segoe UI", 10, "bold"), padding=10)
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 9), background="#ffffff", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(13, 8))
        style.configure("Danger.TButton", foreground="#a22220", font=("Segoe UI", 9, "bold"), padding=(10, 8))
        style.configure("TNotebook", background="#f3f6f8", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI", 9, "bold"))

    def _make_layout(self) -> None:
        shell = ttk.Frame(self.root, padding=16)
        shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell)
        header.pack(fill="x")
        ttk.Label(header, text="NCDR Autonomous Research Manager", style="Title.TLabel").pack(side="left")
        self.worker_status = tk.StringVar(value="Перевірка стану…")
        ttk.Label(header, textvariable=self.worker_status, font=("Segoe UI", 10, "bold")).pack(side="right", padx=(12, 0))

        action = ttk.Frame(shell, padding=(0, 12, 0, 12))
        action.pack(fill="x")
        self.start_button = ttk.Button(action, text="Запустити дослідження", style="Accent.TButton", command=self.start)
        self.start_button.pack(side="left")
        self.pause_button = ttk.Button(action, text="Пауза", command=self.pause)
        self.pause_button.pack(side="left", padx=(8, 0))
        self.resume_button = ttk.Button(action, text="Продовжити", command=self.resume)
        self.resume_button.pack(side="left", padx=(8, 0))
        self.stop_button = ttk.Button(action, text="Зупинити", command=self.stop)
        self.stop_button.pack(side="left", padx=(8, 0))
        ttk.Button(action, text="Аварійне зупинення", style="Danger.TButton", command=self.emergency_stop).pack(side="left", padx=(8, 0))
        ttk.Button(action, text="Переглянути результати", command=self.open_results).pack(side="right")
        self.command_status = tk.StringVar(value="Натисніть «Запустити дослідження», щоб перевірити залежності та чергу.")
        ttk.Label(shell, textvariable=self.command_status, style="Hint.TLabel", wraplength=1120,
                  justify="left").pack(fill="x", pady=(0, 8))

        metrics = ttk.Frame(shell)
        metrics.pack(fill="x", pady=(0, 12))
        self.metric_vars = [tk.StringVar(value="—") for _ in range(4)]
        for idx, (title, var) in enumerate(zip(("Черга", "Поточна задача", "Ресурси", "Локальна модель"), self.metric_vars)):
            card = ttk.Frame(metrics, style="Card.TFrame", padding=2)
            card.pack(side="left", fill="x", expand=True, padx=(0 if idx == 0 else 8, 0))
            ttk.Label(card, text=title.upper(), style="Hint.TLabel").pack(anchor="w", padx=10, pady=(8, 0))
            ttk.Label(card, textvariable=var, style="Metric.TLabel", wraplength=260, justify="left").pack(anchor="w", fill="x")

        self.progress_frame = ttk.Frame(shell, style="Card.TFrame", padding=(12, 8))
        self.progress_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(self.progress_frame,
                  text=f"Глобальна мета: {project_scope.global_goal()}",
                  font=("Segoe UI", 9, "bold"), background="#ffffff", wraplength=1100).grid(
                      row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.progress_title = tk.StringVar(value="Перевірена готовність продукту")
        ttk.Label(self.progress_frame, textvariable=self.progress_title,
                  font=("Segoe UI", 10, "bold"), background="#ffffff").grid(
                      row=1, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.progress_bars: dict[str, VisualProgressScale] = {}
        self.progress_values: dict[str, tk.StringVar] = {}
        progress_names = ["Загалом", *project_scope.load_scope()["readiness_policy"]["progress_components"].keys()]
        for row_index, name in enumerate(progress_names, start=2):
            ttk.Label(self.progress_frame, text=name, background="#ffffff", width=29).grid(
                row=row_index, column=0, sticky="w", padx=(0, 8), pady=2)
            bar = VisualProgressScale(self.progress_frame, height=18)
            bar.grid(row=row_index, column=1, sticky="ew", pady=2)
            value = tk.StringVar(value="0%")
            ttk.Label(self.progress_frame, textvariable=value, background="#ffffff", width=17,
                      anchor="e").grid(row=row_index, column=2, sticky="e", padx=(8, 0))
            self.progress_bars[name] = bar
            self.progress_values[name] = value
        self.progress_frame.columnconfigure(1, weight=1)
        self.hardware_progress_note = tk.StringVar(value="Фізична сумісність: не перевірено")
        ttk.Label(self.progress_frame, textvariable=self.hardware_progress_note,
                  style="Hint.TLabel", background="#ffffff").grid(
            row=len(progress_names) + 2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(self.progress_frame, text="Національний OSM-імпорт", background="#ffffff", width=29).grid(
            row=len(progress_names) + 3, column=0, sticky="w", padx=(0, 8), pady=(5, 2))
        self.national_osm_bar = VisualProgressScale(self.progress_frame, height=18)
        self.national_osm_bar.grid(row=len(progress_names) + 3, column=1, sticky="ew", pady=(5, 2))
        self.national_osm_status = tk.StringVar(value="Ще не запущено")
        ttk.Label(self.progress_frame, textvariable=self.national_osm_status, background="#ffffff", width=48,
                  anchor="e").grid(row=len(progress_names) + 3, column=2, sticky="e", padx=(8, 0))

        self.tabs = ttk.Notebook(shell)
        self.tabs.pack(fill="both", expand=True)
        self.queue_tab = ttk.Frame(self.tabs, padding=8)
        self.logs_tab = ttk.Frame(self.tabs, padding=8)
        self.evidence_tab = ttk.Frame(self.tabs, padding=8)
        self.reports_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.queue_tab, text="Черга завдань")
        self.tabs.add(self.logs_tab, text="Журнал")
        self.tabs.add(self.evidence_tab, text="Докази й артефакти")
        self.tabs.add(self.reports_tab, text="Звіти AI Supervisor")

        self.queue = ttk.Treeview(self.queue_tab, columns=("stage", "status", "attempts", "updated"), show="tree headings")
        self.queue.heading("#0", text="Задача")
        self.queue.heading("stage", text="Етап")
        self.queue.heading("status", text="Стан")
        self.queue.heading("attempts", text="Спроби")
        self.queue.heading("updated", text="Оновлено")
        self.queue.column("#0", width=420, anchor="w")
        self.queue.column("stage", width=80, anchor="center")
        self.queue.column("status", width=150, anchor="center")
        self.queue.column("attempts", width=90, anchor="center")
        self.queue.column("updated", width=180, anchor="center")
        self.queue.pack(fill="both", expand=True)
        self.queue.tag_configure("BLOCKED", foreground="#99342d")
        self.queue.tag_configure("DONE", foreground="#216d4d")
        self.queue.tag_configure("LEASED", background="#fff2cf")

        logbar = ttk.Frame(self.logs_tab)
        logbar.pack(fill="x", pady=(0, 6))
        ttk.Label(logbar, text="Події worker оновлюються автоматично.", style="Hint.TLabel").pack(side="left")
        self.log_text = tk.Text(self.logs_tab, height=18, wrap="word", font=("Consolas", 9), bg="#ffffff", fg="#243444", relief="solid", borderwidth=1)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

        self.evidence_text = tk.Text(self.evidence_tab, height=18, wrap="word", font=("Segoe UI", 9), bg="#ffffff", fg="#243444", relief="solid", borderwidth=1)
        self.evidence_text.pack(fill="both", expand=True)
        self.evidence_text.configure(state="disabled")

        report_actions = ttk.Frame(self.reports_tab)
        report_actions.pack(fill="x", pady=(0, 7))
        ttk.Label(report_actions, text="Фактичні результати задач, перевірки, блокування та моделі.",
                  style="Hint.TLabel").pack(side="left")
        ttk.Button(report_actions, text="Відкрити", command=self.open_selected_report).pack(side="right")
        ttk.Button(report_actions, text="Експортувати копію…", command=self.export_selected_report).pack(side="right", padx=(0, 8))
        self.reports = ttk.Treeview(self.reports_tab, columns=("period", "created", "file"), show="headings")
        self.reports.heading("period", text="Період")
        self.reports.heading("created", text="Створено")
        self.reports.heading("file", text="Звіт")
        self.reports.column("period", width=110, anchor="center")
        self.reports.column("created", width=190, anchor="center")
        self.reports.column("file", width=650, anchor="w")
        self.reports.pack(fill="both", expand=True)

        footer = ttk.Frame(shell)
        footer.pack(fill="x", pady=(9, 0))
        ttk.Label(footer, text=str(PROJECT_ROOT), style="Hint.TLabel").pack(side="left")
        ttk.Label(footer, text="Оригінальні диски відкриваються лише для читання", style="Hint.TLabel").pack(side="right")

    def _system_cpu(self) -> str:
        if os.name != "nt":
            return "CPU —"
        kernel = ctypes.windll.kernel32
        idle, ktime, utime = _FILETIME(), _FILETIME(), _FILETIME()
        if not kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(ktime), ctypes.byref(utime)):
            return "CPU —"
        now = (_filetime(idle), _filetime(ktime) + _filetime(utime))
        prior, self.last_cpu = self.last_cpu, now
        if prior is None:
            return "CPU вимірюється"
        total = now[1] - prior[1]
        spent = now[0] - prior[0]
        if total <= 0:
            return "CPU —"
        return f"CPU {max(0, min(100, round((total-spent) * 100 / total)))}%"

    @staticmethod
    def _format_bytes(value: int | None) -> str:
        if not value:
            return "—"
        return f"{value / (1024 ** 3):.1f} GB"

    def _refresh_queue(self, rows: list[dict[str, Any]]) -> None:
        for item in self.queue.get_children():
            self.queue.delete(item)
        for row in rows:
            status = str(row.get("status", ""))
            self.queue.insert("", "end", text=row.get("id", ""),
                              values=(row.get("stage", ""), status,
                                      f"{row.get('attempts', 0)}/{row.get('retry_limit', 0)}",
                                      str(row.get("updated_utc", ""))[:19].replace("T", " ")),
                              tags=(status,))

    def _refresh_logs(self, events: list[dict[str, Any]]) -> None:
        content = []
        for row in reversed(events[-150:]):
            detail = row.get("detail_json", "{}")
            try:
                detail = json.dumps(json.loads(detail), ensure_ascii=False, separators=(", ", ": "))
            except (TypeError, json.JSONDecodeError):
                pass
            content.append(f"{str(row.get('created_utc',''))[:19]}  {row.get('severity','INFO'):<7} {row.get('event','')}  {row.get('task_id') or ''}  {detail}")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "\n".join(content))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _refresh_evidence(self, state: dict[str, Any]) -> None:
        lines = ["ДОКАЗИ ПРОЄКТУ", f"Інвентаризованих джерел: {state['project'].get('evidence_count', 0)}",
                 f"Результатів моделей у checkpoint: {state['project'].get('model_run_count', 0)}", "",
                 "ВОРОТА F0–F9"]
        for gate in state["project"].get("stage_gates", []):
            lines.append(f"{gate['stage']}: {gate['status']}")
        lines.extend(["", "ЗБЕРЕЖЕНІ АРТЕФАКТИ"])
        for item in state.get("artifacts", []):
            lines.append(f"[{item['acceptance']}] {item['path']}  SHA-256 {item['sha256']}")
        if len(lines) <= 9:
            lines.append("Артефакти з'являться тут після виконання перевірок.")
        coordinator = state.get("coordinator", {})
        lines.extend(["", "ГОТОВНІСТЬ ПРОГРАМНИХ НАПРЯМІВ"])
        for name, item in coordinator.get("system_readiness", {}).items():
            lines.append(f"{name}: {item.get('status')} — {item.get('tests')} — {item.get('artifact')}")
        if coordinator.get("error"):
            lines.append("Помилка зчитування модельного журналу: " + coordinator["error"])
        lines.extend(["", "ОСТАННІ ЛОКАЛЬНІ МОДЕЛЬНІ ЗАПУСКИ"])
        for run in coordinator.get("model_runs", [])[:10]:
            lines.append(f"{run.get('created_utc','')[:19]} · {run.get('task_id')} · {run.get('model')} · {run.get('decision')} · {run.get('elapsed_ms')} ms")
            if run.get("error"):
                lines.append("  Помилка: " + run["error"])
        if coordinator.get("last_success"):
            lines.append(f"Останній перевірений результат: {coordinator['last_success'].get('task_id')} · {coordinator['last_success'].get('decision')}")
        if coordinator.get("last_error"):
            lines.append(f"Остання модельна помилка: {coordinator['last_error'].get('error')}")
        lines.extend(["", "Поточна задача Qwen / дослідницького координатора: " +
                      str((coordinator.get("current_task") or {}).get("id") or "немає активної задачі")])
        lines.extend(["", "РЕЗУЛЬТАТИ"])
        if manager.REPORT_PATH.is_file():
            lines.append(str(manager.REPORT_PATH))
        lines.append(str(PROJECT_ROOT / "reports"))
        self.evidence_text.configure(state="normal")
        self.evidence_text.delete("1.0", "end")
        self.evidence_text.insert("end", "\n".join(lines))
        self.evidence_text.configure(state="disabled")

    def _refresh_progress(self, state: dict[str, Any]) -> None:
        progress = verified_progress(state)
        self.progress_bars["Загалом"].set(progress["percent"])
        self.progress_values["Загалом"].set(f"{progress['percent']}% · {progress['earned']}/{progress['total']}")
        for name, item in progress["components"].items():
            if name not in self.progress_bars:
                continue
            self.progress_bars[name].set(item["percent"])
            self.progress_values[name].set(f"{item['percent']}% · {item['earned']}/{item['total']}")
        self.hardware_progress_note.set(
            "Фізична сумісність: не перевірено · потрібне випробування в сумісному автомобілі")
        self.progress_title.set("Готовність за збереженими приймальними доказами · апаратне приймання окреме")
        osm = state.get("national_osm_progress", {})
        self.national_osm_bar.set(osm.get("percent", 0))
        self.national_osm_status.set(str(osm.get("message", "Стан імпорту недоступний")))

    def _refresh_reports(self) -> None:
        selected = self.reports.selection()
        selected_path = self.reports.item(selected[0], "values")[2] if selected else None
        for item in self.reports.get_children():
            self.reports.delete(item)
        root = PROJECT_ROOT / "reports" / "periodic"
        rows = []
        for period in ("daily", "weekly", "monthly"):
            folder = root / period
            if folder.is_dir():
                rows.extend((period, path.stat().st_mtime, path) for path in folder.glob("*.md"))
                rows.extend((period, path.stat().st_mtime, path) for path in folder.glob("*.json"))
        rows.sort(key=lambda row: row[1], reverse=True)
        for period, modified, path in rows[:200]:
            iid = str(path.relative_to(PROJECT_ROOT))
            self.reports.insert("", "end", iid=iid, values=(period, datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M:%S"), iid))
        if selected_path and self.reports.exists(selected_path):
            self.reports.selection_set(selected_path)

    def _selected_report(self) -> Path | None:
        selection = self.reports.selection()
        if not selection:
            messagebox.showinfo("Звіт не вибрано", "Виберіть звіт у списку.", parent=self.root)
            return None
        path = (PROJECT_ROOT / self.reports.item(selection[0], "values")[2]).resolve()
        reports_root = (PROJECT_ROOT / "reports").resolve()
        if path != reports_root and reports_root not in path.parents or not path.is_file():
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
        path = self._selected_report()
        if not path:
            return
        target = filedialog.asksaveasfilename(parent=self.root, initialfile=path.name,
            defaultextension=path.suffix, filetypes=[("Звіт", "*.md *.json"), ("Усі файли", "*.*")])
        if not target:
            return
        try:
            import shutil
            shutil.copy2(path, target)
            self.command_status.set(f"Експортовано копію звіту: {target}")
        except OSError as exc:
            messagebox.showerror("Не вдалося експортувати звіт", str(exc), parent=self.root)

    def refresh(self) -> None:
        now = time.monotonic()
        try:
            state = self.latest_state
            if state is None:
                if self.snapshot_error:
                    self.worker_status.set("Перевірка стану не пройшла: " + self.snapshot_error)
                self.root.after(500, self.refresh)
                return
            control = state["control"]
            desired = control.get("desired_state", "STOPPED")
            pid = control.get("worker_pid")
            worker_alive = manager.worker_lock_held()
            labels = {"RUNNING": (f"Працює · PID {pid}" if worker_alive else "Worker не запущений · можна продовжити"),
                      "PAUSED": ("Поточна задача завершується; далі пауза" if worker_alive and control.get("current_task") else "На паузі"),
                      "STOPPING": "Завершує поточну задачу…", "STOPPED": "Зупинено"}
            self.worker_status.set("Worker: " + labels.get(desired, desired))
            counts: dict[str, int] = {}
            for row in state["tasks"]:
                counts[row["status"]] = counts.get(row["status"], 0) + 1
            self.metric_vars[0].set("  ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "Задач поки немає")
            diagnosis = state.get("queue_diagnosis", {})
            self.metric_vars[1].set(control.get("current_task") or diagnosis.get("message", "Чергу перевірено"))
            current_task = control.get("current_task")
            if current_task:
                self.command_status.set(f"Виконується задача {current_task}; стан і докази зберігаються у SQLite.")
            elif desired == "RUNNING" and worker_alive:
                self.command_status.set("Немає придатної задачі: " + str(diagnosis.get("message", "причину не повернула черга")))
            elif desired == "PAUSED" and worker_alive:
                self.command_status.set("Координатор на паузі; збережені задачі та залежності залишаються в черзі.")
            elif desired == "STOPPED":
                self.command_status.set("Координатор зупинений; стан черги збережено у SQLite.")
            resources = state.get("resources", {})
            ram = resources.get("ram", {})
            gpu = resources.get("gpu") or {}
            resource_parts = [self._system_cpu(), f"RAM {self._format_bytes(ram.get('used_bytes'))} / {self._format_bytes(ram.get('total_bytes'))}"]
            if gpu:
                resource_parts.append(f"GPU {gpu.get('name','NVIDIA')} · {gpu.get('memory_used_mib','—')}/{gpu.get('memory_total_mib','—')} MiB")
            self.metric_vars[2].set(" · ".join(resource_parts))
            health = json.loads(control.get("health_json") or "{}")
            chosen = health.get("selected_model") or manager._selected_model(state.get("ollama_models", []))
            resident = state.get("ollama_resident", [])
            coordinator = state.get("coordinator", {})
            runs = coordinator.get("model_runs", [])
            active_names = [str(row.get("name")) for row in resident if row.get("name")]
            latest_run = runs[0] if runs else None
            if active_names:
                model_line = "У пам'яті зараз: " + ", ".join(active_names[:2])
            elif latest_run:
                model_line = f"Останній запуск: {latest_run.get('model')} · {latest_run.get('role')}"
            else:
                model_line = f"Вибрана для наступної задачі: {chosen}"
            run_line = (f"Останній результат: {latest_run.get('decision')} · {latest_run.get('task_id')}"
                        if latest_run else f"Установлено моделей: {len(state.get('ollama_models', []))}")
            self.metric_vars[3].set(model_line + "\n" + run_line)
            if now - self.last_refresh >= 2:
                self._refresh_queue(state["tasks"])
                self._refresh_logs(state["events"])
                self._refresh_evidence(state)
                self._refresh_progress(state)
                self._refresh_reports()
                self.last_refresh = now
            self.pause_button.configure(state="normal" if desired == "RUNNING" and worker_alive else "disabled")
            self.resume_button.configure(state="normal" if desired in {"PAUSED", "STOPPED"} or (desired == "RUNNING" and not worker_alive) else "disabled")
            self.stop_button.configure(state="normal" if desired in {"RUNNING", "PAUSED"} else "disabled")
        except Exception as exc:
            self.worker_status.set(f"Перевірка стану не пройшла: {exc}")
        self.root.after(1500, self.refresh)

    def _spawn_worker(self):
        control = manager._control()
        if manager.worker_lock_held():
            return None
        log_path = manager.PROJECT_ROOT / "work" / "autonomous_manager" / "worker_console.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("a", encoding="utf-8")
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0) |
                 getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) |
                 getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            process = subprocess.Popen([sys.executable, "-X", "utf8", "-B", "-m", "src.agent.autonomous_manager", "worker"],
                             cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL, stdout=log_handle,
                             stderr=subprocess.STDOUT, creationflags=flags, close_fds=True,
                             env=manager.python_utf8_environment())
        finally:
            log_handle.close()
        return process

    def start(self) -> None:
        try:
            prepared = manager.prepare_research_request()
            queue = prepared["queue"]
            if not prepared["can_run"]:
                self.command_status.set("Не запущено: " + queue["message"] + " " +
                    str(prepared["scheduled"].get("reason", "Немає придатної задачі.")))
                return
            control = manager._control()
            if control.get("desired_state") != "RUNNING":
                manager.set_control("RUNNING")
            process = self._spawn_worker()
            if process:
                action = f"Створено worker PID {process.pid}."
            else:
                action = f"Worker уже працює (PID {control.get('worker_pid')}); новий процес не створено."
            recovered = prepared.get("recovered_fixed_blockers", [])
            created = prepared.get("scheduled", {}).get("task_id")
            details = []
            if recovered:
                details.append("Після виправлення причин повернено в чергу: " + ", ".join(recovered))
            if created:
                details.append("Планувальник створив: " + created)
            if not details:
                details.append(queue["message"])
            self.command_status.set(action + " " + " ".join(details))
            self._refresh_logs(manager.snapshot()["events"])
        except Exception as exc:
            self.command_status.set(f"Запуск не пройшов: {type(exc).__name__}: {exc}")
            messagebox.showerror("Не вдалося запустити дослідження", str(exc), parent=self.root)

    def pause(self) -> None:
        manager.set_control("PAUSED")

    def resume(self) -> None:
        self.start()

    def stop(self) -> None:
        manager.set_control("STOPPING")
        state = manager._control()
        if not state.get("worker_pid"):
            manager.set_control("STOPPED")

    def emergency_stop(self) -> None:
        manager.set_control("STOPPING", emergency=True)
        state = manager._control()
        if not state.get("worker_pid"):
            manager.set_control("STOPPED", emergency=True)
        messagebox.showwarning("Аварійне зупинення", "Worker перериває активний дочірній процес і повертає незавершену задачу до SQLite черги.", parent=self.root)

    def open_results(self) -> None:
        target = manager.REPORT_PATH if manager.REPORT_PATH.is_file() else PROJECT_ROOT / "reports"
        try:
            os.startfile(str(target))
        except (AttributeError, OSError) as exc:
            messagebox.showerror("Не вдалося відкрити результати", str(exc), parent=self.root)

    def close(self) -> None:
        self.closing.set()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    from src.agent.autonomous_gui_compact import ManagerWindow as CompactManagerWindow
    CompactManagerWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
