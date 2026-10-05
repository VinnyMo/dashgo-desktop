"""Camera workspace. No network activity until the user chooses an action."""
from __future__ import annotations

import queue
import math
import subprocess
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from dashcam_live import (CaptureSession, CREATE_NO_WINDOW, describe_probe, enable_live_stream, input_options,
                          inspect_stream, media_tool, read_capabilities, validate_stream)
from dashcam_render import BackgroundRenderer


class CameraPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=20)
        self.app = app
        self.events = queue.Queue()
        self.frames = queue.Queue(maxsize=1)
        self.operation = False
        self.preview = None
        self.capture = None
        self.renderer = None
        self.render_enabled = tk.BooleanVar(value=False)
        self.report = None
        self.report_url = None
        self.stream = tk.StringVar()
        self.destination = tk.StringVar(value=str(Path(__file__).resolve().parent / "Captures"))
        self.device = tk.StringVar(value="Not connected")
        self.details = tk.StringVar(value="Stream details have not been measured.")
        self.state = tk.StringVar(value="Ready")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Camera address").grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Entry(top, textvariable=app.camera).grid(row=0, column=1, sticky="ew")
        self.identify = ttk.Button(top, text="Read device info", command=self._identify)
        self.identify.grid(row=0, column=2, padx=(12, 0))
        self.enable = ttk.Button(top, text="Enable live stream", command=self._enable)
        self.enable.grid(row=1, column=2, padx=(12, 0), pady=(6, 12))
        ttk.Label(top, textvariable=self.device).grid(row=1, column=1, sticky="w", pady=(6, 12))
        ttk.Label(top, text="Live stream URL").grid(row=2, column=0, sticky="w", padx=(0, 12))
        self.stream_entry = ttk.Entry(top, textvariable=self.stream)
        self.stream_entry.grid(row=2, column=1, sticky="ew")
        self.measure = ttk.Button(top, text="Measure stream", command=self._measure)
        self.measure.grid(row=2, column=2, padx=(12, 0))
        ttk.Label(top, text="Read device info to get its reported URL. Measure stream to verify it.",
                  style="Muted.TLabel").grid(row=3, column=1, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(self, textvariable=self.details, wraplength=880).grid(row=1, column=0, sticky="ew", pady=12)
        self.canvas = tk.Canvas(self, background="#101827", highlightthickness=0, height=245)
        self.canvas.grid(row=2, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda event: self._placeholder())
        self.image = None
        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, sticky="ew", pady=12)
        self.play = ttk.Button(actions, text="Start preview", command=self._preview)
        self.play.pack(side="left")
        self.stop_preview = ttk.Button(actions, text="Stop preview", command=self._stop_preview, state="disabled")
        self.stop_preview.pack(side="left", padx=8)
        self.record = ttk.Button(actions, text="Record to PC", command=self._record, style="Accent.TButton")
        self.record.pack(side="right")
        self.stop_record = ttk.Button(actions, text="Stop recording", command=self._stop_record, state="disabled")
        self.stop_record.pack(side="right", padx=8)
        output = ttk.Frame(self)
        output.grid(row=4, column=0, sticky="ew")
        output.columnconfigure(1, weight=1)
        ttk.Label(output, text="Recording folder").grid(row=0, column=0, padx=(0, 12))
        self.folder_entry = ttk.Entry(output, textvariable=self.destination)
        self.folder_entry.grid(row=0, column=1, sticky="ew")
        self.browse = ttk.Button(output, text="Browse", command=self._browse)
        self.browse.grid(row=0, column=2, padx=(12, 0))
        self.render_option = ttk.Checkbutton(output, text="Add music and overlays in background (uses Drives & MP4s settings)", variable=self.render_enabled)
        self.render_option.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.stop_render = ttk.Button(output, text="Stop rendering", command=self._stop_render, state="disabled")
        self.stop_render.grid(row=1, column=2, padx=(12, 0), pady=(8, 0))
        ttk.Label(self, textvariable=self.state, wraplength=880).grid(row=5, column=0, sticky="ew", pady=(12, 6))
        ttk.Label(self, text="PC recording uses separate five-minute segments. Preview stops before recording.",
                  style="Muted.TLabel").grid(row=6, column=0, sticky="w")
        controls = ttk.LabelFrame(self, text="Camera controls", padding=10)
        controls.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        header = ttk.Frame(controls)
        header.pack(fill="x")
        ttk.Label(header, text="Device settings are read-only; writes are not yet verified.").pack(side="left")
        self.show_settings = False
        self.toggle_settings = ttk.Button(header, text="Show settings", command=self._toggle_settings)
        self.toggle_settings.pack(side="right")
        self.settings = ttk.Treeview(controls, columns=("setting", "current", "options"), show="headings", height=3)
        for key, label, width in (("setting", "Setting", 170), ("current", "Current", 150), ("options", "Device-reported options", 480)):
            self.settings.heading(key, text=label)
            self.settings.column(key, width=width)
        self.after(100, self._poll)

    def _toggle_settings(self):
        self.show_settings = not self.show_settings
        if self.show_settings:
            self.settings.pack(fill="x", pady=(6, 0))
        else:
            self.settings.pack_forget()
        self.toggle_settings.configure(text="Hide settings" if self.show_settings else "Show settings")

    def _placeholder(self):
        if self.image is None:
            self.canvas.delete("all")
            self.canvas.create_text(self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2,
                                    text="Live preview\nMeasure a verified stream to begin", fill="#94a3b8",
                                    font=("Segoe UI", 14), justify="center")

    @property
    def busy(self):
        return self.operation or self.preview is not None or (self.capture and self.capture.active) or (self.renderer and self.renderer.active)

    def _available(self):
        if self.app.process is not None or getattr(self.app, "task_running", False) or self.busy:
            messagebox.showinfo("Task running", "Stop or finish the current task first.")
            return False
        return True

    def _run(self, label, function, kind):
        self.operation = True
        self.state.set(label)
        self._controls()
        def work():
            try:
                self.events.put((kind, function()))
            except Exception as exc:
                # Do not expose credentials or query tokens through subprocess errors.
                self.events.put(("error", "The operation failed. Check the camera address, stream URL and FFmpeg installation."))
        threading.Thread(target=work, daemon=True).start()

    def _identify(self):
        if not self._available():
            return
        address = self.app.camera.get().strip()
        if not address:
            messagebox.showinfo("Camera address", "Enter the camera HTTP address. Use Download for automatic discovery.")
            return
        self._run("Reading device information…", lambda: read_capabilities(address), "device")

    def _measure(self):
        if not self._available():
            return
        try:
            url = validate_stream(self.stream.get())
        except ValueError as exc:
            messagebox.showerror("Live stream", str(exc))
            return
        self.report = self.report_url = None
        self._run("Measuring a short stream sample…", lambda: (url, inspect_stream(url)), "probe")

    def _enable(self):
        if not self._available():
            return
        if not messagebox.askyesno("Enable camera live stream", "Send the verified VSQ10 app-connect command?\n\nThis opens the camera live server. SD recording stayed on in the tested firmware. Stop important transfers first."):
            return
        address = self.app.camera.get().strip()
        self._run("Enabling camera live stream…", lambda: enable_live_stream(address), "device")

    def _verified(self):
        if self.report is None or self.stream.get().strip() != self.report_url:
            messagebox.showinfo("Measure stream", "Measure this stream before previewing or recording.")
            return False
        return True

    def _preview(self):
        if not self._available() or not self._verified():
            return
        try:
            command = [media_tool("ffmpeg"), "-hide_banner", "-loglevel", "error",
                       *input_options(self.report_url), "-i", self.report_url, "-an",
                       "-vf", "fps=10,scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2",
                       "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
            self.preview = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
            process = self.preview
            self.state.set("Previewing · display scaled to 640 × 360 · audio muted")
            self._controls()
            def read_frames():
                try:
                    while True:
                        data = bytearray()
                        while len(data) < 640 * 360 * 3:
                            chunk = process.stdout.read(640 * 360 * 3 - len(data))
                            if not chunk:
                                return
                            data.extend(chunk)
                        if self.frames.empty():
                            self.frames.put(b"P6\n640 360\n255\n" + data)
                finally:
                    process.stdout.close()
                    self.events.put(("preview_done", process))
            threading.Thread(target=read_frames, daemon=True).start()
        except Exception:
            self.state.set("Preview could not start. Check FFmpeg and the stream URL.")

    def _stop_preview(self):
        process, self.preview = self.preview, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self.image = None
        self._placeholder()
        self.state.set("Preview stopped")
        self._controls()

    def _record(self):
        if self.preview is not None:
            self._stop_preview()
        if not self._available() or not self._verified():
            return
        try:
            render_settings = None
            if self.render_enabled.get():
                music = Path(self.app.music_dir.get())
                fade = float(self.app.crossfade.get())
                if not music.is_dir() or fade <= 0:
                    raise ValueError("Choose a music folder and positive crossfade in Drives & MP4s first.")
                render_settings = (music, self.app.channel_title.get(), self.app.route_info.get(), fade)
            session = CaptureSession(self.report_url, Path(self.destination.get()), self.report)
            session.start()
            self.capture = session
            if render_settings:
                try:
                    self.renderer = BackgroundRenderer(session, *render_settings)
                    self.renderer.start()
                except Exception:
                    messagebox.showerror("Background rendering", "Rendering could not start. Raw PC recording continues.")
            self._controls()
        except Exception as exc:
            messagebox.showerror("Recording", str(exc))

    def _stop_record(self):
        if self.capture:
            self.capture.stop()
            self.state.set("Stopping recording and closing the current segment…")
            self.stop_record.configure(state="disabled")

    def _stop_render(self):
        if self.renderer:
            self.renderer.stop()
            self.stop_render.configure(state="disabled")

    def _browse(self):
        selected = filedialog.askdirectory(initialdir=self.destination.get())
        if selected:
            self.destination.set(selected)

    def _controls(self):
        busy = bool(self.busy)
        for button in (self.identify, self.enable, self.measure, self.play, self.record, self.browse):
            button.configure(state="disabled" if busy else "normal")
        if self.preview is not None:
            self.record.configure(state="normal")
        self.stop_preview.configure(state="normal" if self.preview is not None else "disabled")
        self.stop_record.configure(state="normal" if self.capture and self.capture.active else "disabled")
        self.stop_render.configure(state="normal" if self.renderer and self.renderer.active else "disabled")
        self.render_option.configure(state="disabled" if busy else "normal")
        for entry in (self.stream_entry, self.folder_entry):
            entry.configure(state="disabled" if busy else "normal")

    def _poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "preview_done":
                    if self.preview is value:
                        self._stop_preview()
                        self.state.set("Preview ended. Check the connection before restarting.")
                    continue
                self.operation = False
                if kind == "device":
                    self.device.set(f"{value['firmware']} · {value['cameras']} camera(s)")
                    media = value.get("media") or {}
                    if isinstance(media, dict) and media.get("rtsp"):
                        try:
                            self.stream.set(validate_stream(media["rtsp"]))
                            self.report = self.report_url = None
                        except ValueError:
                            pass
                    self.settings.delete(*self.settings.get_children())
                    current = {item.get("name"): item.get("value") for item in value.get("values", []) if isinstance(item, dict)}
                    for item in value.get("items", []):
                        if not isinstance(item, dict):
                            continue
                        choices = dict(zip(item.get("index", []), item.get("items", [])))
                        name = item.get("name", "unknown")
                        # Only non-sensitive, observed settings are displayed.
                        if name not in {"switchcam", "mic", "osd", "rec_resolution", "rec_split_duration", "key_tone", "speaker", "gsr_sensitivity", "rec", "light_fre", "screen_standby"}:
                            continue
                        self.settings.insert("", "end", values=(name, choices.get(current.get(name), "Unknown"), ", ".join(map(str, choices.values()))))
                    self.state.set("Device information read. Reported stream URL is not yet tested; settings remain read-only.")
                elif kind == "probe":
                    self.report_url, self.report = value
                    self.details.set(describe_probe(self.report))
                    self.state.set("Stream measured. Preview and PC recording are available.")
                elif kind == "error":
                    self.state.set(value)
                self._controls()
        except queue.Empty:
            pass
        try:
            frame = self.frames.get_nowait()
            if self.preview is not None:
                self.image = tk.PhotoImage(data=frame, format="PPM")
                factor = max(1, math.ceil(640 / max(self.canvas.winfo_width(), 1)), math.ceil(360 / max(self.canvas.winfo_height(), 1)))
                if factor > 1:
                    self.image = self.image.subsample(factor)
                self.canvas.delete("all")
                self.canvas.create_image(self.canvas.winfo_width()/2, self.canvas.winfo_height()/2, image=self.image)
        except queue.Empty:
            pass
        if self.capture:
            if self.capture.active:
                elapsed = int(time.monotonic() - self.capture.started)
                self.state.set(f"Recording to PC · {elapsed // 60:02}:{elapsed % 60:02} · {self.capture.byte_count / 1048576:.1f} MiB\n{self.capture.directory}")
            else:
                self.state.set((self.capture.reason or "Recording stopped. Segments saved.") + f"\n{self.capture.directory}")
                self.capture = None
                self._controls()
        if self.renderer:
            if self.renderer.active:
                if not (self.capture and self.capture.active):
                    self.state.set(f"Background rendering: {self.renderer.state} · {self.renderer.completed} segment(s) ready")
            else:
                result = self.renderer.reason or f"Background rendering {self.renderer.state}: {self.renderer.completed} segment(s) ready."
                if self.capture and self.capture.active:
                    result += " Raw PC recording continues."
                self.state.set(result)
                self.renderer = None
                self._controls()
        self.after(100, self._poll)

    def shutdown(self):
        self._stop_preview()
        if self.capture and self.capture.active:
            self.capture.stop()
        if self.renderer and self.renderer.active:
            self.renderer.stop()
        if self.capture:
            self.capture.wait()
        if self.renderer:
            self.renderer.wait()
