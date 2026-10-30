"""Offline Windows map, personal POI editor, and Virtual CID simulation.

OSM Simulation uses the project's internal SQLite representation. It makes no
claim about Opel hardware compatibility or the still-unconfirmed NCDx format.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import queue
import sqlite3
import sys
import threading
import time
import unicodedata
import uuid
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    # PyInstaller stores bundled data under its extraction/runtime directory.
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from src.osm.engine import OSMStore, normalize_name

def _default_map_path() -> Path:
    data_dir = PROJECT_ROOT / "data" / "osm"
    pointer = data_dir / "current.json"
    if pointer.is_file():
        try:
            filename = json.loads(pointer.read_text(encoding="utf-8")).get("database_file")
            if isinstance(filename, str) and Path(filename).name == filename:
                candidate = data_dir / filename
                if candidate.is_file():
                    return candidate
        except (OSError, ValueError):
            pass
    return data_dir / "kryvyi_rih.sqlite"


DEFAULT_MAP = _default_map_path()
ATTRIBUTION = "Map data © OpenStreetMap contributors · ODbL · openstreetmap.org/copyright"
CITY_VIEW = (47.64, 33.10, 48.18, 33.70)  # Map viewport around Kryvyi Rih and nearby approaches.


class PoiStore:
    """Small persistent personal POI database, independent from the OSM source."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _sqlite(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS poi(
                  id TEXT PRIMARY KEY, name_uk TEXT NOT NULL, latitude REAL NOT NULL,
                  longitude REAL NOT NULL, category TEXT NOT NULL, aliases_json TEXT NOT NULL,
                  created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_poi_name ON poi(name_uk);
                """
            )

    def all(self) -> list[dict[str, Any]]:
        with _sqlite(self.path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) | {"aliases": json.loads(row["aliases_json"])}
                    for row in conn.execute("SELECT * FROM poi ORDER BY name_uk COLLATE NOCASE")]

    def search(self, query: str) -> list[dict[str, Any]]:
        key = normalize_name(query)
        if not key:
            return self.all()
        return [row for row in self.all()
                if key in normalize_name(row["name_uk"])
                or any(key in normalize_name(alias) for alias in row["aliases"])
                or key in normalize_name(row["category"])]

    def save(self, name_uk: str, latitude: float, longitude: float, category: str,
             aliases: list[str] | None = None, poi_id: str | None = None) -> dict[str, Any]:
        name_uk = unicodedata.normalize("NFC", name_uk).strip()
        category = category.strip()
        if not name_uk or not category:
            raise ValueError("Вкажіть українську назву й категорію")
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError("Широта має бути числом у межах −90…90")
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("Довгота має бути числом у межах −180…180")
        aliases = list(dict.fromkeys(unicodedata.normalize("NFC", a.strip()) for a in (aliases or []) if a.strip()))
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        candidate_id = poi_id or str(uuid.uuid4())
        with _sqlite(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            duplicate = conn.execute(
                "SELECT id,name_uk,latitude,longitude FROM poi WHERE id<>?", (candidate_id,)
            ).fetchall()
            normalized = normalize_name(name_uk)
            for row in duplicate:
                distance = _distance_m(latitude, longitude, row[2], row[3])
                if normalize_name(row[1]) == normalized or distance < 30:
                    raise ValueError(f"Схоже місце вже є: {row[1]} ({distance:.0f} м)")
            conn.execute(
                """INSERT INTO poi(id,name_uk,latitude,longitude,category,aliases_json,created_utc,updated_utc)
                   VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                   name_uk=excluded.name_uk,latitude=excluded.latitude,longitude=excluded.longitude,
                   category=excluded.category,aliases_json=excluded.aliases_json,updated_utc=excluded.updated_utc""",
                (candidate_id, name_uk, latitude, longitude, category,
                 json.dumps(aliases, ensure_ascii=False), now, now),
            )
        return next(row for row in self.all() if row["id"] == candidate_id)

    def delete(self, poi_id: str) -> None:
        with _sqlite(self.path) as conn:
            conn.execute("DELETE FROM poi WHERE id=?", (poi_id,))

    def export_json(self, path: str | Path) -> int:
        rows = self.all()
        payload = {"format": "ncdr-personal-poi-v1", "pois": [
            {k: row[k] for k in ("name_uk", "latitude", "longitude", "category", "aliases")} for row in rows
        ]}
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(rows)

    def import_json(self, path: str | Path) -> tuple[int, int]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("format") != "ncdr-personal-poi-v1" or not isinstance(payload.get("pois"), list):
            raise ValueError("Невідомий формат файлу POI")
        imported = skipped = 0
        for row in payload["pois"]:
            try:
                self.save(row["name_uk"], float(row["latitude"]), float(row["longitude"]),
                          row["category"], row.get("aliases", []))
                imported += 1
            except ValueError as exc:
                if "Схоже місце вже є" in str(exc):
                    skipped += 1
                else:
                    raise
        return imported, skipped


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 2*radius*math.asin(min(1.0, math.sqrt(a)))


@contextmanager
def _sqlite(path: Path):
    conn = sqlite3.connect(path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def default_poi_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return root / "NCDR Ukraine" / "personal_poi.sqlite"


class VirtualCID:
    def __init__(self, root: tk.Tk, map_path: Path, poi_path: Path):
        self.root, self.map_path, self.poi_path = root, map_path, poi_path
        self.store = OSMStore(map_path)
        self.poi = PoiStore(poi_path)
        # Display the window before reading map geometry. The regional database
        # is large enough that loading it synchronously looks like a failed GUI
        # launch even though Python is still working.
        self.ways: list[dict[str, Any]] = []
        self._ordered_ways: list[dict[str, Any]] = []
        self._geometry_queue: queue.Queue[tuple[list[dict[str, Any]], tuple[float, float, float, float]] | str] = queue.Queue()
        self.route_nodes: list[tuple[str, float, float]] = []
        self.route_limitations: tuple[str, ...] = ()
        self.gps_index = 0
        self.gps_running = False
        self.search_results: list[tuple[str, Any]] = []
        self.start_point: tuple[float, float, str] | None = None
        self.end_point: tuple[float, float, str] | None = None
        self.map_click: tuple[float, float] | None = None
        self.zoom = 1.0
        self.bounds = CITY_VIEW
        self._build_ui()
        self.redraw()
        self.status.configure(text="Карта завантажується у фоновому потоці…")
        self.root.after(100, self._start_geometry_load)

    def _start_geometry_load(self) -> None:
        threading.Thread(target=self._geometry_worker, name="ncdr-map-geometry", daemon=True).start()
        self.root.after(150, self._poll_geometry_load)

    def _geometry_worker(self) -> None:
        try:
            ways = list(self.store.iter_map_ways(limit=16_000))
            pts = [p for way in ways for p in way["coordinates"]
                   if CITY_VIEW[0] <= p["latitude"] <= CITY_VIEW[2]
                   and CITY_VIEW[1] <= p["longitude"] <= CITY_VIEW[3]]
            if not pts:
                raise ValueError("У локальній карті немає геометрії доріг")
            bounds = (min(p["latitude"] for p in pts), min(p["longitude"] for p in pts),
                      max(p["latitude"] for p in pts), max(p["longitude"] for p in pts))
            layer_order = {"waterway": 0, "landuse": 1, "railway": 2, "residential": 3}
            ways.sort(key=lambda w: layer_order.get(
                next((k for k in ("waterway", "landuse", "railway") if k in w["tags"]),
                     w["tags"].get("highway", "residential")), 3))
            self._geometry_queue.put((ways, bounds))
        except Exception as exc:
            self._geometry_queue.put(f"{type(exc).__name__}: {exc}")

    def _poll_geometry_load(self) -> None:
        try:
            result = self._geometry_queue.get_nowait()
        except queue.Empty:
            self.root.after(250, self._poll_geometry_load)
            return
        if isinstance(result, str):
            self.status.configure(text=f"Помилка завантаження карти: {result}")
            messagebox.showerror("Карта", result, parent=self.root)
            return
        self.ways, self.bounds = result
        self._ordered_ways = self.ways
        self.status.configure(text=self._dataset_label())
        self.redraw()

    def _bounds(self) -> tuple[float, float, float, float]:
        pts = [p for way in self.ways for p in way["coordinates"]
               if CITY_VIEW[0] <= p["latitude"] <= CITY_VIEW[2]
               and CITY_VIEW[1] <= p["longitude"] <= CITY_VIEW[3]]
        if not pts:
            pts = [p for way in self.ways for p in way["coordinates"]]
        if not pts:
            raise ValueError("У локальній карті немає геометрії доріг")
        return (min(p["latitude"] for p in pts), min(p["longitude"] for p in pts),
                max(p["latitude"] for p in pts), max(p["longitude"] for p in pts))

    def _build_ui(self) -> None:
        self.root.title("NCDR Ukraine · Virtual CID · Кривий Ріг")
        self.root.geometry("1320x820")
        self.root.minsize(960, 640)
        self.root.configure(bg="#eef2f4")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TButton", padding=7)
        header = ttk.Frame(self.root, padding=(12, 9))
        header.pack(fill="x")
        ttk.Label(header, text="Кривий Ріг", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(header, text="OSM Simulation", foreground="#116644", font=("Segoe UI", 11, "bold")).pack(side="left", padx=18)
        ttk.Label(header, text="NCDR Validation недоступний: незалежний читач образу ще не підтверджений",
                  foreground="#785500").pack(side="right")
        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=4)
        left = ttk.Frame(body, width=370, padding=8)
        map_frame = ttk.Frame(body, padding=4)
        body.add(left, weight=0)
        body.add(map_frame, weight=1)

        ttk.Label(left, text="Пошук адреси, вулиці або POI").pack(anchor="w")
        searchbar = ttk.Frame(left)
        searchbar.pack(fill="x", pady=(4, 7))
        self.query = tk.StringVar()
        entry = ttk.Entry(searchbar, textvariable=self.query)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.search())
        ttk.Button(searchbar, text="Знайти", command=self.search).pack(side="left", padx=(5, 0))
        self.results = tk.Listbox(left, height=10, activestyle="dotbox", font=("Segoe UI", 9))
        self.results.pack(fill="x")
        ttk.Label(left, text="Вибраний результат можна призначити початком або пунктом призначення.",
                  wraplength=330, foreground="#59636a").pack(anchor="w", pady=(4, 3))
        routebar = ttk.Frame(left)
        routebar.pack(fill="x", pady=3)
        ttk.Button(routebar, text="Початок", command=lambda: self.set_endpoint("start")).pack(side="left", expand=True, fill="x")
        ttk.Button(routebar, text="Фініш", command=lambda: self.set_endpoint("end")).pack(side="left", expand=True, fill="x", padx=4)
        ttk.Button(routebar, text="Маршрут", command=self.build_route).pack(side="left", expand=True, fill="x")
        self.route_label = ttk.Label(left, text="Маршрут ще не побудовано", wraplength=330)
        self.route_label.pack(fill="x", pady=(3, 8))
        gpsbar = ttk.Frame(left)
        gpsbar.pack(fill="x", pady=(0, 7))
        ttk.Button(gpsbar, text="▶ GPS-симуляція", command=self.start_gps).pack(side="left", expand=True, fill="x")
        ttk.Button(gpsbar, text="■ Стоп", command=self.stop_gps).pack(side="left", expand=True, fill="x", padx=(5, 0))
        ttk.Separator(left).pack(fill="x", pady=6)
        ttk.Label(left, text="Мої місця", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        poibar = ttk.Frame(left)
        poibar.pack(fill="x", pady=5)
        ttk.Button(poibar, text="＋ Додати на карті", command=self.add_poi).pack(side="left", expand=True, fill="x")
        ttk.Button(poibar, text="Редагувати", command=self.edit_poi).pack(side="left", expand=True, fill="x", padx=4)
        ttk.Button(poibar, text="Видалити", command=self.delete_poi).pack(side="left", expand=True, fill="x")
        self.poi_list = tk.Listbox(left, height=7, activestyle="dotbox", font=("Segoe UI", 9))
        self.poi_list.pack(fill="x")
        self.refresh_pois()
        importbar = ttk.Frame(left)
        importbar.pack(fill="x", pady=5)
        ttk.Button(importbar, text="Імпорт JSON", command=self.import_pois).pack(side="left", expand=True, fill="x")
        ttk.Button(importbar, text="Експорт JSON", command=self.export_pois).pack(side="left", expand=True, fill="x", padx=(5, 0))
        self.status = ttk.Label(left, text=self._dataset_label(), wraplength=330, foreground="#53616a")
        self.status.pack(anchor="w", pady=(6, 0))
        self.canvas = tk.Canvas(map_frame, background="#f7f7f2", highlightthickness=1, highlightbackground="#c9d1d7")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.redraw())
        self.canvas.bind("<Button-1>", self.on_map_click)
        self.canvas.bind("<MouseWheel>", self.on_zoom)
        ttk.Label(self.root, text=ATTRIBUTION, background="#e2e8ec", foreground="#34434b",
                  anchor="center", padding=5).pack(fill="x")

    def _dataset_label(self) -> str:
        meta = self.store.metadata
        return (f"Локальна база: {Path(meta.get('source_path', '')).name} · "
                f"{meta.get('routable_way_count', '?')} проїзних відрізків · "
                f"{meta.get('poi_count', '?')} OSM POI\n" +
                "Маршрут: найкоротша відстань за автомобільним профілем; повороти поки не обмежені.")

    def _xy(self, lat: float, lon: float) -> tuple[float, float]:
        h, w = max(200, self.canvas.winfo_height()), max(300, self.canvas.winfo_width())
        lat0, lon0, lat1, lon1 = self.bounds
        c = math.cos(math.radians((lat0+lat1)/2))
        map_w, map_h = max(0.0001, (lon1-lon0)*c), max(0.0001, lat1-lat0)
        scale = min((w-40)/map_w, (h-40)/map_h) * self.zoom
        used_w, used_h = map_w*scale, map_h*scale
        x = (w-used_w)/2 + (lon-lon0)*c*scale
        y = (h-used_h)/2 + (lat1-lat)*scale
        return x, y

    def redraw(self) -> None:
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        layer_order = {"waterway": 0, "landuse": 1, "railway": 2, "residential": 3}
        ordered = self._ordered_ways
        road_colors = {"motorway": "#d27862", "trunk": "#d27862", "primary": "#e5ad66", "secondary": "#f0c983", "tertiary": "#f6dfb5", "residential": "#ffffff", "service": "#ffffff", "unclassified": "#ffffff"}
        for way in ordered:
            tags = way["tags"]
            coords = [self._xy(p["latitude"], p["longitude"]) for p in way["coordinates"]]
            if len(coords) < 2:
                continue
            if "waterway" in tags:
                color, width = "#8bbbd3", 2
            elif tags.get("natural") == "water" or tags.get("landuse") in {"reservoir", "basin"}:
                color, width = "#c0dce9", 2
            elif tags.get("landuse") in {"grass", "forest", "recreation_ground", "village_green"} or tags.get("leisure") == "park":
                color, width = "#d9e8d4", 2
            elif "railway" in tags:
                color, width = "#8c8990", 1
            else:
                road = tags.get("highway", "")
                if road not in road_colors:
                    continue
                color, width = road_colors[road], 3 if road in {"primary", "trunk", "motorway"} else 1.6
            flat = [v for xy in coords for v in xy]
            self.canvas.create_line(*flat, fill=color, width=width, capstyle="round", joinstyle="round")
        if self.route_nodes:
            pts = [self._xy(lat, lon) for _nid, lat, lon in self.route_nodes]
            if len(pts) >= 2:
                self.canvas.create_line(*[v for xy in pts for v in xy], fill="#135ecb", width=5, capstyle="round", joinstyle="round")
            for idx, (lat, lon) in enumerate((self.route_nodes[0][1:], self.route_nodes[-1][1:])):
                x, y = self._xy(lat, lon)
                self.canvas.create_oval(x-7, y-7, x+7, y+7, fill="#1267d5" if idx == 0 else "#d04a42", outline="white", width=2)
        for poi in self.poi.all():
            x, y = self._xy(poi["latitude"], poi["longitude"])
            self.canvas.create_oval(x-5, y-5, x+5, y+5, fill="#7546b8", outline="white", width=1)
        if self.gps_running and self.route_nodes:
            _nid, lat, lon = self.route_nodes[self.gps_index % len(self.route_nodes)]
            x, y = self._xy(lat, lon)
            self.canvas.create_oval(x-9, y-9, x+9, y+9, fill="#24a66a", outline="white", width=2)

    def search(self) -> None:
        query = self.query.get().strip()
        self.search_results = [("OSM", r) for r in self.store.search(query, limit=50)]
        self.search_results.extend(("POI", row) for row in self.poi.search(query))
        self.results.delete(0, tk.END)
        for source, row in self.search_results:
            label = row.name if source == "OSM" else row["name_uk"]
            address = row.address if source == "OSM" else row["category"]
            self.results.insert(tk.END, f"[{source}] {label}" + (f" — {address}" if address else ""))
        self.status.configure(text=f"Знайдено: {len(self.search_results)} · джерело OSM локально")
        if not self.search_results:
            messagebox.showinfo("Пошук", "Збігів у локальній базі не знайдено.")

    def _selected_point(self) -> tuple[float, float, str] | None:
        selection = self.results.curselection()
        if not selection:
            return None
        source, row = self.search_results[selection[0]]
        if source == "OSM":
            if row.latitude is None or row.longitude is None:
                return None
            return row.latitude, row.longitude, row.address or row.name
        return row["latitude"], row["longitude"], row["name_uk"]

    def set_endpoint(self, which: str) -> None:
        point = self._selected_point()
        if point is None:
            messagebox.showwarning("Маршрут", "Виберіть об'єкт із координатами.")
            return
        if which == "start":
            self.start_point = point
        else:
            self.end_point = point
        self.route_label.configure(text=f"Початок: {self.start_point[2] if self.start_point else '—'}\nФініш: {self.end_point[2] if self.end_point else '—'}")

    def build_route(self) -> None:
        if not self.start_point or not self.end_point:
            messagebox.showwarning("Маршрут", "Спочатку знайдіть і задайте початок та фініш.")
            return
        start = self.store.nearest_routable_node(*self.start_point[:2], max_distance_m=5000)
        end = self.store.nearest_routable_node(*self.end_point[:2], max_distance_m=5000)
        if not start or not end:
            messagebox.showerror("Маршрут", "Не знайдено поруч вузол дороги.")
            return
        route = self.store.route(start[0], end[0])
        if not route:
            messagebox.showerror("Маршрут", "Шлях між об'єктами не знайдено.")
            return
        with sqlite3.connect(self.map_path) as conn:
            by_id = {row[0]: (row[1], row[2]) for row in conn.execute(
                "SELECT id,latitude,longitude FROM nodes WHERE id IN (" + ",".join("?" for _ in route.node_ids) + ")", route.node_ids)}
        self.route_nodes = [(node_id, *by_id[node_id]) for node_id in route.node_ids if node_id in by_id]
        self.route_limitations = route.limitations
        limitation = " · повороти ще не враховані" if route.limitations else ""
        self.route_label.configure(text=f"{self.start_point[2]} → {self.end_point[2]}\n{route.distance_m/1000:.2f} км · вузлів {len(route.node_ids)}{limitation}")
        self.redraw()

    def start_gps(self) -> None:
        if not self.route_nodes:
            messagebox.showinfo("GPS", "Спочатку побудуйте тестовий маршрут.")
            return
        self.gps_running = True
        self._gps_tick()

    def _gps_tick(self) -> None:
        if not self.gps_running:
            return
        self.redraw()
        self.gps_index += 1
        self.root.after(650, self._gps_tick)

    def stop_gps(self) -> None:
        self.gps_running = False
        self.redraw()

    def on_map_click(self, event: tk.Event) -> None:
        self.map_click = self._geo(event.x, event.y)
        lat, lon = self.map_click
        self.status.configure(text=f"Точка карти: {lat:.6f}, {lon:.6f} · Натисніть «Додати на карті»")

    def _geo(self, x: float, y: float) -> tuple[float, float]:
        h, w = max(200, self.canvas.winfo_height()), max(300, self.canvas.winfo_width())
        lat0, lon0, lat1, lon1 = self.bounds
        c = math.cos(math.radians((lat0+lat1)/2))
        map_w, map_h = max(0.0001, (lon1-lon0)*c), max(0.0001, lat1-lat0)
        scale = min((w-40)/map_w, (h-40)/map_h) * self.zoom
        used_w, used_h = map_w*scale, map_h*scale
        lon = lon0 + (x-(w-used_w)/2)/(c*scale)
        lat = lat1 - (y-(h-used_h)/2)/scale
        return lat, lon

    def on_zoom(self, event: tk.Event) -> None:
        self.zoom = min(5.0, max(0.35, self.zoom * (1.15 if event.delta > 0 else 1/1.15)))
        self.redraw()

    def _poi_dialog(self, row: dict[str, Any] | None = None) -> None:
        row = row or {}
        dialog = tk.Toplevel(self.root)
        dialog.title("Моє місце")
        dialog.transient(self.root)
        dialog.grab_set()
        form = ttk.Frame(dialog, padding=14)
        form.pack(fill="both", expand=True)
        point = self.map_click or (self.bounds[0] + (self.bounds[2]-self.bounds[0])/2,
                                   self.bounds[1] + (self.bounds[3]-self.bounds[1])/2)
        fields = [("Назва українською", str(row.get("name_uk", ""))),
                  ("Широта", str(row.get("latitude", point[0]))),
                  ("Довгота", str(row.get("longitude", point[1]))),
                  ("Категорія", str(row.get("category", "Інше"))),
                  ("Альтернативні назви через ;", "; ".join(row.get("aliases", [])))]
        vars_: list[tk.StringVar] = []
        for label, value in fields:
            ttk.Label(form, text=label).pack(anchor="w")
            var = tk.StringVar(value=value)
            ttk.Entry(form, textvariable=var, width=48).pack(fill="x", pady=(0, 7))
            vars_.append(var)
        def save() -> None:
            try:
                saved = self.poi.save(vars_[0].get(), float(vars_[1].get()), float(vars_[2].get()),
                                      vars_[3].get(), vars_[4].get().split(";"), row.get("id"))
            except (ValueError, sqlite3.Error) as exc:
                messagebox.showerror("Не збережено", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.refresh_pois()
            self.status.configure(text=f"Збережено: {saved['name_uk']} · {self.poi_path}")
        ttk.Button(form, text="Зберегти", command=save).pack(anchor="e")
        dialog.bind("<Return>", lambda _e: save())

    def add_poi(self) -> None:
        self._poi_dialog()

    def _selected_poi(self) -> dict[str, Any] | None:
        selection = self.poi_list.curselection()
        if not selection:
            return None
        rows = self.poi.all()
        return rows[selection[0]] if selection[0] < len(rows) else None

    def edit_poi(self) -> None:
        row = self._selected_poi()
        if not row:
            messagebox.showinfo("Мої місця", "Виберіть місце для редагування.")
            return
        self._poi_dialog(row)

    def delete_poi(self) -> None:
        row = self._selected_poi()
        if not row:
            return
        if messagebox.askyesno("Видалити місце", f"Видалити «{row['name_uk']}»?"):
            self.poi.delete(row["id"])
            self.refresh_pois()

    def refresh_pois(self) -> None:
        if not hasattr(self, "poi_list"):
            return
        self.poi_list.delete(0, tk.END)
        for row in self.poi.all():
            self.poi_list.insert(tk.END, f"{row['name_uk']} · {row['category']}")
        self.redraw()

    def export_pois(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON POI", "*.json")])
        if path:
            self.poi.export_json(path)
            messagebox.showinfo("Експорт", f"Файл збережено: {path}")

    def import_pois(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON POI", "*.json")])
        if path:
            try:
                imported, skipped = self.poi.import_json(path)
            except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
                messagebox.showerror("Імпорт POI", str(exc))
                return
            self.refresh_pois()
            messagebox.showinfo("Імпорт POI", f"Додано: {imported}; дублікати пропущено: {skipped}")


def launch(map_path: Path = DEFAULT_MAP, poi_path: Path | None = None) -> int:
    if not map_path.is_file():
        raise FileNotFoundError(f"Не знайдено локальну OSM-карту: {map_path}\nСпочатку запустіть importer.")
    root = tk.Tk()
    VirtualCID(root, map_path, poi_path or default_poi_path())
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Кривий Ріг: OSM Simulation, редактор POI та Virtual CID")
    parser.add_argument("--map-db", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--poi-db", type=Path, default=default_poi_path())
    args = parser.parse_args(argv)
    return launch(args.map_db, args.poi_db)


if __name__ == "__main__":
    raise SystemExit(main())
