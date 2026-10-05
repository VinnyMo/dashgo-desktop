# DashGo Desktop

Windows desktop prototype for downloading NEXPOW VSQ10 dashcam recordings, organizing drives, and developing direct-to-PC live capture. Python/Tkinter UI with FFmpeg media processing. Independent project, not affiliated with NEXPOW or DashGo.

**Prototype:** SD transfer was verified on one VSQ10. Live capture infrastructure passes synthetic-media tests, and an eight-second front-camera live sample was saved and decoded. Control writes and long-duration capture are not yet validated. No installer or release package is available.

## Compatibility and current support

| Feature | Status |
| --- | --- |
| NEXPOW VSQ10, firmware `NEXPOW-VSQ10-20250418`, hardware `H30D-LMT-V1.1-20230810` | Device tested; other firmware/models unverified |
| Camera identification, media URL and settings inventory | Read-only API verified on this firmware |
| Front-camera SD file listing/download | Verified in the existing workflow; persistent local history |
| Drive grouping and MP4 rendering | Existing workflow retained; requires local music files |
| Embedded live preview | Implemented for a measurable HTTP/HTTPS/RTSP stream; synthetic media tested |
| Direct PC recording | Implemented as segmented Matroska stream copy; synthetic media tested |
| VSQ10 front live video | Measured 1280×720 H.264 at 25 FPS; approximately 3.15 Mbit/s in one eight-second sample |
| Camera audio | Intentionally excluded from PC recording; mic-off firmware advertises malformed AAC |
| Stream activation | Explicit `/app/enterrecorder` verified on the listed firmware; SD recording remained on |
| Sustained multi-hour recording | Not yet validated |
| Camera setting changes, SD start/stop, front/rear switching | Not enabled; read-only settings shown |
| Full iOS feature parity | Planned, not claimed |

The original SD front recordings were verified as 3840×2160 H.264 with AAC audio. **Live video was separately measured at 1280×720, H.264, 25 FPS.** The eight-second sample was 3,147,018 bytes (about 3.15 Mbit/s including container overhead), and all 201 frames decoded. This sample does not prove sustained bitrate or selectable qualities; 4K live capture is not supported by this evidence. The app measures the supplied stream and displays dimensions, codec, frame rate, audio and an approximate sampled bitrate.

## Windows setup

