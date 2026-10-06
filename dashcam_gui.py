#!/usr/bin/env python3
"""Windows GUI for managing DashGo downloads and local drive MP4s."""

from __future__ import annotations

import datetime as dt
import json
import os
import queue
import dashcam_process as subprocess
import sys
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from dashcam_history import DownloadHistory
from dashcam_paths import APP_DIR, DATA_DIR
from dashcam_power import KeepAwake
from dashcam_recycle import plan_recycle, recycle_plan
from dashcam_camera_ui import CameraPanel
from dashcam_stitch import Clip, group_drives, output_name, scan_clips

DOWNLOADER = APP_DIR / "dashcam_downloader.py"
STITCHER = APP_DIR / "dashcam_stitch.py"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class DashcamGUI(tk.Tk):
    def __init__(self, *, auto_connect=True) -> None:
        super().__init__()
        self.title("DashGo Desktop")
        self.geometry("1080x840")
        self.minsize(1000, 780)
        self.auto_connect = auto_connect and os.environ.get("DASHGO_NO_AUTO_CONNECT") != "1"
        self.task_running = False
        self.task_keeps_awake = False
        self.keep_awake = KeepAwake()
        self._power_error = None
        self._style()
        self.process: subprocess.Popen[str] | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.drive_rows: dict[str, list[Clip]] = {}
        self.mp4_rows: dict[str, list[Path]] = {}
        self.partial_rows: dict[str, list[Path]] = {}
        self.initial_inventory_logged = False

        self.camera = tk.StringVar()
        self.output = tk.StringVar(value=str(DATA_DIR / "Transfers"))
        self.gap = tk.StringVar(value="5")
        self.skip_newest = tk.StringVar(value="2")
        self.redownload = tk.BooleanVar(value=False)
        self.music_dir = tk.StringVar(value=str(DATA_DIR / "Music"))
        self.crossfade = tk.StringVar(value="3")
        self.route_info = tk.StringVar()
        self.channel_title = tk.StringVar(value="My Drive")
        self.end_card = tk.StringVar(value="20")
        self.video_encoder = tk.StringVar(value="auto")
        self.output_mode = tk.StringVar(value="original")
        self.status = tk.StringVar(value="Ready")
        self.history_status = tk.StringVar(value="History not loaded")

        self._build()
        self.after(150, self._initial_refresh)
        self.after(100, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def report_callback_exception(self, exception, value, tb):
        try:
            self._append("UI ERROR: " + "".join(traceback.format_exception(exception, value, tb)))
            self.status.set("An interface action failed. Details are in Tools → Logs.")
        except Exception:
            pass

    def _sync_awake(self):
        panel = self.camera_panel
        reasons = {name for name, job in (('capture', panel.capture),
                   ('render', panel.renderer), ('export', panel.finalizer)) if job and job.active}
        if self.task_running and self.task_keeps_awake:
            reasons.add('studio export')
        try:
            self.keep_awake.update(reasons)
            self._power_error = None
        except OSError as exc:
            if self._power_error != str(exc):
                self._append('POWER: ' + str(exc) + '\n')
            self._power_error = str(exc)
        if self._power_error:
            self.power_status.set('Keep-awake unavailable; check Windows sleep settings')
        else:
            self.power_status.set('Keeping PC awake during media jobs' if self.keep_awake.active else '')

    def destroy(self):
        try:
            if hasattr(self, 'keep_awake'):
                self.keep_awake.close()
        finally:
            super().destroy()

    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        self.configure(background="#f3f5f8")
        style.configure(".", font=("Segoe UI", 10), background="#f3f5f8", foreground="#172236")
        style.configure("TButton", padding=(12, 8), background="#ffffff", borderwidth=1)
        style.map("TButton", background=[("active", "#e4ebf5")])
        style.configure("Accent.TButton", background="#2359b8", foreground="white")
        style.map("Accent.TButton", background=[("active", "#19478f"), ("disabled", "#d8dee8")])
        style.configure("TNotebook", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 10))
        style.map("TNotebook.Tab", background=[("selected", "#ffffff")], padding=[("selected", (18, 10)), ("!selected", (18, 10))])
        style.configure("Transfer.Horizontal.TProgressbar", background="#2359b8", troughcolor="#e3e9f2", borderwidth=0, thickness=20)
        style.configure("TEntry", fieldbackground="#ffffff", padding=6)
        style.configure("Muted.TLabel", foreground="#59677c")
        style.configure("Treeview", rowheight=30, fieldbackground="#ffffff", background="#ffffff")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=8)

    @property
    def source_dir(self) -> Path:
        return Path(os.path.expandvars(os.path.expanduser(self.output.get().strip())))

    @property
    def drives_dir(self) -> Path:
        return self.source_dir / "Drives"

    @property
    def history_path(self) -> Path:
        return self.source_dir / ".dashcam_history.sqlite3"

    @property
    def log_path(self) -> Path:
        return self.source_dir / "dashcam_transfer.log"

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="DashGo Desktop", font=("Segoe UI", 17, "bold")).pack(
            anchor="w", pady=(0, 8)
        )
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        self.download_tab = ttk.Frame(self.tabs, padding=12)
        self.drives_tab = ttk.Frame(self.tabs, padding=12)
        self.logs_window = tk.Toplevel(self)
        self.logs_window.title("Diagnostic logs")
        self.logs_window.geometry("900x600")
        self.logs_window.withdraw()
        self.logs_window.protocol("WM_DELETE_WINDOW", lambda: (self.logs_window.grab_release(), self.logs_window.withdraw()))
        self.logs_tab = ttk.Frame(self.logs_window, padding=8)
        self.logs_tab.pack(fill="both", expand=True)
        self.camera_panel = CameraPanel(self.tabs, self)
        self.tabs.add(self.camera_panel, text="Live")
        self.tabs.add(self.download_tab, text="Transfer")
        self.tabs.add(self.drives_tab, text="Studio")
        menu = tk.Menu(self)
        tools = tk.Menu(menu, tearoff=False)
        tools.add_command(label="Logs…", command=lambda: self._show_window(self.logs_window, modal=True))
        tools.add_command(label="Live settings…", command=self.camera_panel._advanced)
        menu.add_cascade(label="Tools", menu=tools)
        self.configure(menu=menu)
        self._build_download()
        self._build_drives()
        self._build_logs()

        footer = ttk.Frame(outer)
        footer.pack(side="bottom", fill="x", pady=(8, 0), before=self.tabs)
        self.power_status = tk.StringVar()
        ttk.Label(footer, textvariable=self.power_status).pack(side="right", padx=8)
        self.spinner = ttk.Progressbar(footer, mode="indeterminate", length=130)
        self.spinner.pack(side="left", padx=(0, 10))
        ttk.Label(footer, textvariable=self.status).pack(side="left")
        self.cancel_button = ttk.Button(footer, text="Cancel Current Task", command=self._cancel, state="disabled")


    def _show_window(self, window, modal=False):
        window.deiconify()
        window.lift()
        if modal:
            window.transient(self)
            window.grab_set()

    def _build_download(self):
        self.transfer_settings = tk.Toplevel(self)
        self.transfer_settings.title("Transfer settings")
        self.transfer_settings.geometry("920x530")
        self.transfer_settings.withdraw()
        self.transfer_settings.protocol("WM_DELETE_WINDOW", self.transfer_settings.withdraw)
        self._build_transfer_settings()
        bar = ttk.Frame(self.download_tab)
        bar.pack(fill="x", pady=12)
        self.download_button = ttk.Button(bar, text="Transfer stored clips", command=self._download, style="Accent.TButton")
        self.download_button.pack(side="left")
        options = ttk.Menubutton(bar, text="Options")
        options.pack(side="right")
        menu = tk.Menu(options, tearoff=False)
        menu.add_command(label="Transfer settings…", command=lambda: self._show_window(self.transfer_settings))
        menu.add_command(label="Cancel transfer", command=self._cancel)
        menu.add_command(label="Open source folder", command=lambda: self._open(self.source_dir))
        options.configure(menu=menu)
        self.transfer_progress = ttk.Progressbar(self.download_tab, mode="determinate", maximum=100, style="Transfer.Horizontal.TProgressbar")
        self.transfer_progress.pack(fill="x", pady=20)
        self.transfer_detail = tk.StringVar(value="Ready to copy new stored clips from the camera.")
        ttk.Label(self.download_tab, textvariable=self.transfer_detail, wraplength=900).pack(anchor="w")

    def _build_transfer_settings(self) -> None:
        tab = ttk.Frame(self.transfer_settings, padding=16)
        tab.pack(fill="both", expand=True)
        tab.columnconfigure(1, weight=1)
        ttk.Label(tab, text="Camera URL").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(tab, textvariable=self.camera).grid(row=0, column=1, columnspan=2, sticky="ew")
        ttk.Label(tab, text="Leave blank for automatic Wi-Fi gateway discovery.").grid(
            row=1, column=1, columnspan=2, sticky="w", pady=(2, 10)
        )
        ttk.Label(tab, text="Local source folder").grid(row=2, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(tab, textvariable=self.output).grid(row=2, column=1, sticky="ew")
        ttk.Button(tab, text="Browse…", command=self._browse).grid(row=2, column=2, padx=(8, 0))

        opts = ttk.Frame(tab)
        opts.grid(row=3, column=0, columnspan=3, sticky="w", pady=12)
        ttk.Label(opts, text="Skip newest front clips:").pack(side="left")
        ttk.Entry(opts, textvariable=self.skip_newest, width=7).pack(side="left", padx=(6, 20))
        ttk.Checkbutton(
            opts, text="Re-download sources previously deleted locally", variable=self.redownload
        ).pack(side="left")

        info = ttk.LabelFrame(tab, text="Persistent download history", padding=10)
        info.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        ttk.Label(info, textvariable=self.history_status).pack(anchor="w")
        ttk.Label(
            info,
            text="Deleting local TS files does not erase this history. They stay skipped unless the re-download box is checked.",
            wraplength=760,
        ).pack(anchor="w", pady=(4, 0))

        buttons = ttk.Frame(tab)
        buttons.grid(row=5, column=0, columnspan=3, sticky="w")
        self.scan_button = ttk.Button(buttons, text="Scan Camera", command=self._scan)
        self.download_button = ttk.Button(buttons, text="Download New Front Clips", command=self._download)
        self.refresh_button = ttk.Button(buttons, text="Refresh Local Inventory", command=self._refresh_all)
        self.scan_button.pack(side="left")
        self.download_button.pack(side="left", padx=8)
        self.refresh_button.pack(side="left")

        ttk.Separator(tab).grid(row=6, column=0, columnspan=3, sticky="ew", pady=18)
        ttk.Label(
            tab,
            text="MP4 creation is intentionally separate. After downloading, use the Drives & MP4s tab to choose drives.",
            wraplength=800,
        ).grid(row=7, column=0, columnspan=3, sticky="w")

    def _build_drives(self) -> None:
        tab = self.drives_tab
        self.studio_settings = tk.Toplevel(self)
        self.studio_settings.title("Studio settings")
        self.studio_settings.geometry("960x500")
        self.studio_settings.withdraw()
        self.studio_settings.protocol("WM_DELETE_WINDOW", self.studio_settings.withdraw)
        settings = ttk.Frame(self.studio_settings, padding=16)
        settings.pack(fill="both", expand=True)
        quality = ttk.Frame(tab)
        quality.grid(row=0, column=0, sticky="ew", pady=10)
        ttk.Label(quality, text="Output size target").pack(side="left")
        self.output_quality_label = tk.StringVar(value="Source quality")
        ttk.Scale(quality, from_=0, to=4, value=4, length=220, command=self._size_changed).pack(side="left", padx=12)
        ttk.Label(quality, textvariable=self.output_quality_label).pack(side="left")
        options = ttk.Menubutton(quality, text="Options")
        options.pack(side="right")
        menu = tk.Menu(options, tearoff=False)
        options.configure(menu=menu)
        menu.add_command(label="Studio settings…", command=lambda: self._show_window(self.studio_settings))
        menu.add_command(label="Refresh library", command=self._refresh_drives)
        menu.add_command(label="Open selected folder", command=self._open_selected)
        menu.add_separator()
        menu.add_command(label="Delete selected captures...", command=self._delete_captures)
        menu.add_command(label="Delete selected source clips…", command=self._delete_sources)
        menu.add_command(label="Delete selected MP4s…", command=self._delete_mp4s)
        menu.add_command(label="Delete selected partials…", command=self._delete_partials)
        tab.rowconfigure(4, weight=1)
        tab.columnconfigure(0, weight=1)
        controls = ttk.Frame(settings)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(controls, text="New drive after gap (minutes):").pack(side="left")
        ttk.Entry(controls, textvariable=self.gap, width=7).pack(side="left", padx=(6, 12))
        ttk.Button(controls, text="Refresh Drives", command=self._refresh_drives).pack(side="left")
        ttk.Button(controls, text="Open Source Folder", command=lambda: self._open(self.source_dir)).pack(
            side="right"
        )
        ttk.Button(controls, text="Open MP4 Folder", command=lambda: self._open(self.drives_dir)).pack(
            side="right", padx=8
        )

        music = ttk.Frame(settings)
        music.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        music.columnconfigure(1, weight=1)
        ttk.Label(music, text="Drive music folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(music, textvariable=self.music_dir).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(music, text="Browse…", command=self._browse_music).grid(row=0, column=2)
        ttk.Label(music, text="Crossfade seconds:").grid(row=0, column=3, padx=(16, 4))
        ttk.Entry(music, textvariable=self.crossfade, width=7).grid(row=0, column=4)

        presentation = ttk.LabelFrame(settings, text="Video presentation", padding=8)
        presentation.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        presentation.columnconfigure(1, weight=1)
        ttk.Label(presentation, text="Route info (optional):").grid(row=0, column=0, sticky="w")
        ttk.Entry(presentation, textvariable=self.route_info).grid(
            row=0, column=1, sticky="ew", padx=(6, 16)
        )
        ttk.Label(presentation, text="Channel title:").grid(row=0, column=2, sticky="w")
        ttk.Entry(presentation, textvariable=self.channel_title, width=24).grid(
            row=0, column=3, sticky="ew", padx=(6, 0)
        )
        ttk.Label(presentation, text="End card seconds:").grid(row=1, column=0, sticky="w", pady=(7, 0))
        ttk.Entry(presentation, textvariable=self.end_card, width=7).grid(
            row=1, column=1, sticky="w", padx=(6, 16), pady=(7, 0)
        )
        ttk.Label(presentation, text="Video encoder:").grid(row=1, column=2, sticky="w", pady=(7, 0))
        ttk.Combobox(
            presentation, textvariable=self.video_encoder,
            values=("auto", "h264_nvenc", "libx264"), state="readonly", width=21,
        ).grid(row=1, column=3, sticky="w", padx=(6, 0), pady=(7, 0))
        self.output_mode_hint = ttk.Label(presentation, text="Final-render quality is set with the Studio slider.")
        self.output_mode_hint.grid(row=2, column=0, columnspan=4, sticky="w", pady=8)

        ttk.Label(
            tab,
            text="Transferred drives and live captures. Select an item to export or open its folder.",
        ).grid(row=3, column=0, sticky="w", pady=(0, 6))
        columns = ("start", "end", "clips", "source_size", "mp4", "partial")
        self.drive_tree = ttk.Treeview(tab, columns=columns, show="tree headings", selectmode="extended")
        self.drive_tree.column("#0", width=28, stretch=False)
        self.drive_tree.bind("<<TreeviewSelect>>", lambda event: self._size_changed(("1gbh", "2gbh", "4gbh", "8gbh", "original").index(self.output_mode.get()) if self.output_mode.get() in ("1gbh", "2gbh", "4gbh", "8gbh", "original") else 4))
        headings = {
            "start": "Drive / capture / file", "end": "End / state", "clips": "Clips",
            "source_size": "Source size", "mp4": "MP4 status", "partial": "Interrupted partials"
        }
        widths = {
            "start": 155, "end": 155, "clips": 55, "source_size": 95,
            "mp4": 200, "partial": 150
        }
        for column in columns:
            self.drive_tree.heading(column, text=headings[column])
            self.drive_tree.column(column, width=widths[column], anchor="w")
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.drive_tree.yview)
        self.drive_tree.configure(yscrollcommand=scroll.set)
        self.drive_tree.grid(row=4, column=0, sticky="nsew")
        scroll.grid(row=4, column=1, sticky="ns")

        actions = ttk.Frame(tab)
        actions.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        self.convert_button = ttk.Button(
            actions, text="Export selected", command=self._convert
        )
        self.delete_sources_button = ttk.Button(
            actions, text="Delete Selected Source Clips", command=self._delete_sources
        )
        self.delete_mp4_button = ttk.Button(actions, text="Delete Selected MP4s", command=self._delete_mp4s)
        self.delete_partials_button = ttk.Button(
            actions, text="Delete Selected Partials", command=self._delete_partials
        )
        self.convert_button.pack(side="left")
        ttk.Button(actions, text="Open selected folder", command=self._open_selected).pack(side="left", padx=8)

    def _size_changed(self, value):
        mode = ("1gbh", "2gbh", "4gbh", "8gbh", "original")[min(4, max(0, round(float(value))))]
        self.output_mode.set(mode)
        seconds = 0.0
        for key in self.drive_tree.selection() if hasattr(self, "drive_tree") else []:
            folder = getattr(self, "capture_rows", {}).get(key)
            if folder:
                try:
                    seconds += json.loads((folder / "Rendered" / "render.json").read_text()).get("rendered_seconds", 0)
                except (OSError, ValueError):
                    pass
            else:
                clips = self.drive_rows.get(key, [])
                if clips:
                    seconds += (clips[-1].started - clips[0].started).total_seconds() + 60
        text = "Source quality" if mode == "original" else f"≈ {mode[:-3]} GB/hour"
        if seconds and mode != "original":
            text += f" · ≈ {float(mode[:-3]) * seconds / 3600:.2f} GB selected"
        self.output_quality_label.set(text)

    def _open_selected(self):
        for key in self.drive_tree.selection():
            if key in getattr(self, "capture_rows", {}):
                self._open(self.capture_rows[key])
                return
            paths = self.mp4_rows.get(key) or getattr(self, "capture_sources", {}).get(key) or [clip.path for clip in self.drive_rows.get(key, [])]
            if paths:
                self._open(paths[0].parent)
                return

    def _update_output_mode_hint(self) -> None:
        if self.output_mode.get() == "2gb":
            self.output_mode_hint.configure(
                text="Estimates a smaller file; check the final size"
            )
        else:
            self.output_mode_hint.configure(
                text="Source resolution, H.264 CRF 19"
            )

    def _build_logs(self) -> None:
        self.logs_tab.rowconfigure(0, weight=1)
        self.logs_tab.columnconfigure(0, weight=1)
        self.log = tk.Text(self.logs_tab, wrap="word", state="disabled", font=("Consolas", 9))
        scroll = ttk.Scrollbar(self.logs_tab, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        bar = ttk.Frame(self.logs_tab)
        bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="Open Log File", command=lambda: self._open(self.log_path)).pack(side="left")
        ttk.Button(bar, text="Clear Display", command=self._clear_log).pack(side="left", padx=8)

    def _initial_refresh(self) -> None:
        self._load_existing_log()
        self._refresh_all()

    def _settings(self) -> tuple[Path, float, int] | None:
        try:
            gap = float(self.gap.get())
            skip = int(self.skip_newest.get())
            if gap <= 0 or skip < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid settings", "Gap must be positive and skip count non-negative.")
            return None
        source = self.source_dir
        camera = self.camera.get().strip()
        if camera and not camera.startswith(("http://", "https://")):
            messagebox.showerror("Invalid camera URL", "Use a URL such as http://192.168.169.1")
            return None
        return source, gap, skip

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.source_dir)
        if chosen:
            self.output.set(chosen)
            self._refresh_all()

    def _browse_music(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.music_dir.get())
        if chosen:
            self.music_dir.set(chosen)

    def _base_download_command(self, download: bool) -> list[str] | None:
        settings = self._settings()
        if not settings:
            return None
        source, _gap, skip = settings
        command = [
            sys.executable, "-u", "-B", str(DOWNLOADER), "--output", str(source),
            "--history", str(self.history_path), "--skip-newest", str(skip)
        ]
        command.append("--download" if download else "--quiet-list")
        if download and self.redownload.get():
            command.append("--redownload-missing")
        if self.camera.get().strip():
            command.extend(["--camera", self.camera.get().strip()])
        return command

    def _scan(self) -> None:
        command = self._base_download_command(False)
        if command:
            self._start([command], "Scanning camera")

    def _download(self) -> None:
        command = self._base_download_command(True)
        if command:
            self._start([command], "Downloading new front clips")

    def _selected_drives(self) -> list[list[Clip]]:
        return [self.drive_rows[item] for item in self.drive_tree.selection() if item in self.drive_rows]

    def _convert(self) -> None:
        captures = [self.capture_rows[key] for key in self.drive_tree.selection() if key in getattr(self, "capture_rows", {})]
        if captures:
            if len(captures) != 1:
                messagebox.showinfo("Select one capture", "Export one capture at a time.")
                return
            self.camera_panel.finalize_path(captures[0])
            return
        settings = self._settings()
        drives = [drive for drive in self._selected_drives() if drive]
        if not settings or not drives:
            messagebox.showinfo("Select drives", "Select one or more drives first.")
            return
        source, gap, _skip = settings
        music_dir = Path(os.path.expandvars(os.path.expanduser(self.music_dir.get().strip())))
        try:
            crossfade = float(self.crossfade.get())
            end_card = float(self.end_card.get())
            if crossfade <= 0 or end_card <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Invalid presentation timing", "Crossfade and end-card seconds must be positive."
            )
            return
        channel_title = self.channel_title.get().strip()
        if not channel_title:
            messagebox.showerror("Channel title required", "Enter a channel title for the intro and ending.")
            return
        if not music_dir.is_dir():
            messagebox.showerror("Music folder not found", str(music_dir))
            return
        selected_ids = list(self.drive_tree.selection())
        partials = {
            path for item in selected_ids for path in self.partial_rows.get(item, []) if path.exists()
        }
        if partials and not messagebox.askyesno(
            "Restart interrupted conversions?",
            f"Delete {len(partials)} partial MP4 file(s) ({self._human(sum(p.stat().st_size for p in partials))}) "
            "and restart the selected conversion(s)?",
            icon="warning",
        ):
            return
        for path in partials:
            try:
                path.unlink()
                self._append(f"Deleted partial before restart: {path.name}\n")
            except OSError as exc:
                messagebox.showerror("Could not restart", f"Could not delete {path.name}:\n{exc}")
                return
        commands: list[list[str]] = []
        for drive in drives:
            start = drive[0].started.strftime("%Y-%m-%d_%H-%M-%S")
            commands.append([
                sys.executable, "-u", "-B", str(STITCHER), "--source", str(source),
                "--output", str(self.drives_dir), "--gap-minutes", str(gap),
                "--drive-start", start, "--music-dir", str(music_dir),
                "--crossfade-seconds", str(crossfade),
                "--route-info", self.route_info.get().strip(),
                "--channel-title", channel_title, "--end-card-seconds", str(end_card),
                "--video-encoder", self.video_encoder.get(),
                "--target-size", self.output_mode.get(),
                "--overwrite", "--stitch"
            ])
        mode_label = "Source quality" if self.output_mode.get() == "original" else self.output_mode.get()
        self._start(commands, f"Creating {len(commands)} selected MP4(s) [{mode_label}]")

    def _delete_partials(self) -> None:
        if not self._media_edit_allowed():
            return
        paths = {
            path for item in self.drive_tree.selection()
            for path in self.partial_rows.get(item, []) if path.exists()
        }
        if not paths:
            messagebox.showinfo("No partial files", "The selected rows have no interrupted MP4 partials.")
            return
        size = sum(path.stat().st_size for path in paths)
        if not messagebox.askyesno(
            "Permanently delete partial conversions?",
            f"Delete {len(paths)} partial MP4 file(s) ({self._human(size)})?",
            icon="warning",
        ):
            return
        failures = []
        for path in paths:
            try:
                path.unlink()
                self._append(f"Deleted interrupted partial: {path.name}\n")
            except OSError as exc:
                failures.append(f"{path.name}: {exc}")
        if failures:
            self._append("PARTIAL DELETE ERRORS:\n" + "\n".join(failures) + "\n")
            messagebox.showerror("Some partials were not deleted", "See the Logs tab for details.")
        self._refresh_drives()

    def _media_edit_allowed(self):
        if self._media_jobs_active():
            messagebox.showinfo("Media in use", "Finish capture, rendering, export or transfer before changing library files.")
            return False
        return True

    def _media_jobs_active(self):
        panel = self.camera_panel
        return self.task_running or self.process is not None or any(
            job and job.active for job in (panel.capture, panel.renderer, panel.finalizer))

    def _capture_selection(self):
        return any(key in getattr(self, 'capture_rows', {}) or key in getattr(self, 'capture_files', {})
                   for key in self.drive_tree.selection())

    def _delete_captures(self, scope='selected'):
        if not self._media_edit_allowed():
            return
        root = Path(self.camera_panel.destination.get()).absolute()
        paths = []
        try:
            for key in self.drive_tree.selection():
                session = getattr(self, 'capture_rows', {}).get(key)
                media = getattr(self, 'capture_files', {}).get(key)
                if not session and not media:
                    raise ValueError('Select only capture sessions or their expanded files. Transferred drives use the other delete actions.')
                if scope == 'raw':
                    paths.extend(getattr(self, 'capture_sources', {}).get(key, []))
                elif scope == 'mp4':
                    paths.extend(self.mp4_rows.get(key, []))
                else:
                    paths.append(session or media)
            items = plan_recycle(root, paths)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Cannot recycle selection', str(exc))
            return
        if not self._confirm_capture_recycle(root, items):
            self.status.set('Recycling cancelled. No files changed.')
            return
        # Confirmation runs a nested event loop; recheck jobs and path identity.
        try:
            moved, failures = recycle_plan(root, items, is_busy=self._media_jobs_active)
            message = f'Moved {len(moved)} complete selection(s) to Recycle Bin.'
            if failures:
                message += ' Processing stopped. Check the listed item and Recycle Bin; unattempted selections were left in place.\n' + '\n'.join(f'{path.name}: {reason}' for path, reason in failures)
                messagebox.showerror('Recycling incomplete', message)
        except (OSError, ValueError) as exc:
            message = 'Recycling stopped: ' + str(exc)
            messagebox.showerror('Cannot recycle selection', message)
        self._refresh_drives()
        self.drive_tree.selection_remove(*self.drive_tree.selection())
        modes = ('1gbh', '2gbh', '4gbh', '8gbh', 'original')
        self._size_changed(modes.index(self.output_mode.get()) if self.output_mode.get() in modes else 4)
        self.status.set(message)
        self._append('RECYCLE: ' + message + '\n')

    def _confirm_capture_recycle(self, root, items):
        dialog = tk.Toplevel(self)
        dialog.title('Move captures to Recycle Bin?')
        dialog.transient(self)
        dialog.geometry('920x620')
        dialog.minsize(800, 560)
        outer = ttk.Frame(dialog, padding=16)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Move the following selection to Recycle Bin?', font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(outer, text=f'Capture folder: {root}', wraplength=850).pack(anchor='w', pady=(6, 12))
        frame = ttk.Frame(outer); frame.pack(fill='both', expand=True)
        table = ttk.Treeview(frame, columns=('kind', 'path', 'files', 'size'), show='headings', height=6)
        for key, title, width in (('kind', 'Scope', 170), ('path', 'Path within capture folder', 460), ('files', 'Files', 50), ('size', 'Size', 80)):
            table.heading(key, text=title)
            table.column(key, width=width, stretch=key == 'path')
        scroll = ttk.Scrollbar(frame, command=table.yview)
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=table.xview)
        horizontal.pack(side='bottom', fill='x')
        table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        table.column('path', width=max(460, max(len(str(item.path.relative_to(root))) for item in items) * 8), stretch=False)
        scroll.pack(side='right', fill='y'); table.pack(fill='both', expand=True)
        for item in items:
            table.insert('', 'end', values=(item.kind, str(item.path.relative_to(root)), item.file_count, self._human(item.size)))
        ttk.Label(outer, text='Entire sessions include all raw, rendered, final and support files inside that folder.\nIndividual files leave the rest of the session intact. Removing raw or rendered segments can prevent future finalization.\nCamera files and download history are unchanged. If recycling is unavailable, the operation stops.', wraplength=860).pack(anchor='w', pady=12)
        answer = [False]
        def confirm():
            answer[0] = True
            dialog.destroy()
        buttons = ttk.Frame(outer); buttons.pack(fill='x')
        cancel = ttk.Button(buttons, text='Cancel', command=dialog.destroy)
        cancel.pack(side='right')
        ttk.Button(buttons, text='Move to Recycle Bin', command=confirm).pack(side='right', padx=8)
        dialog.bind('<Escape>', lambda event: dialog.destroy())
        dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)
        dialog.grab_set(); cancel.focus_set()
        self.wait_window(dialog)
        return answer[0]

    def _delete_sources(self) -> None:
        if self._capture_selection():
            self._delete_captures(scope='raw')
            return
        if not self._media_edit_allowed():
            return
        drives = [drive for drive in self._selected_drives() if drive]
        if not drives:
            messagebox.showinfo("Select drives", "Select one or more drives first.")
            return
        clips = {clip.path for drive in drives for clip in drive}
        size = sum(path.stat().st_size for path in clips if path.exists())
        if not messagebox.askyesno(
            "Permanently delete source clips?",
            f"Delete {len(clips)} local TS files ({self._human(size)})?\n\n"
            "This does not delete camera files. Persistent history remains, so these clips will not download again unless you enable re-download.",
            icon="warning",
        ):
            return
        failures: list[str] = []
        self.source_dir.mkdir(parents=True, exist_ok=True)
        with DownloadHistory(self.history_path) as history:
            for path in clips:
                try:
                    path.unlink(missing_ok=True)
                    history.mark_present_by_filename(path.name, False)
                except OSError as exc:
                    failures.append(f"{path.name}: {exc}")
        self._append(f"Deleted {len(clips) - len(failures)} local source clips; history retained.\n")
        if failures:
            self._append("DELETE ERRORS:\n" + "\n".join(failures) + "\n")
            messagebox.showerror("Some files were not deleted", "See the Logs tab for details.")
        self._refresh_all()

    def _delete_mp4s(self) -> None:
        if self._capture_selection():
            self._delete_captures(scope='mp4')
            return
        if not self._media_edit_allowed():
            return
        paths = [
            path for item in self.drive_tree.selection()
            for path in self.mp4_rows.get(item, [])
        ]
        if not paths:
            messagebox.showinfo("Select MP4s", "Select one or more rows that have generated MP4s.")
            return
        existing = [path for path in paths if path.exists()]
        if not existing:
            messagebox.showinfo("No MP4s", "The selected drives have no generated MP4 files.")
            return
        size = sum(path.stat().st_size for path in existing)
        names = "\n".join(f"  • {p.name} ({self._human(p.stat().st_size)})" for p in existing[:8])
        if len(existing) > 8:
            names += f"\n  ... and {len(existing) - 8} more"
        if not messagebox.askyesno(
            "Permanently delete MP4s?",
            f"Delete {len(existing)} generated MP4 file(s) ({self._human(size)})?\n\n{names}",
            icon="warning",
        ):
            return
        failures = []
        for path in existing:
            try:
                path.unlink()
            except OSError as exc:
                failures.append(f"{path.name}: {exc}")
        self._append(f"Deleted {len(existing) - len(failures)} generated MP4s.\n")
        if failures:
            self._append("DELETE ERRORS:\n" + "\n".join(failures) + "\n")
        self._refresh_drives()

    def _refresh_all(self) -> None:
        try:
            self.source_dir.mkdir(parents=True, exist_ok=True)
            with DownloadHistory(self.history_path) as history:
                imported = history.import_local_sources(self.source_dir)
                present, missing = history.reconcile(self.source_dir)
                total, _present, _missing = history.stats()
            untracked = len(list(self.source_dir.glob("*_f.ts"))) - present
            self.history_status.set(
                f"Recorded downloads: {total}  |  Sources present: {present}  |  "
                f"Deleted/missing: {missing}  |  Local untracked: {max(untracked, 0)}"
            )
            self._append(
                f"Inventory: history={total}, present={present}, deleted/missing={missing}, "
                f"untracked local={max(untracked, 0)}, newly imported={imported}\n"
            )
            if not self.initial_inventory_logged:
                local_files = sorted(self.source_dir.glob("*_f.ts"))
                self._append(f"Startup local-source inventory ({len(local_files)} files):\n")
                for path in local_files:
                    self._append(f"  LOCAL SOURCE {path.name}  {path.stat().st_size} bytes\n")
                self.initial_inventory_logged = True
        except (OSError, Exception) as exc:
            self.history_status.set(f"History error: {exc}")
            self._append(f"INVENTORY ERROR: {exc}\n")
        self._refresh_drives()

    def _refresh_drives(self) -> None:
        try:
            gap = float(self.gap.get())
            if gap <= 0:
                raise ValueError("gap must be positive")
            drives = group_drives(scan_clips(self.source_dir), dt.timedelta(minutes=gap))
            self.drive_tree.delete(*self.drive_tree.get_children())
            self.drive_rows.clear()
            self.mp4_rows.clear()
            self.partial_rows.clear()
            represented_mp4s: set[Path] = set()
            represented_partials: set[Path] = set()
            all_partials = sorted(self.drives_dir.glob("*.mp4.part*"))
            for index, drive in enumerate(drives):
                key = str(index)
                size = sum(clip.path.stat().st_size for clip in drive)
                mp4_orig = self.drives_dir / output_name(drive, "original")
                mp4_2gb = self.drives_dir / output_name(drive, "2gb")
                existing_mp4s: list[Path] = []
                status_parts: list[str] = []
                if mp4_orig.exists():
                    existing_mp4s.append(mp4_orig)
                    represented_mp4s.add(mp4_orig.resolve())
                    status_parts.append(f"4K ({self._human(mp4_orig.stat().st_size)})")
                if mp4_2gb.exists():
                    existing_mp4s.append(mp4_2gb)
                    represented_mp4s.add(mp4_2gb.resolve())
                    status_parts.append(f"2GB ({self._human(mp4_2gb.stat().st_size)})")
                status = ", ".join(status_parts) if status_parts else "Not generated"

                drive_prefix = "Drive_" + drive[0].started.strftime("%Y-%m-%d_%H-%M-%S")
                partials = [path for path in all_partials if path.name.startswith(drive_prefix)]
                partial_status = (
                    f"{len(partials)} ({self._human(sum(p.stat().st_size for p in partials))})"
                    if partials else "None"
                )
                self.drive_tree.insert(
                    "", "end", iid=key,
                    values=(
                        drive[0].started.strftime("%Y-%m-%d %H:%M:%S"),
                        drive[-1].started.strftime("%Y-%m-%d %H:%M:%S"),
                        len(drive), self._human(size), status, partial_status,
                    ),
                )
                self.drive_rows[key] = drive
                if partials:
                    self.partial_rows[key] = partials
                    represented_partials.update(path.resolve() for path in partials)
                if existing_mp4s:
                    self.mp4_rows[key] = existing_mp4s
            for mp4 in sorted(self.drives_dir.glob("Drive_*.mp4")):
                if mp4.resolve() in represented_mp4s:
                    continue
                key = f"mp4-{len(self.mp4_rows)}-{mp4.name}"
                stamp = mp4.stem.removeprefix("Drive_").replace("_", " ")
                tag = " [2GB]" if mp4.stem.endswith("_2GB") else ""
                self.drive_tree.insert(
                    "", "end", iid=key,
                    values=(stamp, "Sources deleted", 0, "0.0 B", f"Ready{tag} ({self._human(mp4.stat().st_size)})", "None"),
                )
                self.drive_rows[key] = []
                self.mp4_rows[key] = [mp4]
            for partial in all_partials:
                if partial.resolve() in represented_partials:
                    continue
                key = f"partial-{partial.name}"
                stamp = partial.name.removeprefix("Drive_").split(".mp4.part", 1)[0].replace("_", " ")
                self.drive_tree.insert(
                    "", "end", iid=key,
                    values=(stamp, "Sources not matched", 0, "0.0 B", "No completed MP4", f"1 ({self._human(partial.stat().st_size)})"),
                )
                self.drive_rows[key] = []
                self.partial_rows[key] = [partial]
            self.capture_rows = {}
            self.capture_sources = {}
            self.capture_files = {}
            root = Path(self.camera_panel.destination.get())
            for folder in sorted(root.glob("Capture_*")):
                if not folder.is_dir():
                    continue
                key = "capture-" + folder.name
                raw = sorted(folder.glob("part_*.mkv"))
                rendered = sorted(folder.glob("Rendered/part_*.mp4"))
                final = sorted(folder.glob("Finalized_*/Capture.mp4"))
                try:
                    record = json.loads((folder / "session.json").read_text())
                    state = record.get("state", "Unknown")
                except (OSError, ValueError):
                    state = "Status unavailable"
                self.drive_tree.insert("", "end", iid=key, values=(folder.name.removeprefix("Capture_"), state,
                    len(raw), self._human(sum(p.stat().st_size for p in raw)),
                    f"{len(rendered)} rendered / {len(final)} final MP4s", ""))
                self.capture_rows[key] = folder
                self.mp4_rows[key] = rendered + final
                self.drive_rows[key] = []
                self.capture_sources[key] = raw
                for index, path in enumerate([*raw, *rendered, *final]):
                    child = f"{key}-file-{index}"
                    self.capture_files[child] = path
                    kind = "Raw capture" if path.suffix == ".mkv" else "Final MP4" if path in final else "Rendered segment"
                    self.drive_tree.insert(key, "end", iid=child, values=(path.name, kind, 1, self._human(path.stat().st_size), "", ""))
                    self.drive_rows[child] = []
                    if path.suffix == ".mkv":
                        self.capture_sources[child] = [path]
                    else:
                        self.mp4_rows[child] = [path]
            if not self.task_running:
                self.status.set(f"{len(drives)} transferred drive(s) · {len(self.capture_rows)} live capture(s)")
        except (OSError, ValueError) as exc:
            self._append(f"DRIVE INVENTORY ERROR: {exc}\n")

    def _start(self, commands: list[list[str]], label: str) -> None:
        if self.camera_panel.preview is not None:
            self.camera_panel._stop_preview()
        if self.process is not None or self.task_running or self.camera_panel.busy:
            messagebox.showinfo("Task running", "Cancel or wait for the current task first.")
            return
        self.task_running = True
        self.task_keeps_awake = any(str(STITCHER) in command for command in commands)
        self._sync_awake()
        self._append(f"\n=== {label} ===\n")
        self.status.set(label)
        self._set_task_controls(False)
        self.cancel_button.configure(state="normal")
        self.cancel_button.pack(side="right")
        self.transfer_detail.set(label)
        self.spinner.start(12)
        threading.Thread(target=self._worker, args=(commands,), daemon=True).start()

    def _worker(self, commands: list[list[str]]) -> None:
        try:
            for command in commands:
                self.events.put(("log", "COMMAND: " + subprocess.list2cmdline(command) + "\n"))
                self.process = subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    creationflags=CREATE_NO_WINDOW,
                )
                assert self.process.stdout is not None
                for line in iter(self.process.stdout.readline, ""):
                    self.events.put(("log", line.replace("\r", "\n")))
                code = self.process.wait()
                self.process = None
                if code:
                    self.events.put(("done", (False, f"Task failed with exit code {code}")))
                    return
            self.events.put(("done", (True, "Task finished successfully")))
        except Exception as exc:
            self.process = None
            self.events.put(("log", f"UNEXPECTED GUI WORKER ERROR: {exc!r}\n"))
            self.events.put(("done", (False, f"Unexpected error: {exc}")))

    def _cancel(self) -> None:
        if self.process is not None:
            self.process.terminate()
            self.status.set("Cancelling… partial download is retained")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    line = str(value)
                    if line.startswith("PROGRESS "):
                        try:
                            progress = json.loads(line[9:])
                            self.transfer_progress['value'] = progress['percent']
                            eta = progress.get('eta_seconds')
                            remaining = f"{int(eta)//60}m {int(eta)%60:02}s left" if eta is not None else "Estimating time remaining"
                            self.transfer_detail.set(f"{progress['percent']:.1f}% · {self._human(progress['done'])} / {self._human(progress['total'])} · {remaining}")
                        except (ValueError, KeyError):
                            pass
                    else:
                        self._append(line)
                elif kind == "done":
                    success, message = value  # type: ignore[misc]
                    self.task_running = False
                    self.task_keeps_awake = False
                    self._sync_awake()
                    self.spinner.stop()
                    self.cancel_button.configure(state="disabled")
                    self.cancel_button.pack_forget()
                    self._set_task_controls(True)
                    self.status.set(str(message))
                    self._append(f"=== {message} ===\n")
                    self._refresh_all()
                    self.transfer_detail.set(str(message))
                    if self.auto_connect:
                        self.camera_panel._preview()
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _set_task_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (
            self.scan_button, self.download_button, self.refresh_button,
            self.convert_button, self.delete_sources_button, self.delete_mp4_button,
            self.delete_partials_button,
        ):
            button.configure(state=state)

    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        if int(self.log.index("end-1c").split(".")[0]) > 2000:
            self.log.delete("1.0", "1000.0")
        self.log.see("end")
        self.log.configure(state="disabled")
        try:
            self.source_dir.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as output:
                output.write(text)
        except OSError:
            pass

    def _load_existing_log(self) -> None:
        try:
            if self.log_path.exists():
                with self.log_path.open("rb") as source:
                    source.seek(max(0, self.log_path.stat().st_size - 100_000))
                    text = source.read().decode("utf-8", errors="replace")
                self.log.configure(state="normal")
                self.log.insert("end", text[-100_000:])
                self.log.see("end")
                self.log.configure(state="disabled")
        except OSError as exc:
            self._append(f"Could not load prior log: {exc}\n")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _open(self, path: Path) -> None:
        try:
            if path.suffix and not path.exists():
                messagebox.showinfo("Not found", f"File does not exist yet:\n{path}")
                return
            if not path.suffix:
                path.mkdir(parents=True, exist_ok=True)
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Could not open", str(exc))

    @staticmethod
    def _human(value: int) -> str:
        amount = float(value)
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if amount < 1024 or unit == "TiB":
                return f"{amount:.1f} {unit}"
            amount /= 1024
        return str(value)

    def _close(self) -> None:
        if self.camera_panel.operation:
            self.camera_panel._cancel_connect()
            self.status.set("Closing after the current connection request finishes…")
            self.after(150, self._close)
            return
        if self.camera_panel.preview is not None and not any(job and job.active for job in (self.camera_panel.capture, self.camera_panel.renderer, self.camera_panel.finalizer)):
            self.camera_panel._stop_preview()
        if self.camera_panel.busy:
            if not messagebox.askyesno("Camera task running", "Stop preview, PC recording, rendering and finalization, then close?"):
                return
            try:
                self.camera_panel.shutdown()
            except TimeoutError:
                messagebox.showinfo("Recording", "Recording is still stopping. Try closing again shortly.")
                return
        if self.process is not None and not messagebox.askyesno(
            "Task running", "Cancel the current task and close?"
        ):
            return
        if self.process is not None:
            self.process.terminate()
        self.destroy()


if __name__ == "__main__":
    DashcamGUI().mainloop()
