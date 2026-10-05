#!/usr/bin/env python3
"""Windows GUI for managing DashGo downloads and local drive MP4s."""

from __future__ import annotations

import datetime as dt
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from dashcam_history import DownloadHistory
from dashcam_camera_ui import CameraPanel
from dashcam_stitch import Clip, group_drives, output_name, scan_clips

APP_DIR = Path(__file__).resolve().parent
DOWNLOADER = APP_DIR / "dashcam_downloader.py"
STITCHER = APP_DIR / "dashcam_stitch.py"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class DashcamGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("DashGo Desktop")
        self.geometry("1080x840")
        self.minsize(1000, 780)
        self.task_running = False
        self._style()
        self.process: subprocess.Popen[str] | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.drive_rows: dict[str, list[Clip]] = {}
        self.mp4_rows: dict[str, list[Path]] = {}
        self.partial_rows: dict[str, list[Path]] = {}
        self.initial_inventory_logged = False

        self.camera = tk.StringVar()
        self.output = tk.StringVar(value=str(Path(__file__).resolve().parent / "Transfers"))
        self.gap = tk.StringVar(value="5")
        self.skip_newest = tk.StringVar(value="2")
        self.redownload = tk.BooleanVar(value=False)
        self.music_dir = tk.StringVar(value=str(Path(__file__).resolve().parent / "Music"))
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
        self.logs_tab = ttk.Frame(self.tabs, padding=8)
        self.camera_panel = CameraPanel(self.tabs, self)
        self.tabs.add(self.camera_panel, text="Camera")
        self.tabs.add(self.download_tab, text="Download")
        self.tabs.add(self.drives_tab, text="Drives & MP4s")
        self.tabs.add(self.logs_tab, text="Logs")
        self._build_download()
        self._build_drives()
        self._build_logs()

        footer = ttk.Frame(outer)
        footer.pack(side="bottom", fill="x", pady=(8, 0), before=self.tabs)
        self.spinner = ttk.Progressbar(footer, mode="indeterminate", length=130)
        self.spinner.pack(side="left", padx=(0, 10))
        ttk.Label(footer, textvariable=self.status).pack(side="left")
        self.cancel_button = ttk.Button(footer, text="Cancel Current Task", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="right")

    def _build_download(self) -> None:
        tab = self.download_tab
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
        tab.rowconfigure(4, weight=1)
        tab.columnconfigure(0, weight=1)
        controls = ttk.Frame(tab)
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

        music = ttk.Frame(tab)
        music.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        music.columnconfigure(1, weight=1)
        ttk.Label(music, text="Drive music folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(music, textvariable=self.music_dir).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(music, text="Browse…", command=self._browse_music).grid(row=0, column=2)
        ttk.Label(music, text="Crossfade seconds:").grid(row=0, column=3, padx=(16, 4))
        ttk.Entry(music, textvariable=self.crossfade, width=7).grid(row=0, column=4)

        presentation = ttk.LabelFrame(tab, text="Video presentation", padding=8)
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
        ttk.Label(presentation, text="Output target:").grid(row=2, column=0, sticky="w", pady=(7, 0))
        toggle_frame = ttk.Frame(presentation)
        toggle_frame.grid(row=2, column=1, sticky="w", padx=(6, 16), pady=(7, 0))
        ttk.Radiobutton(
            toggle_frame, text="Original (4K)", variable=self.output_mode,
            value="original", command=self._update_output_mode_hint,
        ).pack(side="left")
        ttk.Radiobutton(
            toggle_frame, text="Target < 2 GB", variable=self.output_mode,
            value="2gb", command=self._update_output_mode_hint,
        ).pack(side="left", padx=(10, 0))
        self.output_mode_hint = ttk.Label(
            presentation, text="", font=("Segoe UI", 9, "italic")
        )
        self.output_mode_hint.grid(row=2, column=2, columnspan=2, sticky="w", padx=(6, 0), pady=(7, 0))
        self._update_output_mode_hint()

        ttk.Label(
            tab,
            text="Select one or more timestamp-grouped drives. Source deletion is permanent, but download history is retained.",
        ).grid(row=3, column=0, sticky="w", pady=(0, 6))
        columns = ("start", "end", "clips", "source_size", "mp4", "partial")
        self.drive_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="extended")
        headings = {
            "start": "Drive start", "end": "Drive end", "clips": "Clips",
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
            actions, text="Start / Restart Selected Conversions", command=self._convert
        )
        self.delete_sources_button = ttk.Button(
            actions, text="Delete Selected Source Clips", command=self._delete_sources
        )
        self.delete_mp4_button = ttk.Button(actions, text="Delete Selected MP4s", command=self._delete_mp4s)
        self.delete_partials_button = ttk.Button(
            actions, text="Delete Selected Partials", command=self._delete_partials
        )
        self.convert_button.pack(side="left")
        self.delete_sources_button.pack(side="left", padx=8)
        self.delete_mp4_button.pack(side="left")
        self.delete_partials_button.pack(side="left", padx=8)

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
        mode_label = "Original 4K" if self.output_mode.get() == "original" else "< 2 GB"
        self._start(commands, f"Creating {len(commands)} selected MP4(s) [{mode_label}]")

    def _delete_partials(self) -> None:
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

    def _delete_sources(self) -> None:
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
            self.status.set(f"Ready — {len(drives)} local drive group(s)")
        except (OSError, ValueError) as exc:
            self._append(f"DRIVE INVENTORY ERROR: {exc}\n")

    def _start(self, commands: list[list[str]], label: str) -> None:
        if self.process is not None or self.task_running or self.camera_panel.busy:
            messagebox.showinfo("Task running", "Cancel or wait for the current task first.")
            return
        self.task_running = True
        self.tabs.select(self.logs_tab)
        self._append(f"\n=== {label} ===\n")
        self.status.set(label)
        self._set_task_controls(False)
        self.cancel_button.configure(state="normal")
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
                    self._append(str(value))
                elif kind == "done":
                    success, message = value  # type: ignore[misc]
                    self.task_running = False
                    self.spinner.stop()
                    self.cancel_button.configure(state="disabled")
                    self._set_task_controls(True)
                    self.status.set(str(message))
                    self._append(f"=== {message} ===\n")
                    self._refresh_all()
                    if not success:
                        messagebox.showerror("Dashcam Transfer", f"{message}\n\nDetails are saved in the Logs tab and log file.")
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
                text = self.log_path.read_text(encoding="utf-8", errors="replace")
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
            messagebox.showinfo("Camera check running", "Wait for the current camera check to finish before closing (up to 50 seconds).")
            return
        if self.camera_panel.busy:
            if not messagebox.askyesno("Camera task running", "Stop preview, PC recording and background rendering, then close?"):
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