1. Install Python 3.10 or newer with Tkinter and add Python to PATH. Development checks used Python 3.14 on Windows. No pip packages are required.
2. Install a complete [FFmpeg build](https://ffmpeg.org/download.html), including `ffmpeg.exe` and `ffprobe.exe`, and add its `bin` folder to PATH. The app also detects Gyan's WinGet FFmpeg installation. Development checks used FFmpeg 9.0. Installation is a manual user action; the app does not install tools.
3. Clone or download this repository into a writable local folder.
4. Run:

   ```powershell
   python -B dashcam_gui.py
   ```

   Or double-click `Launch Dashcam Transfer.cmd`. If `python` opens the Microsoft Store, install Python or correct your Windows app execution aliases/PATH.

Connect Windows to the dashcam's Wi-Fi yourself. This project does not change Wi-Fi, routes, firewall rules or camera credentials. If another connection supplies Internet access, preserve that setup. Avoid camera traffic during important uploads.

## Camera and live capture

The **Camera** tab makes no automatic network connection. Enter the camera's HTTP base address and choose **Read device info**. It reads device information, the advertised live URL, and reported settings. Device settings remain read-only. No camera reset, format, erase, reboot or deletion actions are implemented.

The VSQ10 advertises an RTSP root URL and separately reports TCP/port 5000. The separate port is not the observed RTSP port: live video worked on the URL's default port 554 after explicit activation. The app preserves the reported URL without rewriting its port. Choose **Enable live stream** to send the verified app-connect notification on the exact supported firmware; it asks before activation. Nothing is activated at launch. No exit/cleanup camera command is guessed; stopping closes the owned client.

When a valid stream is available:

1. Choose **Measure stream**. This reads a five-second media sample, with bounded process timeouts. If RTSP advertises broken audio metadata, a second video-only sample is copied into a temporary local folder and probed there (up to two 20-second network stages plus a 10-second local stage). The temporary sample is removed after inspection. Bitrate is an approximate sum of packet sizes divided by sample timestamp span; FPS is the stream-reported rate. Unknown values stay unknown.
2. Choose **Start preview** for embedded, muted playback. The display is scaled to 640×360 at 10 FPS; this is only display scaling, not the source/capture quality. Choose **Stop preview** to disconnect.
3. Choose a **Recording folder**, then **Record to PC**. Preview stops first to avoid competing camera stream clients. Recording requires a successful measurement of that same URL.
4. Choose **Stop recording** to flush and close the current segment. Closing the app during a camera task asks before stopping it.

Each recording creates a unique `Capture_<time>_<random>` subfolder, `part_000000.mkv` segments, and a `session.json` status/measurement record. It does not overwrite existing recordings or write into the transfer/drive inventory. Video is copied without re-encoding. Camera audio and proprietary data tracks are deliberately omitted. The microphone setting is never changed; background music belongs in the later render stage. This captures the live feed delivered to the PC, not SD files. Whether this camera can sustain streaming with no SD card has not been tested.

There is no application session-duration cap. Available storage, camera power, PC sleep, Wi-Fi stability and device limits still apply. At the observed rate, budget roughly 1.4 GB per hour for video, allowing extra headroom. Segments target five minutes, split at source keyframes. Earlier completed segments should remain usable after an interruption; the final segment can be incomplete after power loss or forced termination. Keep the originals when attempting recovery. New sessions never append to an interrupted one.

Recording stops on process failure, a 30-second lack of output growth, or less than 512 MiB free. A graceful stop is attempted before terminating only the process owned by this session. Polling/free-space reserves reduce risk but cannot guarantee against sudden storage failures. A session left marked `recording` after a crash is an interrupted session, not proof that a process is still running. Automatic reconnect and multi-hour soak testing remain planned.

Capture folders are separate from the legacy MP4 editor. Combining live segments into a drive MP4 is not implemented yet. A compatible media player can open the `.mkv` files directly.

## SD download and drive workflow

- **Download:** leave Camera URL blank to discover camera gateways, or enter a specific URL. **Scan Camera** inventories only; **Download New Front Clips** copies front-camera files. The two newest files are skipped by default because they may still be recording.
- Transfers use `.part` files and check HTTP content length before renaming. Existing mismatched files are retained unless explicitly replaced in the CLI. VSQ10 Range responses are unreliable; interrupted transfers may restart from byte zero.
- SQLite history remembers completed downloads even after local source deletion. Re-download of deleted sources requires the explicit checkbox.
- **Drives & MP4s:** timestamp-grouped front clips can be rendered with a music playlist, route text, opening/ending title and audio visualization. Add your own permitted music to `Music/`. Camera audio is omitted by this legacy rendering workflow. Each render shuffles the available playlist once and loops that order if needed.
- Original-resolution and target-size MP4 profiles can coexist. The target under 2 GB is a bitrate estimate, **not a hard guarantee**; inspect the final size. Very long drives can exceed the budget.
- Creating/updating selected MP4s intentionally replaces the matching derived MP4 after a successful render. Local source, MP4 and partial deletion controls require confirmation. These legacy local operations never delete camera files. Do not convert or delete media while another program is using/uploading it.
- **Logs:** transfer/conversion output persists in `Transfers/dashcam_transfer.log`.

CLI examples:

```powershell
python -B dashcam_downloader.py --help
python -B dashcam_downloader.py --camera http://192.168.169.1
python -B dashcam_downloader.py --download --output D:\Dashcam\Transfers
python -B dashcam_stitch.py --source D:\Dashcam\Transfers
python -B dashcam_stitch.py --source D:\Dashcam\Transfers --output D:\Dashcam\Drives --stitch
```

`dashcam_transfer.ps1` runs download followed by MP4 generation. `config.example.json` is a field reference only; configuration persistence is not yet implemented.

## Protocol evidence

Direct, read-only observations on the VSQ10 (2026-10-05):

- `/app/getdeviceattr`: firmware/hardware identification, two cameras.
- `/app/getmediainfo`: RTSP root URL, `transport=tcp`, separate `port=5000`.
- `/app/capability`: opaque bit string; meanings not assumed.
- `/app/getparamitems?param=all` and `/app/getparamvalue?param=all`: settings/options and current indexes. Reported SD-resolution choices include 1080p+1080p through 4K+2K. These are not live-quality selections.
- Earlier verified: `/app/getsdinfo`, `/app/getfilelist?folder=loop&start=0&end=99`, and HTTP download of returned `/mnt/card/video_front/..._f.ts` paths. File-list sizes are approximate whole KiB; HTTP content length is authoritative.

The official [DashGo iOS listing](https://apps.apple.com/us/app/dashgo/id1303402312) describes live preview/control. A [firsthand investigation of a different Yantop device](https://randhana.com/blog/reverse-engineering-my-dashcams-hidden-rtsp-stream) reports stream activation with `/app/enterrecorder` and RTSP/TCP on port 554. This lead was followed by direct VSQ10 validation of activation and front RTSP capture. Other controls from that investigation have not been verified here. Do not copy mutating commands to other hardware without checking their effects and recording state.

## Tests and development

```powershell
python -B -m unittest discover -s tests -v
$env:DASHGO_MEDIA_TESTS = '1'
python -B -m unittest discover -s tests -v
```

The default suite exercises URL safeguards, read-only capability detection, measurement parsing, unique recording directories, graceful stop, simulated disk exhaustion/disconnect, history retention and inventory isolation. The opt-in FFmpeg integration test generates a small synthetic H.264/AAC fixture, serves it on localhost, probes it, records multiple segments, stops and decodes the result. It never connects to the physical camera or reads user media. Temporary test files are removed after the test. Windows sandbox restrictions on Python 3.14 temporary directories can require running tests in a normal terminal.

An eight-second live front sample saved and decoded successfully while read-only status still reported SD recording on. A later integrated segmented camera test and OSD/SD-control validation were not completed; those checks remain gated. No hours-long recording test has passed. The rear camera on the test unit was reported faulty and was not selected or validated. Do not treat synthetic tests as device certification.

Architecture:

| Module | Responsibility |
| --- | --- |
| `dashcam_gui.py` | Desktop shell, transfer/drive controls, job events and local inventory |
| `dashcam_camera_ui.py` | Explicit camera actions, embedded preview, recording state |
| `dashcam_live.py` | Read-only capabilities, FFprobe measurements, owned FFmpeg capture lifecycle |
| `dashcam_downloader.py` | Gateway discovery, file index, safe HTTP downloads |
| `dashcam_history.py` | Persistent SQLite download history |
| `dashcam_stitch.py` | Grouping, music playlist and derived MP4 rendering |

## Troubleshooting

- **Camera not found:** check Wi-Fi and the base URL; avoid changing Windows network settings just to force discovery.
- **Device information works but live probe fails:** the stream server may require a device-specific activation handshake. No activation is guessed automatically. Confirm firmware, reported URL and vendor-app behavior first.
- **No audio:** it may be absent/disabled at the camera. The app reports what the sample contains and does not enable the microphone.
- **Recording stops:** inspect `session.json` for a connection, stall or space reason. Retain all segments; resolve the cause and begin a new session.
- **FFmpeg missing:** check `ffmpeg -version` and `ffprobe -version` from the same terminal used to start the GUI.
- **MP4 conversion fails:** confirm readable music exists and sufficient disk space is available. CPU encoding is the default; NVIDIA encoding requires compatible hardware/drivers.
- **Files are not re-downloaded:** completed history is intentional. Use the re-download option only when desired.

## Privacy and safety

The repository contains source and synthetic test definitions only. `.gitignore` excludes footage, music, capture sessions, logs, SQLite databases, local config, packet captures and build outputs. Gitignore is not a substitute for reviewing files before publishing.

Camera HTTP is generally unencrypted on its local Wi-Fi. Do not expose camera ports to the Internet. Runtime transfer logs can contain local paths and device identifiers; do not publish them without sanitizing. Live-session manifests omit the source URL and credentials. The live UI rejects embedded URL credentials, but query strings can still be sensitive: use only trusted URLs and avoid sharing process listings. The application has no telemetry and does not upload footage.

## Roadmap

- Expand activation/reconnection testing; determine safe exit semantics without guessing an exit command.
- Extend front stream measurements across longer sessions and other firmware; validate rear support on working hardware.
- Verify safe camera controls and read-back before enabling writes.
- Test long recording sessions, network interruptions, storage exhaustion, sleep and recovery.
- Add an optional background renderer for completed raw segments with the existing overlay and lo-fi music workflow, scaled to 720p without upscaling. Benchmark CPU/GPU throughput, preserve playlist continuity and keep raw capture independent of rendering failures.
- Add recording library/segment export and richer preview/capture integration. Real-time polished output is not implemented yet.
- Improve accessibility, smaller-screen layouts and configuration persistence.
- Package a Windows app/installer later, with dependency/license review, signing and reproducible builds. No current packaging/release promise.

## License

[MIT](LICENSE), copyright 2026 Vincent Mossman. FFmpeg is installed separately and has its own build-specific licensing terms; it is not bundled here.
