"""TS to MP4 Converter — desktop app."""
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from collections import Counter
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk
from typing import Optional

from tsconverter import feedback, history, tray, updater
from tsconverter.media import thumbnail
from tsconverter.media.handlers import REGISTRY, get_handler
from tsconverter.queue import QueueController

from converter import (
    ConflictPolicy,
    Converter,
    Job,
    MODE_LABELS,
    Mode,
    detect_hw_encoders,
    get_logs_dir,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except ImportError:
    _HAS_DND = False

try:
    import sv_ttk
    _HAS_SVTTK = True
except ImportError:
    _HAS_SVTTK = False

APP_NAME = "TS to MP4 Converter"
APP_VERSION = "1.7.3"
SAME_AS_SOURCE = "(same folder as source)"


def get_config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA", str(Path.home()))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    p = Path(base) / "TSConverter"
    p.mkdir(parents=True, exist_ok=True)
    return p


class Settings:
    PATH = get_config_dir() / "settings.json"

    DEFAULTS = {
        "output_dir": SAME_AS_SOURCE,
        "mode": Mode.AUTO.value,
        "out_format": "mp4",
        "conflict": ConflictPolicy.RENAME.value,
        "prefer_hw": True,
        "concurrency": 2,
        "theme": "light",
        "geometry": "880x600",
        "delete_source_after_success": False,
        "delete_source_warned": False,
        "check_updates": True,
        "skip_update_version": "",
        "minimize_to_tray": False,
        "col_widths": {},
        "show_thumbs": False,
        "last_seen_version": "",
    }

    def __init__(self):
        self.data = dict(self.DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.PATH, "r", encoding="utf-8") as fp:
                self.data.update(json.load(fp))
        except (OSError, json.JSONDecodeError):
            pass

    def save(self):
        try:
            with open(self.PATH, "w", encoding="utf-8") as fp:
                json.dump(self.data, fp, indent=2)
        except OSError:
            pass

    def get(self, key):
        return self.data.get(key, self.DEFAULTS.get(key))

    def set(self, key, value):
        self.data[key] = value


def fmt_size(n: int) -> str:
    if n <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_duration(seconds: float) -> str:
    if seconds <= 0:
        return ""
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_eta(seconds: float) -> str:
    if seconds <= 0 or seconds > 24 * 3600:
        return ""
    return fmt_duration(seconds)


def open_in_explorer(path: Path):
    path = Path(path)
    if not path.exists():
        return
    if os.name == "nt":
        if path.is_file():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R" if path.is_file() else "", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent if path.is_file() else path)])


class App:
    def __init__(self, root):
        self.root = root
        self.settings = Settings()
        self.jobs: list[Job] = []
        self.job_by_iid: dict[str, Job] = {}
        self._dirty_rows: set[str] = set()      # iids needing a redraw
        self._row_thumbs: dict[str, tk.PhotoImage] = {}   # iid -> image (keeps refs alive)
        self._dirty_lock = threading.Lock()
        self._flush_scheduled = False
        self.is_running = False
        self.converter = Converter(prefer_hw=self.settings.get("prefer_hw"))
        self.history = history.HistoryStore(get_config_dir() / "history.json")
        self.queue = QueueController(
            self.converter,
            refresh=self._refresh_row,
            record=self._record_history,
            set_overall=self._set_overall,
            finished=lambda d, f, c, t: self.root.after(0, lambda: self._finish(d, f, c, t)),
            concurrency=lambda: int(self.settings.get("concurrency") or 2),
            should_delete_source=lambda: bool(self.settings.get("delete_source_after_success")),
        )
        self.tray: Optional[tray.Tray] = None
        self._tray_quit = False
        self._hidden = False
        self._drag_iid: Optional[str] = None
        self._drag_started: bool = False

        self._setup_window()
        self._build_ui()
        self._enable_dnd()
        self._refresh_button_state()
        # Before the restore-queue prompt (200ms) so that modal lands on top, not under it.
        self.root.after(100, lambda: self.show_whats_new(auto=True))
        self.root.after(200, self._load_queue_if_exists)
        if self.settings.get("check_updates"):
            self.root.after(1500, lambda: self._check_updates_async(manual=False))

    def _setup_window(self):
        self.root.title(APP_NAME)
        self.root.geometry(self.settings.get("geometry"))
        self.root.minsize(720, 460)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        if _HAS_SVTTK:
            try:
                theme = self.settings.get("theme")
                sv_ttk.set_theme("dark" if theme == "dark" else "light")
            except Exception:
                pass

    def _build_ui(self):
        self._build_menu()

        # Toolbar
        toolbar = ttk.Frame(self.root, padding=(10, 8, 10, 4))
        toolbar.pack(fill="x")

        ttk.Button(toolbar, text="Add files", command=self.add_files).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Add folder", command=self.add_folder).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Remove", command=self.remove_selected).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Clear", command=self.clear_files).pack(side="left", padx=2)
        self.retry_btn = ttk.Button(toolbar, text="Retry failed", command=self.retry_failed)
        self.retry_btn.pack(side="left", padx=2)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Inspect", command=self.inspect_selected).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Show in folder", command=self.show_in_folder).pack(side="left", padx=2)
        self.show_thumbs_var = tk.BooleanVar(value=bool(self.settings.get("show_thumbs")))
        ttk.Checkbutton(
            toolbar, text="Show thumbnails", variable=self.show_thumbs_var,
            command=self._on_thumbs_toggle,
            style="Switch.TCheckbutton" if _HAS_SVTTK else "TCheckbutton",
        ).pack(side="right", padx=2)

        # Options strip
        opts = ttk.Frame(self.root, padding=(10, 4))
        opts.pack(fill="x")

        ttk.Label(opts, text="Mode:").pack(side="left", padx=(0, 4))
        self.mode_var = tk.StringVar(value=MODE_LABELS[Mode(self.settings.get("mode"))])
        mode_combo = ttk.Combobox(
            opts, textvariable=self.mode_var, state="readonly", width=30,
            values=list(MODE_LABELS.values()),
        )
        mode_combo.pack(side="left", padx=2)
        mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)

        ttk.Separator(opts, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(opts, text="Format:").pack(side="left", padx=(0, 4))
        cur_fmt = self.settings.get("out_format")
        if cur_fmt not in REGISTRY:
            cur_fmt = "mp4"
        self._fmt_label_to_id = {h.label: fid for fid, h in REGISTRY.items()}
        self.format_var = tk.StringVar(value=REGISTRY[cur_fmt].label)
        fmt_combo = ttk.Combobox(
            opts, textvariable=self.format_var, state="readonly", width=18,
            values=[h.label for h in REGISTRY.values()],
        )
        fmt_combo.pack(side="left", padx=2)
        fmt_combo.bind("<<ComboboxSelected>>", self._on_format_change)

        ttk.Separator(opts, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(opts, text="Parallel:").pack(side="left", padx=(0, 4))
        self.concurrency_var = tk.StringVar(value=str(self.settings.get("concurrency")))
        conc_combo = ttk.Combobox(
            opts, textvariable=self.concurrency_var, state="readonly", width=4,
            values=["1", "2", "3", "4", "5", "6", "8"],
        )
        conc_combo.pack(side="left", padx=2)
        conc_combo.bind("<<ComboboxSelected>>", self._on_concurrency_change)

        ttk.Separator(opts, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(opts, text="If exists:").pack(side="left", padx=(0, 4))
        self.conflict_var = tk.StringVar(value=self.settings.get("conflict"))
        for label, val in (("Rename", ConflictPolicy.RENAME.value),
                          ("Overwrite", ConflictPolicy.OVERWRITE.value),
                          ("Skip", ConflictPolicy.SKIP.value)):
            ttk.Radiobutton(
                opts, text=label, value=val, variable=self.conflict_var,
                command=self._on_conflict_change,
            ).pack(side="left", padx=2)

        # Output folder
        out_frame = ttk.Frame(self.root, padding=(10, 4))
        out_frame.pack(fill="x")
        ttk.Label(out_frame, text="Output:").pack(side="left", padx=(0, 6))
        self.output_var = tk.StringVar(value=self.settings.get("output_dir"))
        out_label = ttk.Label(out_frame, textvariable=self.output_var, foreground="#555")
        out_label.pack(side="left", fill="x", expand=True)
        ttk.Button(out_frame, text="Browse", command=self.choose_output).pack(side="right", padx=2)
        ttk.Button(out_frame, text="Same as source", command=self.reset_output).pack(side="right", padx=2)

        # File list
        list_wrap = ttk.Frame(self.root, padding=(10, 4))
        list_wrap.pack(fill="both", expand=True)

        cols = ("file", "size", "duration", "status", "progress", "speed", "eta")
        self.tree = ttk.Treeview(list_wrap, columns=cols, show="headings", selectmode="extended")
        # (key, label, default width, min width, stretch, anchor). Only File/Status
        # stretch, so window resizes and border drags don't reshuffle numeric columns.
        headings = [
            ("file", "File", 260, 140, True, "w"),
            ("size", "Size", 80, 50, False, "e"),
            ("duration", "Length", 80, 50, False, "e"),
            ("status", "Status", 200, 120, True, "w"),
            ("progress", "Progress", 80, 50, False, "e"),
            ("speed", "Speed", 70, 50, False, "e"),
            ("eta", "ETA", 70, 50, False, "e"),
        ]
        saved = self.settings.get("col_widths")
        saved = saved if isinstance(saved, dict) else {}
        for key, label, width, minw, stretch, anchor in headings:
            w = saved.get(key)
            if not isinstance(w, int) or w < minw:   # settings.json is hand-editable
                w = width
            self.tree.heading(key, text=label)
            self.tree.column(key, width=w, minwidth=minw, stretch=stretch, anchor=anchor)
        self.tree.tag_configure("failed", foreground="#b00020")
        self.tree.tag_configure("done", foreground="#0a7d29")
        self.tree.tag_configure("cancelled", foreground="#996600")
        self.tree.tag_configure("running", foreground="#0a4d9e")
        self.tree.bind("<Double-1>", self._on_row_double_click)
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<ButtonPress-1>", self._on_tree_press, add="+")
        self.tree.bind("<B1-Motion>", self._on_tree_drag, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release, add="+")

        sb = ttk.Scrollbar(list_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._apply_thumbs_mode()

        # Drop hint overlay
        if _HAS_DND:
            hint = ttk.Label(self.root, text="Tip: drag .ts / .mkv / .mp4 / .mov … video files into the window",
                             foreground="#888", padding=(10, 0))
            hint.pack(fill="x")

        # Bottom: overall progress + start/cancel
        bot = ttk.Frame(self.root, padding=(10, 6, 10, 10))
        bot.pack(fill="x")

        self.overall_progress = ttk.Progressbar(bot, mode="determinate", maximum=100)
        self.overall_progress.pack(fill="x", pady=(0, 6))

        bot_row = ttk.Frame(bot)
        bot_row.pack(fill="x")
        self.status_label = ttk.Label(bot_row, text=self._initial_status_text())
        self.status_label.pack(side="left")

        self.cancel_btn = ttk.Button(bot_row, text="Cancel", command=self.cancel_all, state="disabled")
        self.cancel_btn.pack(side="right", padx=2)

        self.pause_btn = ttk.Button(bot_row, text="Pause", command=self.toggle_pause, state="disabled")
        self.pause_btn.pack(side="right", padx=2)

        self.start_btn = ttk.Button(bot_row, text="Start", command=self.start, style="Accent.TButton")
        self.start_btn.pack(side="right", padx=2)

        if feedback.FORM_URL:
            self._link_font = tkfont.nametofont("TkDefaultFont").copy()   # ref: Tk drops it on GC
            self._link_font.configure(underline=True)
            link = ttk.Label(bot_row, text="Send feedback", cursor="hand2", font=self._link_font)
            link.pack(side="right", padx=(0, 14))
            link.bind("<Button-1>", lambda e: self.send_feedback())

        # Right-click context menu
        self.ctx_menu = tk.Menu(self.root, tearoff=0)
        self.ctx_menu.add_command(label="Open output", command=self.open_output_file)
        self.ctx_menu.add_command(label="Show in folder", command=self.show_in_folder)
        self.ctx_menu.add_command(label="Open log", command=self.open_log_file)
        self.ctx_menu.add_command(label="Preview", command=self.preview_selected)
        self.ctx_menu.add_command(label="Inspect", command=self.inspect_selected)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="Remove from list", command=self.remove_selected)

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Add files...", command=self.add_files, accelerator="Ctrl+O")
        file_menu.add_command(label="Clear list", command=self.clear_files)
        file_menu.add_separator()
        file_menu.add_command(label="Conversion history...", command=self.show_history)
        file_menu.add_command(label="Conversion analytics...", command=self.show_analytics)
        file_menu.add_command(label="Thumbnail gallery...", command=self.show_gallery)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._quit_app)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.bind_all("<Control-o>", lambda e: self.add_files())

        edit_menu = tk.Menu(menubar, tearoff=0)
        self.hw_var = tk.BooleanVar(value=self.settings.get("prefer_hw"))
        edit_menu.add_checkbutton(
            label="Prefer GPU encoding when available",
            variable=self.hw_var, command=self._on_hw_change,
        )
        self.delete_after_var = tk.BooleanVar(
            value=self.settings.get("delete_source_after_success")
        )
        edit_menu.add_checkbutton(
            label="Delete source file after successful conversion",
            variable=self.delete_after_var, command=self._on_delete_after_change,
        )
        self.tray_var = tk.BooleanVar(value=self.settings.get("minimize_to_tray"))
        edit_menu.add_checkbutton(
            label="Minimize to system tray on close",
            variable=self.tray_var, command=self._on_tray_change,
            state="normal" if tray.available() else "disabled",
        )
        edit_menu.add_separator()
        saved_theme = self.settings.get("theme")
        if saved_theme not in ("light", "dark"):
            saved_theme = "light"
        self.theme_var = tk.StringVar(value=saved_theme)
        theme_state = "normal" if _HAS_SVTTK else "disabled"
        edit_menu.add_radiobutton(
            label="Light theme", variable=self.theme_var, value="light",
            command=self._on_theme_change, state=theme_state,
        )
        edit_menu.add_radiobutton(
            label="Dark theme", variable=self.theme_var, value="dark",
            command=self._on_theme_change, state=theme_state,
        )
        menubar.add_cascade(label="Settings", menu=edit_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Check for updates...",
                              command=lambda: self._check_updates_async(manual=True))
        self.check_updates_var = tk.BooleanVar(value=self.settings.get("check_updates"))
        help_menu.add_checkbutton(
            label="Check for updates on startup",
            variable=self.check_updates_var, command=self._on_check_updates_change,
        )
        help_menu.add_separator()
        help_menu.add_command(label="What's new", command=self.show_whats_new)
        if feedback.FORM_URL:
            help_menu.add_command(label="Send feedback...", command=self.send_feedback)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

    def _initial_status_text(self):
        hw = detect_hw_encoders()
        if hw:
            return f"Ready  •  GPU encoder available: {hw[0]}"
        return "Ready  •  CPU encoding only"

    def _enable_dnd(self):
        if not _HAS_DND:
            return
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event):
        raw = event.data
        paths = self.root.tk.splitlist(raw)
        self._add_paths([p for p in paths if os.path.isfile(p)])

    SUPPORTED_EXTS = (".ts", ".m2ts", ".mts", ".mkv", ".mp4", ".mov", ".avi",
                      ".flv", ".webm", ".wmv", ".m4v", ".mpg", ".mpeg")

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select video files",
            filetypes=[
                ("Video files", "*.ts *.m2ts *.mts *.mkv *.mp4 *.mov *.avi "
                                "*.flv *.webm *.wmv *.m4v *.mpg *.mpeg"),
                ("MPEG-TS files", "*.ts *.m2ts *.mts"),
                ("Matroska / WebM", "*.mkv *.webm"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            self._add_paths(list(paths))

    def add_folder(self):
        d = filedialog.askdirectory(title="Select a folder to scan for video files")
        if not d:
            return
        found = []
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith(self.SUPPORTED_EXTS):
                    found.append(os.path.join(root, f))
        if not found:
            messagebox.showinfo(
                "Add folder",
                f"No supported video files found under:\n{d}",
            )
            return
        self._add_paths(found)

    def _add_paths(self, paths):
        existing = {str(j.src) for j in self.jobs}
        added = 0
        new_jobs = []
        for p in paths:
            p = os.path.abspath(p)
            if p in existing:
                continue
            src = Path(p)
            try:
                size = src.stat().st_size
            except OSError:
                size = 0
            job = Job(src=src, out_dir=Path("."), file_size=size)
            self.jobs.append(job)
            iid = str(id(job))
            self.job_by_iid[iid] = job
            self.tree.insert("", "end", iid=iid, values=self._row_values(job))
            existing.add(p)
            added += 1
            new_jobs.append(job)
        if added:
            self._refresh_button_state()
            self._save_queue()
            if self.show_thumbs_var.get():
                self._load_thumbs_async(new_jobs, self._THUMB_W, self._set_row_thumb,
                                        height=self._THUMB_H)

    def remove_selected(self):
        if self.is_running:
            return
        for iid in self.tree.selection():
            job = self.job_by_iid.pop(iid, None)
            if job:
                self.jobs.remove(job)
            self._row_thumbs.pop(iid, None)   # iid = id(job); a reused id must not inherit it
            self.tree.delete(iid)
        self._refresh_button_state()
        self._save_queue()

    def clear_files(self):
        if self.is_running:
            return
        self.tree.delete(*self.tree.get_children())
        self.jobs.clear()
        self.job_by_iid.clear()
        self._row_thumbs.clear()
        self._refresh_button_state()
        self._clear_queue_file()

    def choose_output(self):
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self.output_var.set(d)
            self.settings.set("output_dir", d)
            self.settings.save()

    def reset_output(self):
        self.output_var.set(SAME_AS_SOURCE)
        self.settings.set("output_dir", SAME_AS_SOURCE)
        self.settings.save()

    def _on_mode_change(self, _event=None):
        label = self.mode_var.get()
        for mode, lbl in MODE_LABELS.items():
            if lbl == label:
                self.settings.set("mode", mode.value)
                self.settings.save()
                break

    def _selected_format(self) -> str:
        return self._fmt_label_to_id.get(self.format_var.get(), "mp4")

    def _on_format_change(self, _event=None):
        self.settings.set("out_format", self._selected_format())
        self.settings.save()

    def _on_conflict_change(self):
        self.settings.set("conflict", self.conflict_var.get())
        self.settings.save()

    def _on_concurrency_change(self, _event=None):
        try:
            n = int(self.concurrency_var.get())
        except ValueError:
            n = 2
        self.settings.set("concurrency", max(1, min(8, n)))
        self.settings.save()

    def _on_hw_change(self):
        v = self.hw_var.get()
        self.settings.set("prefer_hw", v)
        self.settings.save()
        self.converter.prefer_hw = v

    def _on_theme_change(self):
        theme = self.theme_var.get()
        self.settings.set("theme", theme)
        self.settings.save()
        if _HAS_SVTTK:
            try:
                sv_ttk.set_theme(theme)
            except Exception:
                pass
        self._apply_thumbs_mode()   # ttk style config is per-theme; re-apply row height

    def _on_delete_after_change(self):
        v = self.delete_after_var.get()
        if v and not self.settings.get("delete_source_warned"):
            ok = messagebox.askokcancel(
                "Delete source files?",
                "When this is enabled, the original file is permanently deleted "
                "after each successful conversion. It is NOT sent to the Recycle Bin.\n\n"
                "Make sure your output folder and 'If exists' policy are set correctly "
                "before running. Continue?",
                icon="warning",
            )
            if not ok:
                self.delete_after_var.set(False)
                return
            self.settings.set("delete_source_warned", True)
        self.settings.set("delete_source_after_success", v)
        self.settings.save()

    def _selected_mode(self) -> Mode:
        label = self.mode_var.get()
        for mode, lbl in MODE_LABELS.items():
            if lbl == label:
                return mode
        return Mode.AUTO

    def _selected_conflict(self) -> ConflictPolicy:
        return ConflictPolicy(self.conflict_var.get())

    def start(self):
        if self.is_running or not self.jobs:
            return

        mode = self._selected_mode()
        conflict = self._selected_conflict()
        out_format = self._selected_format()
        output_val = self.output_var.get()
        for j in self.jobs:
            if j.status in ("Done",):
                continue
            j.mode = mode
            j.conflict = conflict
            j.out_format = out_format
            j.out_dir = j.src.parent if output_val == SAME_AS_SOURCE else Path(output_val)
            j.status = "Queued"
            j.stage = ""
            j.error = None
            j.error_full = None
            j.seconds_done = 0
            j.speed = 0
            j.progress_pct = 0
            j.eta_seconds = 0
            j.out_path = None
            j.actually_used = None
            j.started_at = None
            j.completed_at = None
            self._refresh_row(j)

        self.is_running = True
        self.start_btn.config(state="disabled")
        self.retry_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.pause_btn.config(state="normal", text="Pause")
        self.status_label.config(text="Converting...")
        self.overall_progress.config(value=0)

        pending = [j for j in self.jobs if j.status != "Done"]
        self.queue.start(pending)

    def cancel_all(self):
        if not self.is_running:
            return
        self.queue.cancel()
        self.cancel_btn.config(state="disabled")
        self.pause_btn.config(state="disabled", text="Pause")
        self.status_label.config(text="Cancelling...")

    def toggle_pause(self):
        if not self.is_running:
            return
        if self.queue.toggle_pause():
            self.pause_btn.config(text="Resume")
            self.status_label.config(text="Paused (running jobs suspended; new ones held)")
        else:
            self.pause_btn.config(text="Pause")
            self.status_label.config(text="Converting...")

    def _finish(self, success, failed, cancelled, total):
        self.is_running = False
        self.start_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self.pause_btn.config(state="disabled", text="Pause")
        parts = [f"{success}/{total} done"]
        if failed:
            parts.append(f"{failed} failed")
        if cancelled:
            parts.append(f"{cancelled} cancelled")
        summary = "  •  ".join(parts)
        self.status_label.config(text=summary)
        self._refresh_button_state()
        self._save_queue()
        if self._hidden and self.tray:
            self.tray.notify(summary, "Conversions finished")

    def retry_failed(self):
        """Re-queue every Failed job and run them again."""
        if self.is_running:
            return
        retried = 0
        for j in self.jobs:
            if j.status == "Failed":
                j.status = "Queued"
                j.stage = ""
                j.error = None
                j.error_full = None
                j.progress_pct = 0
                j.seconds_done = 0
                j.speed = 0
                j.eta_seconds = 0
                self._refresh_row(j)
                retried += 1
        if retried:
            self.start()
        else:
            self._refresh_button_state()

    def _on_check_updates_change(self):
        self.settings.set("check_updates", bool(self.check_updates_var.get()))
        self.settings.save()

    def _check_updates_async(self, manual=False):
        def work():
            info = updater.check_for_update(APP_VERSION)
            self.root.after(0, lambda: self._on_update_result(info, manual))
        threading.Thread(target=work, daemon=True).start()

    def _on_update_result(self, info, manual):
        if info is None:
            if manual:
                messagebox.showinfo(
                    "Check for updates",
                    f"You're on the latest version (v{APP_VERSION}).",
                )
            return
        if (not manual) and info.version == self.settings.get("skip_update_version"):
            return

        # Installed Windows builds can download + run the installer directly;
        # dev / portable / other platforms just open the download page.
        can_self_update = (getattr(sys, "frozen", False) and os.name == "nt"
                           and bool(info.setup_url))
        if can_self_update:
            self._offer_self_update(info)
            return

        choice = messagebox.askyesnocancel(
            "Update available",
            f"{APP_NAME} {info.tag} is available — you have v{APP_VERSION}.\n\n"
            f"Yes — open the download page\n"
            f"No — remind me later\n"
            f"Cancel — skip this version",
        )
        if choice is True:
            webbrowser.open(info.url)
        elif choice is None:            # Cancel = skip this version
            self.settings.set("skip_update_version", info.version)
            self.settings.save()

    def _offer_self_update(self, info):
        win = tk.Toplevel(self.root)
        win.title("Update available")
        win.geometry("470x230")
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame, justify="left",
            text=f"{APP_NAME} {info.tag} is available.\nYou have v{APP_VERSION}.",
        ).pack(anchor="w")
        size_txt = f"  ({fmt_size(info.setup_size)})" if info.setup_size else ""
        status = ttk.Label(frame, foreground="#666",
                           text=f"Installer: {info.setup_name}{size_txt}")
        status.pack(anchor="w", pady=(6, 0))
        bar = ttk.Progressbar(frame, mode="determinate", maximum=100)

        btns = ttk.Frame(frame)
        btns.pack(side="bottom", fill="x", pady=(12, 0))

        def set_buttons(state):
            for w in btns.winfo_children():
                w.config(state=state)

        def do_skip():
            self.settings.set("skip_update_version", info.version)
            self.settings.save()
            win.destroy()

        def finish_dl(ok, dest):
            if not win.winfo_exists():
                return
            if not ok:
                status.config(text="Download failed. Try the download page instead.")
                set_buttons("normal")
                return
            if info.setup_size and dest.stat().st_size != info.setup_size:
                status.config(text="Downloaded file looks wrong (size mismatch).")
                set_buttons("normal")
                return
            status.config(text="Starting installer — the app will close and reopen…")
            self.root.after(400, lambda: self._run_installer_and_quit(dest))

        def do_download():
            set_buttons("disabled")
            bar.pack(fill="x", pady=(10, 0))
            status.config(text="Downloading…")
            dest = Path(tempfile.gettempdir()) / (info.setup_name or "TSConverter-setup.exe")

            def on_progress(read, total):
                self.root.after(0, lambda: bar.config(value=read / total * 100))

            def work():
                ok = updater.download(info.setup_url, str(dest), on_progress=on_progress)
                self.root.after(0, lambda: finish_dl(ok, dest))
            threading.Thread(target=work, daemon=True).start()

        ttk.Button(btns, text="Download & install", command=do_download).pack(side="left")
        ttk.Button(btns, text="Skip this version", command=do_skip).pack(side="right")
        ttk.Button(btns, text="Later", command=win.destroy).pack(side="right", padx=6)

    def _run_installer_and_quit(self, setup_path):
        # Wait for this app to close, run the installer silently, then relaunch.
        app_exe = sys.executable
        cmd = (f'timeout /t 2 /nobreak >nul & "{setup_path}" /SILENT '
               f'/SUPPRESSMSGBOXES /CLOSEAPPLICATIONS && start "" "{app_exe}"')
        try:
            subprocess.Popen(["cmd", "/c", cmd], creationflags=0x08000000)  # CREATE_NO_WINDOW
        except OSError:
            webbrowser.open(setup_path if isinstance(setup_path, str) else str(setup_path))
            return
        self._tray_quit = True
        self._on_close()

    def _record_history(self, job: Job, result):
        out = str(job.out_path) if job.out_path else ""
        size = 0
        try:
            if job.out_path and job.out_path.exists():
                size = job.out_path.stat().st_size
        except OSError:
            pass
        self.history.add(history.HistoryEntry(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            src=str(job.src),
            out=out,
            result=result.status.value,
            encoder=result.used_encoder,
            duration=result.duration or job.duration,
            size=size,
            error=result.error,
        ))

    def show_history(self):
        entries = self.history.all()
        win = tk.Toplevel(self.root)
        win.title("Conversion history")
        win.geometry("900x460")

        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)

        cols = ("when", "file", "result", "info", "length", "size")
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        for key, label, width, anchor in (
            ("when", "When", 140, "w"),
            ("file", "File", 250, "w"),
            ("result", "Result", 80, "w"),
            ("info", "Encoder", 90, "w"),
            ("length", "Length", 80, "e"),
            ("size", "Output size", 100, "e"),
        ):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor=anchor)
        tree.tag_configure("Failed", foreground="#b00020")
        tree.tag_configure("Done", foreground="#0a7d29")

        rows: dict[str, history.HistoryEntry] = {}
        for i, e in enumerate(entries):
            iid = str(i)
            rows[iid] = e
            tree.insert("", "end", iid=iid, tags=(e.result,), values=(
                e.timestamp,
                Path(e.src).name if e.src else "",
                e.result,
                e.encoder or "",
                fmt_duration(e.duration),
                fmt_size(e.size) if e.size else "",
            ))
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        if not entries:
            ttk.Label(frame, text="No conversions recorded yet.",
                      foreground="#888").place(relx=0.5, rely=0.5, anchor="center")

        def on_open(_e=None):
            sel = tree.selection()
            if not sel:
                return
            entry = rows.get(sel[0])
            if not entry:
                return
            if entry.result == "Done" and entry.out and Path(entry.out).exists():
                try:
                    os.startfile(entry.out)
                except OSError:
                    open_in_explorer(Path(entry.out))
            elif entry.error:
                self._show_text_dialog(f"Error — {Path(entry.src).name}", entry.error)
        tree.bind("<Double-1>", on_open)

        btns = ttk.Frame(win, padding=(10, 0, 10, 10))
        btns.pack(fill="x")

        def do_clear():
            if messagebox.askyesno("Clear history", "Remove all history entries?"):
                self.history.clear()
                tree.delete(*tree.get_children())
                rows.clear()
        ttk.Button(btns, text="Clear history", command=do_clear).pack(side="left")
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")

    def show_analytics(self):
        entries = self.history.all()
        if not entries:
            messagebox.showinfo("Conversion analytics", "No conversions recorded yet.")
            return
        done = [e for e in entries if e.result == "Done"]
        failed = [e for e in entries if e.result == "Failed"]
        total = len(entries)
        total_out = sum(e.size for e in done)
        total_dur = sum(e.duration for e in done)
        by_fmt = Counter(
            (Path(e.out).suffix.lstrip(".").lower() or "?") for e in done if e.out)
        by_enc = Counter((e.encoder or "?") for e in done)

        lines = [
            f"Total conversions : {total}",
            f"  Succeeded       : {len(done)}",
            f"  Failed          : {len(failed)}",
            f"  Success rate    : {len(done) / total * 100:.0f}%",
            "",
            f"Output produced   : {fmt_size(total_out)}",
            f"Media processed   : {fmt_duration(total_dur)}",
        ]
        peak = max(by_fmt.values(), default=0)
        if by_fmt:
            lines += ["", "By output format:"]
            for fmt, n in by_fmt.most_common():
                bar = "█" * max(1, round(n / peak * 20)) if peak else ""
                lines.append(f"  {fmt:6} {n:4}  {bar}")
        if by_enc:
            lines += ["", "By encoder / method:"]
            for enc, n in by_enc.most_common():
                lines.append(f"  {enc:16} {n}")
        self._show_text_dialog("Conversion analytics", "\n".join(lines), mono=True)

    _THUMB_W, _THUMB_H = 80, 45     # list-row thumbnail box (16:9)

    def _load_thumbs_async(self, jobs, width, on_ready, height=None):
        """Extract thumbnails 4 at a time; on_ready(job, png_or_None) runs on the UI thread."""
        jobs = list(jobs)
        if not jobs:
            return

        def work():
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futs = {pool.submit(thumbnail.extract_thumbnail, j.src, width, height=height): j
                        for j in jobs}
                for fut in concurrent.futures.as_completed(futs):
                    try:
                        png = fut.result()
                    except Exception:
                        png = None
                    self.root.after(0, on_ready, futs[fut], png)
        threading.Thread(target=work, daemon=True).start()

    def _on_thumbs_toggle(self):
        self.settings.set("show_thumbs", bool(self.show_thumbs_var.get()))
        self.settings.save()
        self._apply_thumbs_mode()

    def _apply_thumbs_mode(self):
        if not self.show_thumbs_var.get():
            self.tree.configure(style="Treeview", show="headings")
            return
        style = ttk.Style()
        style.configure("Thumbs.Treeview", rowheight=self._THUMB_H + 8)

        # Rows never have children: drop the expand-arrow slot, which otherwise pushes
        # the image ~20px right, past the #0 column into the File text.
        def strip(layout):
            return [(n, dict(o, children=strip(o["children"])) if "children" in o else o)
                    for n, o in layout if not n.endswith(".indicator")]
        style.layout("Thumbs.Treeview.Item", strip(style.layout("Treeview.Item")))
        self.tree.configure(style="Thumbs.Treeview", show="tree headings")
        self.tree.column("#0", width=self._THUMB_W + 12, minwidth=self._THUMB_W + 12,
                         stretch=False)
        missing = [j for j in self.jobs if str(id(j)) not in self._row_thumbs]
        self._load_thumbs_async(missing, self._THUMB_W, self._set_row_thumb,
                                height=self._THUMB_H)

    def _set_row_thumb(self, job, png):
        iid = str(id(job))
        if not png or self.job_by_iid.get(iid) is not job or not self.tree.exists(iid):
            return
        try:
            img = tk.PhotoImage(file=str(png))
        except tk.TclError:
            return
        self._row_thumbs[iid] = img
        self.tree.item(iid, image=img)

    def show_gallery(self):
        if not self.jobs:
            messagebox.showinfo("Thumbnail gallery", "Add some files to the list first.")
            return
        win = tk.Toplevel(self.root)
        win.title("Thumbnail gallery")
        win.geometry("740x540")
        win._thumb_refs = []

        canvas = tk.Canvas(win, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=8)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        cols = 3
        jobs = list(self.jobs)
        labels = {}
        for i, job in enumerate(jobs):
            cell = ttk.Frame(inner, padding=6)
            cell.grid(row=i // cols, column=i % cols, sticky="n")
            img_lbl = ttk.Label(cell, text="…", width=26, anchor="center")
            img_lbl.pack()
            ttk.Label(cell, text=job.src.name, wraplength=200, anchor="center",
                      justify="center").pack(pady=(4, 0))
            labels[id(job)] = img_lbl

        def place(job, png):
            lbl = labels.get(id(job))
            if lbl is None or not win.winfo_exists():
                return
            if not png:
                lbl.config(text="(no preview)")
                return
            try:
                img = tk.PhotoImage(file=str(png))
                win._thumb_refs.append(img)
                lbl.config(image=img, text="")
            except Exception:
                lbl.config(text="(no preview)")
        self._load_thumbs_async(jobs, 200, place, height=113)   # 16:9 box: even grid rows

    def _row_values(self, job: Job):
        if job.progress_pct >= 1 or job.status in ("Done", "Running"):
            pct = f"{job.progress_pct:.0f}%"
        else:
            pct = ""
        status_text = job.stage or job.status
        if job.status == "Failed" and job.error:
            status_text = f"Failed: {job.error}"
        elif job.status == "Done":
            tail = f" ({job.actually_used})" if job.actually_used and job.actually_used != "remux" else ""
            status_text = "Done" + tail
        elif job.status == "Cancelled":
            status_text = "Cancelled"
        speed_text = f"{job.speed:.1f}x" if job.speed > 0 and job.status == "Running" else ""
        eta_text = fmt_eta(job.eta_seconds) if job.status == "Running" else ""
        return (
            job.src.name,
            fmt_size(job.file_size),
            fmt_duration(job.duration),
            status_text,
            pct,
            speed_text,
            eta_text,
        )

    _STATUS_TAGS = {"Done": "done", "Failed": "failed",
                    "Cancelled": "cancelled", "Running": "running"}

    def _refresh_row(self, job: Job):
        # Called from worker threads on every ffmpeg progress tick. Mark the row
        # dirty and coalesce redraws into one periodic flush so the UI thread
        # isn't flooded (which made window resize janky during conversion).
        iid = str(id(job))
        with self._dirty_lock:
            self._dirty_rows.add(iid)
            if self._flush_scheduled:
                return
            self._flush_scheduled = True
        self.root.after(80, self._flush_rows)

    def _flush_rows(self):
        with self._dirty_lock:
            dirty = self._dirty_rows
            self._dirty_rows = set()
            self._flush_scheduled = False
        for iid in dirty:
            job = self.job_by_iid.get(iid)
            if job is None or not self.tree.exists(iid):
                continue
            tag = self._STATUS_TAGS.get(job.status, "")
            self.tree.item(iid, values=self._row_values(job), tags=(tag,) if tag else ())

    def _set_overall(self, pct):
        self.root.after(0, lambda: self.overall_progress.config(value=pct))

    def _refresh_button_state(self):
        has_jobs = bool(self.jobs)
        self.start_btn.config(state="normal" if has_jobs and not self.is_running else "disabled")
        has_failed = any(j.status == "Failed" for j in self.jobs)
        self.retry_btn.config(state="normal" if has_failed and not self.is_running else "disabled")

    def _on_row_double_click(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        job = self.job_by_iid.get(sel[0])
        if not job:
            return
        if job.status == "Done" and job.out_path:
            try:
                os.startfile(str(job.out_path))
            except OSError:
                open_in_explorer(job.out_path)
        elif job.status == "Failed" and (job.error_full or job.error):
            self._show_text_dialog(f"Error — {job.src.name}", job.error_full or job.error)

    def _on_right_click(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        job = self.job_by_iid.get(row)
        log_state = "normal" if (job and job.log_path and job.log_path.exists()) else "disabled"
        try:
            self.ctx_menu.entryconfigure("Open log", state=log_state)
        except tk.TclError:
            pass
        self.ctx_menu.post(event.x_root, event.y_root)

    def _on_tree_press(self, event):
        if self.is_running:
            self._drag_iid = None
            return
        region = self.tree.identify_region(event.x, event.y)
        if region not in ("cell", "tree"):
            self._drag_iid = None
            return
        self._drag_iid = self.tree.identify_row(event.y)
        self._drag_started = False

    def _on_tree_drag(self, event):
        if not self._drag_iid or self.is_running:
            return
        target = self.tree.identify_row(event.y)
        if not target or target == self._drag_iid:
            return
        if not self._drag_started:
            self._drag_started = True
            self.tree.config(cursor="hand2")
        self.tree.move(self._drag_iid, "", self.tree.index(target))

    def _on_tree_release(self, _event):
        if self._drag_started:
            self.tree.config(cursor="")
            new_order = []
            for iid in self.tree.get_children():
                job = self.job_by_iid.get(iid)
                if job:
                    new_order.append(job)
            self.jobs = new_order
            self._save_queue()
        self._drag_iid = None
        self._drag_started = False

    def open_output_file(self):
        sel = self.tree.selection()
        if not sel:
            return
        job = self.job_by_iid.get(sel[0])
        if job and job.out_path and job.out_path.exists():
            try:
                os.startfile(str(job.out_path))
            except OSError:
                open_in_explorer(job.out_path)

    def open_log_file(self):
        sel = self.tree.selection()
        if not sel:
            return
        job = self.job_by_iid.get(sel[0])
        if not job or not job.log_path or not job.log_path.exists():
            messagebox.showinfo(
                "Open log",
                "No log is available for this file yet. "
                "A log is written after each conversion attempt.",
            )
            return
        try:
            os.startfile(str(job.log_path))
        except OSError:
            open_in_explorer(job.log_path)

    def show_in_folder(self):
        sel = self.tree.selection()
        if not sel:
            return
        job = self.job_by_iid.get(sel[0])
        if not job:
            return
        target = job.out_path if (job.out_path and job.out_path.exists()) else job.src
        open_in_explorer(target)

    def preview_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Preview", "Select a file in the list first.")
            return
        job = self.job_by_iid.get(sel[0])
        if not job:
            return
        win = tk.Toplevel(self.root)
        win.title(f"Preview — {job.src.name}")
        lbl = ttk.Label(win, text="Extracting thumbnail…", padding=20)
        lbl.pack()

        def work():
            png = thumbnail.extract_thumbnail(job.src)
            self.root.after(0, lambda: self._show_preview(win, lbl, png))
        threading.Thread(target=work, daemon=True).start()

    def _show_preview(self, win, lbl, png):
        if not win.winfo_exists():
            return
        if not png:
            lbl.config(text="No preview available (audio-only or unreadable).")
            return
        try:
            img = tk.PhotoImage(file=str(png))     # Tk 8.6 reads PNG natively
        except Exception:
            lbl.config(text="Could not load preview image.")
            return
        win._thumb_ref = img                       # keep a reference alive
        lbl.config(image=img, text="")

    def inspect_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Inspect", "Select a file in the list first.")
            return
        job = self.job_by_iid.get(sel[0])
        if not job:
            return
        from converter import FFMPEG_PATH, CREATE_NO_WINDOW
        proc = subprocess.run(
            [FFMPEG_PATH, "-hide_banner", "-i", str(job.src)],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
        )
        info = (proc.stderr or proc.stdout or "(no output)").strip()

        magic = ""
        try:
            with open(job.src, "rb") as fp:
                head = fp.read(16)
            hex_p = " ".join(f"{b:02x}" for b in head)
            ascii_p = "".join(chr(b) if 32 <= b < 127 else "." for b in head)
            magic = f"\n\n--- First 16 bytes ---\nhex:   {hex_p}\nascii: {ascii_p}\n"
            ext = job.src.suffix.lower()
            if head[:1] == b"\x47":
                magic += "MPEG-TS (0x47 sync byte present).\n"
            elif head[4:8] == b"ftyp":
                magic += f"MP4/QuickTime container — wrong {ext} extension?\n"
            elif head[:4] == b"\x1a\x45\xdf\xa3":
                if ext in (".mkv", ".webm"):
                    magic += "Matroska/WebM container.\n"
                else:
                    magic += f"Matroska/WebM — wrong {ext} extension?\n"
            elif head[:3] == b"FLV":
                magic += f"FLV — wrong {ext} extension?\n"
            else:
                magic += "Unknown signature.\n"
        except OSError as e:
            magic = f"\n\n(could not read file head: {e})\n"

        self._show_text_dialog(f"Inspect — {job.src.name}", info + magic, mono=True)

    def _show_text_dialog(self, title, text, mono=False):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("760x460")
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)
        font = ("Consolas", 9) if mono else "TkTextFont"   # tk.Text defaults to Courier
        widget = tk.Text(frame, wrap="word", font=font)
        widget.insert("1.0", text)
        widget.config(state="disabled")
        sb = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
        widget.configure(yscrollcommand=sb.set)
        widget.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 10))

    def show_whats_new(self, auto=False):
        """Help > What's new. auto=True: only on the first launch of a new version."""
        if auto:
            if self.settings.get("last_seen_version") == APP_VERSION:
                return
            self.settings.set("last_seen_version", APP_VERSION)
            self.settings.save()
        # Frozen builds bundle CHANGELOG.md at the bundle root (see TSConverter.spec).
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        try:
            notes = updater.release_notes(APP_VERSION,
                                          (base / "CHANGELOG.md").read_text(encoding="utf-8"))
        except OSError:
            notes = ""
        if notes or not auto:
            self._show_text_dialog(
                f"What's new in version {APP_VERSION}",
                notes or "No release notes are bundled with this build.\n\nSee "
                         "https://github.com/tanumay-deb/TS-MP4-converter/releases")

    def send_feedback(self):
        webbrowser.open(feedback.form_url(APP_VERSION))

    def _show_about(self):
        hw = detect_hw_encoders()
        hw_text = ", ".join(hw) if hw else "none detected"
        try:
            logs_path = str(get_logs_dir())
        except Exception:
            logs_path = "(unavailable)"
        msg = (
            f"{APP_NAME}\nVersion {APP_VERSION}\n\n"
            f"Python {sys.version.split()[0]}\n"
            f"Drag-and-drop: {'enabled' if _HAS_DND else 'disabled (pip install tkinterdnd2)'}\n"
            f"Modern theme: {'enabled' if _HAS_SVTTK else 'disabled (pip install sv-ttk)'}\n"
            f"Hardware encoders: {hw_text}\n\n"
            f"Config: {Settings.PATH}\n"
            f"Logs:   {logs_path}"
        )
        messagebox.showinfo("About", msg)

    def _queue_path(self) -> Path:
        return get_config_dir() / "queue.json"

    def _save_queue(self):
        pending = [
            {"src": str(j.src), "status": j.status}
            for j in self.jobs if j.status != "Done"
        ]
        path = self._queue_path()
        try:
            if pending:
                with open(path, "w", encoding="utf-8") as fp:
                    json.dump({"version": 1, "files": pending}, fp, indent=2)
            elif path.exists():
                path.unlink()
        except OSError:
            pass

    def _clear_queue_file(self):
        try:
            p = self._queue_path()
            if p.exists():
                p.unlink()
        except OSError:
            pass

    def _load_queue_if_exists(self):
        path = self._queue_path()
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError):
            self._clear_queue_file()
            return
        files = data.get("files", []) if isinstance(data, dict) else []
        valid = [f["src"] for f in files
                 if isinstance(f, dict) and f.get("src") and os.path.isfile(f["src"])]
        if not valid:
            self._clear_queue_file()
            return
        n = len(valid)
        if messagebox.askyesno(
            "Restore previous queue",
            f"Found {n} file(s) from a previous session that didn't finish.\n\n"
            f"Restore them to the queue?",
        ):
            self._add_paths(valid)
        else:
            self._clear_queue_file()

    def _on_tray_change(self):
        self.settings.set("minimize_to_tray", bool(self.tray_var.get()))
        self.settings.save()

    def _hide_to_tray(self):
        if self.tray is None:
            self.tray = tray.Tray(
                APP_NAME,
                on_show=lambda: self.root.after(0, self._show_from_tray),
                on_quit=lambda: self.root.after(0, self._quit_from_tray),
            )
        self.tray.start()
        self._hidden = True
        self.root.withdraw()

    def _show_from_tray(self):
        self._hidden = False
        self.root.deiconify()
        self.root.lift()
        if self.tray:
            self.tray.stop()       # pystray icons don't reliably re-run; recreate next time
            self.tray = None

    def _quit_from_tray(self):
        self._tray_quit = True
        if self.tray:
            self.tray.stop()
            self.tray = None
        self._hidden = False
        self.root.deiconify()      # so any "conversion running" prompt is visible
        self._on_close()

    def _quit_app(self):
        self._tray_quit = True
        self._on_close()

    def _on_close(self):
        # X button hides to tray when enabled (keeps converting in the background).
        if (not self._tray_quit and self.settings.get("minimize_to_tray")
                and tray.available()):
            self._hide_to_tray()
            return
        if self.is_running:
            if not messagebox.askokcancel("Quit",
                                          "A conversion is running. Cancel and quit?"):
                self._tray_quit = False
                return
            self.queue.cancel()
            self.queue.join(timeout=3)
        if self.tray:
            self.tray.stop()
            self.tray = None
        try:
            self.settings.set("geometry", self.root.geometry())
            self.settings.set("col_widths", {c: self.tree.column(c, "width")
                                             for c in self.tree["columns"]})
            self.settings.save()
            self._save_queue()
        except Exception:
            pass
        self.root.destroy()


