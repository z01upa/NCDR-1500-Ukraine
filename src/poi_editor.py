"""Standalone Windows editor for user-owned NCDR personal POIs.

The editor shares the same SQLite store as Virtual CID. These locations stay
in the user's LocalAppData folder and never modify original NCDx media.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sqlite3
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.cid.virtual_cid import PoiStore, default_poi_path


CATEGORIES = (
    "Авто", "АЗС", "Медицина", "Їжа", "Магазин", "Паркування",
    "Сервіс", "Культура", "Інше",
)


def parse_coordinate(value: str, label: str, lower: float, upper: float) -> float:
    """Parse a decimal coordinate, accepting the common comma decimal mark."""
    text = value.strip().replace(",", ".")
    try:
        coordinate = float(text)
    except ValueError as exc:
        raise ValueError(f"{label}: введіть координату числом") from exc
    if not math.isfinite(coordinate) or not lower <= coordinate <= upper:
        raise ValueError(f"{label}: допустиме значення від {lower} до {upper}")
    return coordinate


class PoiEditor:
    def __init__(self, root: tk.Tk, database: Path | None = None):
        self.root = root
        self.store = PoiStore(database or default_poi_path())
        self.rows: dict[str, dict[str, Any]] = {}
        self.root.title("NCDR Ukraine · Редактор особистих місць")
        self.root.geometry("900x650")
        self.root.minsize(720, 520)
        self.root.configure(bg="#eef2f4")
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef2f4")
        style.configure("TLabel", background="#eef2f4", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground="#183c54")
        style.configure("Hint.TLabel", foreground="#586873", font=("Segoe UI", 9))
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Редактор особистих місць", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Зберігає назву українською, координати й категорію локально для Virtual CID.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(3, 12))

        form = ttk.LabelFrame(outer, text="Дані місця", padding=10)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        self.name_var = tk.StringVar()
        self.latitude_var = tk.StringVar()
        self.longitude_var = tk.StringVar()
        self.category_var = tk.StringVar(value="Інше")
        ttk.Label(form, text="Назва українською").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.name_entry = ttk.Entry(form, textvariable=self.name_var)
        self.name_entry.grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Label(form, text="Широта").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(form, textvariable=self.latitude_var, width=18).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(form, text="Довгота").grid(row=1, column=2, sticky="w", padx=(12, 8), pady=4)
        ttk.Entry(form, textvariable=self.longitude_var, width=18).grid(row=1, column=3, sticky="ew", pady=4)
        ttk.Label(form, text="Категорія").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Combobox(form, textvariable=self.category_var, values=CATEGORIES, state="normal").grid(
            row=2, column=1, sticky="ew", pady=4
        )
        ttk.Label(form, text="Можна ввести власну категорію", style="Hint.TLabel").grid(
            row=2, column=2, columnspan=2, sticky="w", padx=(12, 0), pady=4
        )

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(8, 12))
        ttk.Button(actions, text="Зберегти місце", command=self.save).pack(side="left")
        ttk.Button(actions, text="Нове місце", command=self.clear_form).pack(side="left", padx=6)
        ttk.Button(actions, text="Видалити вибране", command=self.delete_selected).pack(side="left")
        ttk.Button(actions, text="Імпорт JSON", command=self.import_json).pack(side="right")
        ttk.Button(actions, text="Експорт JSON", command=self.export_json).pack(side="right", padx=6)

        search = ttk.Frame(outer)
        search.pack(fill="x", pady=(0, 5))
        ttk.Label(search, text="Пошук місць").pack(side="left")
        self.filter_var = tk.StringVar()
        search_entry = ttk.Entry(search, textvariable=self.filter_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=8)
        search_entry.bind("<Return>", lambda _event: self.refresh())
        ttk.Button(search, text="Знайти", command=self.refresh).pack(side="left")

        self.table = ttk.Treeview(outer, columns=("latitude", "longitude", "category"), show="tree headings")
        self.table.heading("#0", text="Назва")
        self.table.heading("latitude", text="Широта")
        self.table.heading("longitude", text="Довгота")
        self.table.heading("category", text="Категорія")
        self.table.column("#0", width=350, anchor="w")
        self.table.column("latitude", width=130, anchor="center")
        self.table.column("longitude", width=130, anchor="center")
        self.table.column("category", width=160, anchor="w")
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self.select_row)
        self.table.bind("<Double-1>", self.select_row)

        self.status_var = tk.StringVar()
        ttk.Label(outer, textvariable=self.status_var, style="Hint.TLabel", wraplength=850).pack(anchor="w", pady=(8, 0))
        ttk.Label(
            outer,
            text=f"Локальна база: {self.store.path} · оригінальні файли NCDx не змінюються",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(3, 0))

    def refresh(self) -> None:
        query = self.filter_var.get().strip()
        try:
            rows = self.store.search(query)
        except (OSError, sqlite3.Error) as exc:
            messagebox.showerror("Не вдалося прочитати місця", str(exc), parent=self.root)
            return
        self.rows = {row["id"]: row for row in rows}
        self.table.delete(*self.table.get_children())
        for row in rows:
            self.table.insert(
                "", "end", iid=row["id"], text=row["name_uk"],
                values=(f"{row['latitude']:.6f}", f"{row['longitude']:.6f}", row["category"]),
            )
        self.status_var.set(f"Місць: {len(rows)}" + (f" · фільтр: {query}" if query else ""))

    def select_row(self, _event: object = None) -> None:
        selected = self.table.selection()
        if not selected:
            return
        row = self.rows.get(selected[0])
        if not row:
            return
        self.name_var.set(row["name_uk"])
        self.latitude_var.set(str(row["latitude"]))
        self.longitude_var.set(str(row["longitude"]))
        self.category_var.set(row["category"])
        self.status_var.set(f"Редагування: {row['name_uk']}")

    def save(self) -> None:
        selected = self.table.selection()
        poi_id = selected[0] if selected else None
        try:
            latitude = parse_coordinate(self.latitude_var.get(), "Широта", -90, 90)
            longitude = parse_coordinate(self.longitude_var.get(), "Довгота", -180, 180)
            saved = self.store.save(
                self.name_var.get(), latitude, longitude, self.category_var.get(), poi_id=poi_id
            )
        except (ValueError, sqlite3.Error, OSError) as exc:
            messagebox.showerror("Не вдалося зберегти місце", str(exc), parent=self.root)
            return
        self.filter_var.set("")
        self.refresh()
        self.table.selection_set(saved["id"])
        self.table.focus(saved["id"])
        self.status_var.set(f"Збережено: {saved['name_uk']} · місце залишиться після перезапуску")

    def clear_form(self) -> None:
        self.table.selection_remove(*self.table.selection())
        self.name_var.set("")
        self.latitude_var.set("")
        self.longitude_var.set("")
        self.category_var.set("Інше")
        self.name_entry.focus_set()
        self.status_var.set("Нове місце")

    def delete_selected(self) -> None:
        selected = self.table.selection()
        if not selected:
            self.status_var.set("Спершу виберіть місце у списку")
            return
        row = self.rows.get(selected[0])
        if not row:
            return
        if not messagebox.askyesno("Видалити місце?", f"Видалити «{row['name_uk']}»?", parent=self.root):
            return
        try:
            self.store.delete(row["id"])
        except (sqlite3.Error, OSError) as exc:
            messagebox.showerror("Не вдалося видалити місце", str(exc), parent=self.root)
            return
        self.clear_form()
        self.refresh()

    def export_json(self) -> None:
        destination = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".json", filetypes=[("Файл POI JSON", "*.json")]
        )
        if not destination:
            return
        try:
            count = self.store.export_json(destination)
        except (OSError, sqlite3.Error) as exc:
            messagebox.showerror("Експорт POI", str(exc), parent=self.root)
            return
        self.status_var.set(f"Експортовано місць: {count}")

    def import_json(self) -> None:
        source = filedialog.askopenfilename(parent=self.root, filetypes=[("Файл POI JSON", "*.json")])
        if not source:
            return
        try:
            imported, skipped = self.store.import_json(source)
        except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
            messagebox.showerror("Імпорт POI", str(exc), parent=self.root)
            return
        self.refresh()
        self.status_var.set(f"Додано місць: {imported} · пропущено дублікатів: {skipped}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
    parser = argparse.ArgumentParser(description="Редактор особистих місць для NCDR Ukraine / Virtual CID")
    parser.add_argument("--db", type=Path, default=default_poi_path(), help="Локальна SQLite база POI")
    args = parser.parse_args(argv)
    root = tk.Tk()
    PoiEditor(root, args.db)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
