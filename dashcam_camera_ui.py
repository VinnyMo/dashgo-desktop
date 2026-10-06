"""Camera workspace. No network activity until the user chooses an action."""
from __future__ import annotations

import queue
import math
import dashcam_process as subprocess
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from dashcam_live import (CaptureSession, ProbeError, CREATE_NO_WINDOW, describe_probe, input_options,
                          inspect_stream, media_tool, read_capabilities, validate_stream)
from dashcam_render import BackgroundRenderer
from dashcam_finalize import CaptureFinalizer
from dashcam_paths import DATA_DIR
from dashcam_preview import resize_ppm
from dashcam_connect import CameraConnection, ConnectionCancelled


class CameraPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=20)
        self.app = app
        self.events = queue.Queue()
        self.frames = queue.Queue(maxsize=1)
        self.connection = None
        self.candidates = []
        self.operation = False
        self.notice = ""
        self.preview = None
        self.capture = None
        self.renderer = None
        self.finalizer = None
        self.render_enabled = tk.BooleanVar(value=False)
        self.report = None
        self.report_url = None
        self.stream = tk.StringVar()
        self.destination = tk.StringVar(value=str(DATA_DIR / "Captures"))
        self.device = tk.StringVar(value="Not connected")
        self.details = tk.StringVar(value="Stream details have not been measured.")
        self.state = tk.StringVar(value="Ready")
        self.quality = tk.IntVar(value=720)
        self.quality_label = tk.StringVar(value="720p · source quality")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(bar, textvariable=self.device).pack(side="left")
        self.connect_button = ttk.Button(bar, text="Attempt to reconnect", command=self._connect)
        self.connect_button.pack(side="right")
        self.cancel_connect = ttk.Button(bar, text="Cancel connection", command=self._cancel_connect)
        self.menu_button = ttk.Menubutton(bar, text="Options")
        self.menu_button.pack(side="right", padx=8)
        menu = tk.Menu(self.menu_button, tearoff=False)
        self.menu_button.configure(menu=menu)
        menu.add_command(label="Connection and storage…", command=self._advanced)
        menu.add_command(label="Cancel connection", command=self._cancel_connect)
        menu.add_command(label="Finalize saved capture…", command=self._finalize)
        menu.add_command(label="Cancel finalization", command=self._cancel_finalize)
        menu.add_command(label="Stop background rendering", command=self._stop_render)
        viewport = ttk.Frame(self)
        viewport.grid(row=1, column=0, sticky="nsew")
        self.canvas = tk.Canvas(viewport, background="#101827", borderwidth=0, highlightthickness=0, height=400)
        viewport.bind("<Configure>", self._fit_preview)
        self.canvas.place(relx=.5, rely=.5, anchor="center", width=640, height=360)
        self.canvas.bind("<Configure>", lambda event: self._placeholder())
        self.image = None
        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="ew", pady=12)
        self.record = ttk.Button(actions, text="Start Capture", command=self._toggle_capture, style="Accent.TButton")
        self.record.pack(side="left")
        ttk.Label(actions, text="Capture quality").pack(side="left", padx=(24, 8))
        self.quality_slider = ttk.Scale(actions, from_=0, to=2, value=2, command=self._quality_changed, length=140)
        self.quality_slider.pack(side="left")
        ttk.Label(actions, textvariable=self.quality_label).pack(side="left", padx=8)
        self.render_option = ttk.Checkbutton(actions, text="Render overlay + music (Studio quality)", variable=self.render_enabled)
        self.render_option.pack(side="right")
        ttk.Label(self, textvariable=self.state, wraplength=900).grid(row=3, column=0, sticky="ew")
        # Rarely used controls live in a settings window opened from the menu.
        self.advanced = tk.Toplevel(self)
        self.advanced.title("Live settings")
        self.advanced.geometry("850x520")
        self.advanced.withdraw()
        self.advanced.protocol("WM_DELETE_WINDOW", self.advanced.withdraw)
        top = ttk.Frame(self.advanced, padding=18)
        top.pack(fill="both", expand=True)
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Camera address").grid(row=0, column=0, sticky="w")
        self.address_entry = ttk.Entry(top, textvariable=app.camera)
        self.address_entry.grid(row=0, column=1, sticky="ew")
        self.identify = ttk.Button(top, text="Read device info", command=self._identify)
        self.identify.grid(row=0, column=2)
        self.enable = ttk.Button(top, text="Connect this address", command=lambda: self._connect(manual=True))
        self.enable.grid(row=1, column=2)
        self.candidate_picker = ttk.Combobox(top, state="readonly")
        ttk.Label(top, text="Live stream URL").grid(row=2, column=0, sticky="w")
        self.stream_entry = ttk.Entry(top, textvariable=self.stream)
        self.stream_entry.grid(row=2, column=1, sticky="ew")
        self.measure = ttk.Button(top, text="Measure stream", command=self._measure)
        self.measure.grid(row=2, column=2)
        ttk.Label(top, textvariable=self.details, wraplength=750).grid(row=3, column=0, columnspan=3, sticky="w", pady=12)
        ttk.Label(top, text="Capture folder").grid(row=4, column=0, sticky="w")
        self.folder_entry = ttk.Entry(top, textvariable=self.destination)
        self.folder_entry.grid(row=4, column=1, sticky="ew")
        self.browse = ttk.Button(top, text="Browse", command=self._browse)
        self.browse.grid(row=4, column=2)
        ttk.Label(top, text="Lower quality is encoded on this PC. Camera resolution and microphone stay unchanged.", wraplength=740).grid(row=5, column=0, columnspan=3, sticky="w", pady=12)
        self.settings = ttk.Treeview(top, columns=("setting", "current", "options"), show="headings", height=5)
        for key in ("setting", "current", "options"):
            self.settings.heading(key, text=key.title())
            self.settings.column(key, width=210)
        self.settings.grid(row=6, column=0, columnspan=3, sticky="ew")
        # Internal action handles retained for shared state management.
        self.play = ttk.Button(top, command=self._preview)
        self.stop_preview = ttk.Button(top, command=self._stop_preview)
        self.stop_record = ttk.Button(top, command=self._stop_record)
        self.stop_render = ttk.Button(top, command=self._stop_render)
        self.finalize_button = ttk.Button(top, command=self._finalize)
        self.cancel_finalize_button = ttk.Button(top, command=self._cancel_finalize)
        self._controls()
        self.after(100, self._poll)
        if getattr(app, "auto_connect", False):
            self.after(750, self._connect)

    def _fit_preview(self, event):
        # Fit 16:9 without a surrounding frame, stretch or crop.
        from fractions import Fraction
        ratio = min(1, event.width / 1280, event.height / 720)
        factor = max(Fraction(n, d) for d in (1, 2, 4, 5, 8) for n in range(1, d + 1) if Fraction(n, d) <= max(.125, ratio))
        self.canvas.place_configure(width=1280 * factor.numerator // factor.denominator,
                                    height=720 * factor.numerator // factor.denominator)

    def _quality_changed(self, value):
        quality = (360, 480, 720)[min(2, max(0, round(float(value))))]
        self.quality.set(quality)
        self.quality_label.set(f"{quality}p" + (" · source quality" if quality == 720 else " · smaller file"))

    def _toggle_capture(self):
        if self.capture and self.capture.active:
            self._stop_record()
        else:
            self._record()

    def _advanced(self):
        self.advanced.deiconify()
        self.advanced.lift()

    def _connect(self, manual=False):
        if self.preview is not None:
            self._stop_preview()
        if not self._available():
            return
        base = None
        if manual:
            base = self.app.camera.get().strip()
            if not base:
                messagebox.showinfo("Camera address", "Enter the camera HTTP address first.")
                return
        elif self.candidates:
            selected = self.candidate_picker.current()
            if selected < 0:
                self.state.set("Choose a camera, then click Connect camera.")
                return
            base = self.candidates[selected]["address"]
        self.report = self.report_url = None
        self.details.set("Stream details have not been measured.")
        self.device.set("Connecting")
        self.operation = True
        self.connection = job = CameraConnection(lambda message: self.events.put(("progress", message)))
        self._controls()
        def work():
            try:
                self.events.put(("connected", job.run(base)))
            except ConnectionCancelled:
                self.events.put(("connection_error", "Connection cancelled. Any completed live activation remains in effect; recording and microphone settings were not changed."))
            except (ValueError, RuntimeError) as exc:
                self.events.put(("connection_error", str(exc)))
            except Exception:
                self.events.put(("connection_error", "Connection failed. Check camera Wi-Fi and FFmpeg, then retry."))
        threading.Thread(target=work, daemon=True).start()

    def _cancel_connect(self):
        if self.connection:
            self.connection.cancel()
            self.state.set("Cancelling connection; waiting for the current request to finish.")
            self.cancel_connect.configure(state="disabled")

    def _placeholder(self):
        if self.image is None:
            self.canvas.delete("all")
            self.canvas.create_text(self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2,
                                    text="Live preview\nWaiting for camera", fill="#94a3b8",
                                    font=("Segoe UI", 14), justify="center")

    @property
    def busy(self):
        return self.operation or self.preview is not None or (self.capture and self.capture.active) or (self.renderer and self.renderer.active) or (self.finalizer and self.finalizer.active)

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
            except ProbeError as exc:
                self.events.put(("error", str(exc)))
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

    def _verified(self):
        if self.report is None or self.stream.get().strip() != self.report_url:
            messagebox.showinfo("Measure stream", "Measure this stream before previewing or recording.")
            return False
        return True

    def _preview(self):
        if self.operation or (self.capture and self.capture.active) or self.app.process is not None or getattr(self.app, "task_running", False) or not self.report:
            return
        try:
            command = [media_tool("ffmpeg"), "-hide_banner", "-loglevel", "error",
                       *input_options(self.report_url), "-i", self.report_url, "-an",
                       "-vf", "fps=10,scale=1280:720:force_original_aspect_ratio=decrease:flags=lanczos,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
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
                        while len(data) < 1280 * 720 * 3:
                            chunk = process.stdout.read(1280 * 720 * 3 - len(data))
                            if not chunk:
                                return
                            data.extend(chunk)
                        if self.frames.empty():
                            self.frames.put(b"P6\n1280 720\n255\n" + data)
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
            self.notice = ""
            render_settings = None
            if self.render_enabled.get():
                music = Path(self.app.music_dir.get())
                fade = float(self.app.crossfade.get())
                if not music.is_dir() or fade <= 0:
                    raise ValueError("Choose a music folder and positive crossfade in Drives & MP4s first.")
                render_settings = (music, self.app.channel_title.get(), self.app.route_info.get(), fade)
            session = CaptureSession(self.report_url, Path(self.destination.get()), self.report, quality=self.quality.get(), preview=True, reconnect_attempts=3)
            session.start()
            self.capture = session
            if render_settings:
                try:
                    self.renderer = BackgroundRenderer(session, *render_settings, target_size=self.app.output_mode.get())
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

    def _finalize(self):
        if self.capture and self.capture.active or self.renderer and self.renderer.active or self.finalizer and self.finalizer.active:
            self.state.set("Finish capture, rendering or export first.")
            return
        selected = filedialog.askdirectory(title="Choose a completed capture folder to assemble", initialdir=self.destination.get())
        if not selected:
            return
        self.finalize_path(Path(selected))

    def finalize_path(self, selected):
        if self.capture and self.capture.active or self.finalizer and self.finalizer.active:
            self.state.set("Stop capture and wait for the current export first.")
            return
        self.finalizer = CaptureFinalizer(Path(selected), recover=True,
            raw_only=not (Path(selected) / "Rendered" / "render.json").exists(),
            target_size=self.app.output_mode.get() if hasattr(self.app, "output_mode") else "original")
        self.finalizer.start()
        self.state.set("Checking completed capture segments…")
        self._controls()

    def _cancel_finalize(self):
        if self.finalizer:
            self.finalizer.stop()
            self.cancel_finalize_button.configure(state="disabled")

    def _browse(self):
        selected = filedialog.askdirectory(initialdir=self.destination.get())
        if selected:
            self.destination.set(selected)

    def _controls(self):
        if hasattr(self.app, 'keep_awake') and hasattr(self.app, 'power_status'):
            self.app._sync_awake()
        busy = bool(self.busy)
        for button in (self.identify, self.enable, self.measure, self.play, self.record, self.browse, self.finalize_button, self.connect_button):
            button.configure(state="disabled" if busy else "normal")
        if not self.report or self.stream.get().strip() != self.report_url:
            self.play.configure(state="disabled")
            self.record.configure(state="disabled")
        self.cancel_connect.configure(state="normal" if self.connection and not self.connection.cancelled.is_set() else "disabled")
        self.candidate_picker.configure(state="disabled" if busy else "readonly")
        if self.preview is not None and not (self.renderer and self.renderer.active) and not (self.finalizer and self.finalizer.active):
            self.record.configure(state="normal")
        self.stop_preview.configure(state="normal" if self.preview is not None else "disabled")
        self.stop_record.configure(state="normal" if self.capture and self.capture.active else "disabled")
        self.stop_render.configure(state="normal" if self.renderer and self.renderer.active else "disabled")
        self.cancel_finalize_button.configure(state="normal" if self.finalizer and self.finalizer.active else "disabled")
        capturing = bool(self.capture and self.capture.active)
        self.record.configure(text="Stop Capture" if capturing else "Start Capture")
        if capturing:
            self.record.configure(state="normal")
        self.quality_slider.configure(state="disabled" if capturing else "normal")
        self.render_option.configure(state="disabled" if capturing else "normal")
        if self.preview is not None:
            self.connect_button.configure(state="normal")
        for entry in (self.stream_entry, self.folder_entry, self.address_entry):
            entry.configure(state="disabled" if busy else "normal")

    def _poll(self):
        try:
            self._poll_once()
        finally:
            if hasattr(self.app, '_sync_awake'):
                self.app._sync_awake()
            self.after(100, self._poll)

    def _poll_once(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "preview_done":
                    if self.preview is value:
                        self._stop_preview()
                        self.device.set("Camera disconnected")
                        self.report = self.report_url = None
                        self.state.set("No live video. Check camera Wi-Fi and choose Attempt to reconnect.")
                        self._controls()
                    continue
                if kind == "progress":
                    if not self.connection or not self.connection.cancelled.is_set():
                        self.state.set(value)
                    continue
                self.operation = False
                if kind == "connected" and self.connection and self.connection.cancelled.is_set():
                    kind, value = "connection_error", "Connection cancelled. Any completed live activation remains in effect; recording and microphone settings were not changed."
                if kind in {"connected", "connection_error"}:
                    self.connection = None
                if kind == "connection_error":
                    self.device.set("Not connected")
                    self.state.set(value)
                if kind == "connected":
                    if "candidates" in value:
                        self.candidates = value["candidates"]
                        self.candidate_picker.configure(values=[f"{c['firmware']} — {c['address']}" for c in self.candidates])
                        self.candidate_picker.set("")
                        self.candidate_picker.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
                        self._advanced()
                        self.device.set("Choose a camera")
                        self.state.set("Multiple cameras found. Select one, then click Connect camera.")
                        self._controls()
                        continue
                    self.candidates = []
                    self.candidate_picker.grid_remove()
                    self.app.camera.set(value["address"])
                    self.events.put(("probe", (value["url"], value["report"])))
                    self.stream.set(value["url"])
                    value = value["capabilities"]
                    kind = "device"
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
                    self.state.set("Connected. Preview is live; capture is off.")
                    if getattr(self.app, "auto_connect", False):
                        self._preview()
                elif kind == "error":
                    self.state.set(value)
                self._controls()
        except queue.Empty:
            pass
        try:
            source_frames = self.capture.frames if self.capture and self.capture.active else self.frames
            frame = source_frames.get_nowait()
            if self.preview is not None or (self.capture and self.capture.active):
                width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
                resized = resize_ppm(frame, max(16, width - width % 16), max(9, (width - width % 16) * 9 // 16))
                self.image = tk.PhotoImage(master=self.canvas, data=resized, format="PPM")
                self.canvas.delete("all")
                self.canvas.create_image(self.canvas.winfo_width()/2, self.canvas.winfo_height()/2, image=self.image)
        except queue.Empty:
            pass
        except (OSError, ValueError, tk.TclError):
            self.state.set("Preview frame could not be displayed; capture continues independently.")
        if self.capture:
            if self.capture.active:
                elapsed = int(time.monotonic() - self.capture.started)
                self.state.set(f"Recording to PC · {elapsed // 60:02}:{elapsed % 60:02} · {self.capture.byte_count / 1048576:.1f} MiB\n{self.capture.directory}")
            else:
                if self.capture.state != "stopped":
                    self.notice = self.capture.reason or "Capture interrupted. Saved segments are retained."
                    if hasattr(self.app, "_append"):
                        self.app._append("CAPTURE: " + self.notice + "\n")
                self.state.set((self.capture.reason or "Recording stopped. Segments saved.") + f"\n{self.capture.directory}")
                self.capture = None
                self._controls()
                if getattr(self.app, "auto_connect", False):
                    self._preview()
        if self.renderer:
            if self.renderer.active:
                if not (self.capture and self.capture.active):
                    self.state.set(f"Background rendering: {self.renderer.state} · {self.renderer.completed} segment(s) ready")
            else:
                result = self.renderer.reason or f"Background rendering {self.renderer.state}: {self.renderer.completed} segment(s) ready."
                if self.capture and self.capture.active:
                    result += " Raw PC recording continues."
                if self.renderer.state == "failed":
                    self.notice = result
                    if hasattr(self.app, "_append"):
                        self.app._append("RENDER: " + result + "\n")
                self.state.set(result)
                self.renderer = None
                self._controls()
        if self.finalizer:
            if self.finalizer.active:
                self.state.set(f"Finalizing capture: {self.finalizer.state}. Source files are retained.")
            else:
                if self.finalizer.state == "finished":
                    self.state.set(f"MP4 ready: {self.finalizer.output}")
                else:
                    self.state.set(self.finalizer.reason or "Finalization cancelled. Source files are retained.")
                if hasattr(self.app, "status"):
                    self.app.status.set(self.state.get())
                self.finalizer = None
                self._controls()
                if hasattr(self.app, "_refresh_drives"):
                    self.app._refresh_drives()
                    self.app.status.set(self.state.get())

        if self.capture and self.capture.state == "reconnecting":
            self.state.set(self.capture.reason)
        if self.notice and self.notice not in self.state.get():
            self.state.set(self.state.get() + "\n" + self.notice)

    def shutdown(self):
        if getattr(self, "connection", None):
            self.connection.cancel()
        self._stop_preview()
        if self.capture and self.capture.active:
            self.capture.stop()
        if self.renderer and self.renderer.active:
            self.renderer.stop()
        if self.finalizer and self.finalizer.active:
            self.finalizer.stop()
        if self.capture:
            self.capture.wait()
        if self.renderer:
            self.renderer.wait()
        if self.finalizer:
            self.finalizer.wait()