def run_selftest() -> int:
    """Headless smoke test for CI and the frozen binary.

    Verifies the bundled ffmpeg runs and the junk-header detection works,
    without opening a window. Returns a process exit code.
    """
    import shutil
    import tempfile
    from converter import FFMPEG_PATH, detect_ts_offset, ts_input_opts, CREATE_NO_WINDOW

    def emit(stream, text):
        # In a --windowed PyInstaller build, sys.stdout/stderr are None.
        try:
            if stream is not None:
                stream.write(text)
                stream.flush()
        except Exception:
            pass

    failures = []

    # 1) bundled ffmpeg actually executes
    try:
        proc = subprocess.run(
            [FFMPEG_PATH, "-hide_banner", "-version"],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, timeout=30,
        )
        if proc.returncode != 0 or "ffmpeg version" not in (proc.stdout or "").lower():
            failures.append(f"ffmpeg did not report a version (exit {proc.returncode})")
    except (OSError, subprocess.SubprocessError) as e:
        failures.append(f"ffmpeg failed to run: {e}")

    # 2) junk-header detection finds the real stream offset
    d = Path(tempfile.mkdtemp(prefix="tsconv_selftest_"))
    try:
        junk = b"\x89PNG\r\n\x1a\n" + b"\x00" * 62          # 70-byte fake PNG header
        ts = b"".join(bytes([0x47]) + b"\x00" * 187 for _ in range(5))
        fake = d / "selftest.ts"
        fake.write_bytes(junk + ts)
        clean = d / "clean.ts"
        clean.write_bytes(ts)
        off_fake = detect_ts_offset(fake)
        off_clean = detect_ts_offset(clean)
        if off_fake != 70:
            failures.append(f"detect_ts_offset(fake) != 70 (got {off_fake})")
        if off_clean != 0:
            failures.append(f"detect_ts_offset(clean) != 0 (got {off_clean})")
        if ts_input_opts(fake)[:2] != ["-skip_initial_bytes", "70"]:
            failures.append(f"ts_input_opts(fake) wrong: {ts_input_opts(fake)}")
    except Exception as e:  # noqa: BLE001 - selftest must never crash, only report
        failures.append(f"detection check raised: {e}")
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # 3) ffprobe — bundled in release (frozen) builds; optional in dev
    from tsconverter.media.ffmpeg import FFPROBE_PATH
    if FFPROBE_PATH:
        try:
            p = subprocess.run(
                [FFPROBE_PATH, "-hide_banner", "-version"],
                capture_output=True, text=True,
                creationflags=CREATE_NO_WINDOW, timeout=30,
            )
            if p.returncode != 0 or "ffprobe version" not in (p.stdout or "").lower():
                failures.append(f"ffprobe resolved but gave no version (exit {p.returncode})")
        except (OSError, subprocess.SubprocessError) as e:
            failures.append(f"ffprobe failed to run: {e}")
    elif getattr(sys, "frozen", False):
        failures.append("no ffprobe bundled in the frozen build")
    else:
        emit(sys.stdout, "note: no ffprobe resolved; dev uses ffmpeg fallback\n")

    # 4) optional bundled features (tray, process-suspend)
    from tsconverter import tray
    from tsconverter.media import procctl
    emit(sys.stdout, f"tray={tray.available()} suspend={procctl.available()}\n")
    if getattr(sys, "frozen", False):
        if not procctl.available():
            failures.append("psutil not bundled (process suspend unavailable)")
        if not tray.available():
            failures.append("pystray/Pillow not bundled (tray unavailable)")

    if failures:
        emit(sys.stderr, "SELFTEST FAILED:\n  " + "\n  ".join(failures) + "\n")
        return 1
    emit(sys.stdout, f"SELFTEST OK ({APP_NAME} {APP_VERSION})\n")
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        sys.exit(run_selftest())
    if _HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()