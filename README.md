# DashGo Desktop

Windows desktop prototype for NEXPOW VSQ10 live preview, direct-to-PC capture, stored-clip transfers and video exports. Python/Tkinter with FFmpeg. Independent project, not affiliated with NEXPOW or DashGo.

**Prototype:** two separate 18-minute camera capture/render/export runs passed. Continuous hour-long, eight-hour and moving-drive reliability remain unverified. Camera settings are read-only. There is no installer, packaged release or full iOS feature parity.

## Compatibility

| Feature | Evidence and limits |
| --- | --- |
| Device | NEXPOW VSQ10, firmware `NEXPOW-VSQ10-20250418`; other firmware/models unverified |
| Front live stream | Measured 1280x720 H.264, 25 FPS, approximately 3.15–3.43 Mbit/s in short samples |
| Stored front recordings | 3840x2160 H.264/AAC verified separately; this does not imply 4K live video |
| Preview and PC capture | Shared FFmpeg input during capture; five-minute Matroska segments |
| Capture resolution | PC-side 360p / 480p / 720p limit; not a selectable camera-stream quality |
| Camera audio | Excluded from PC capture; microphone-off firmware advertises malformed AAC |
| Music and overlays | Optional background rendering of closed segments; manual final MP4 assembly |
| Stored-clip transfer | Front-file listing, download, history and existing-copy preservation verified |
| Camera controls | Read-only information/settings; verified live-server activation only |
| Rear camera | Not tested; test unit's rear camera was reported faulty |

Bitrate varies with scene and conditions. The app measures dimensions, codec, frame rate, audio availability and sampled bitrate rather than assuming SD-recording resolutions apply to live video.

## Windows setup

1. Install Python 3.10 or newer with Tkinter. Development checks used Python 3.14. No pip packages are required.
2. Install a complete [FFmpeg build](https://ffmpeg.org/download.html), including `ffmpeg.exe` and `ffprobe.exe`, and add its `bin` directory to PATH. The app also detects Gyan's WinGet installation. Tests used FFmpeg 9.0; it is not installed or bundled by this app.
3. Clone/download this source into a writable folder. Open **Launch DashGo.vbs** for the console-free GUI, or run `python -B dashcam_gui.py`. The older CMD launcher can briefly show a command window.
4. Connect Windows to the camera Wi-Fi yourself. The app does not change network interfaces, routes, firewall rules or credentials. Preserve any separate Internet connection and avoid camera traffic during important uploads.

The VBS launcher uses `%LOCALAPPDATA%\Python\bin\pythonw.exe` when present, otherwise `pythonw.exe` on PATH. If Python opens the Microsoft Store, correct the installation/PATH or Windows app execution aliases.

## Live, Transfer and Studio

### Live

Startup attempts to discover the camera, verify the supported firmware, activate its live server and measure its advertised stream. Preview opens automatically; recording never starts automatically. If no camera is available, use **Attempt to reconnect**. Multiple detected cameras require selection.

Preview preserves aspect ratio without a border and uses a native 1280x720 decoded image, never enlarged beyond native size. **Capture quality** changes PC capture resolution independently of preview resolution and Studio output size. Source-sized video is copied; smaller settings use software H.264 encoding. Camera resolution, microphone, camera selection and SD recording settings are unchanged.

Click **Start Capture**. The button becomes **Stop Capture**, and preview continues through the same FFmpeg input as recording. Starting/stopping involves a brief stream handoff. Every session has a fresh `Capture_<date>_<time>_<id>` directory with five-minute `part_*.mkv` segments. Completed segments survive interruptions; the last segment may need inspection.

Connection details, measurement and storage are under **Options > Connection and storage.** The default destination is `Captures/`. **Known UI limitation:** Capture folder and Browse are disabled while automatic preview is active; editing the destination during preview needs a future fix.

There is no duration field or application recording-duration limit. Power, storage, camera behavior and Wi-Fi still limit sessions. Keep the app open throughout capture and rendering.

### Transfer

Use **Transfer stored clips** to copy new front-camera SD clips. Settings and cancellation are under **Options**. Progress, byte estimates and ETA stay on the same tab. Preview pauses to avoid competing camera traffic.

The two newest clips are skipped by default because they may still be recording. Downloads use `.part` files and verify HTTP content length before renaming. Camera index sizes are whole-KiB estimates. Unreliable camera Range responses mean an interrupted transfer may restart at byte zero.

SQLite history remains at `Transfers/.dashcam_history.sqlite3`. Deleting local sources does not erase history; re-download requires the explicit setting. Mismatched existing files are retained unless replacement is requested through the CLI. Camera files are never deleted.

### Studio

Studio lists transferred drives, live captures, raw segments, rendered segments and final MP4s. Expand a capture to inspect files. Select its parent row and use **Export selected**, or **Open selected folder**. Local deletion requires confirmation and is blocked while media jobs are active. Transferred-drive renders can replace their matching derived export; live finalization always creates a fresh directory.

To remove captures, select one or more session rows or expanded capture files, then choose **Options > Delete selected captures...** The confirmation lists the exact scope: a session means its entire folder, including raw/rendered/final files and support records; a child row means only that file. Selecting both a session and its child counts the session once. Cancel leaves the selection and files unchanged. Windows Recycle Bin is required; the app blocks permanent-delete fallback. Restore recycled items through Windows if needed. Linked folders/junctions, paths outside the capture library, changed selections and active jobs are rejected. A cancellation or failure stops the batch, reports completed items and refreshes the library. Existing source/MP4 delete actions also use recycling for capture selections; transferred-drive delete actions retain their separate explicit confirmations.

**Output size target** offers approximately **1, 2, 4 or 8 decimal GB/hour**, plus source quality. It controls rendered/final video, separately from Live's raw-capture resolution. Hourly targets use average-bitrate encoding with audio included and four-percent headroom. Sizes are estimates, not hard guarantees. The lowest target measured about **0.94 GB/hour** in both camera runs. Selected-output size estimates appear when duration information is available.

Logs are normally hidden under **Tools > Logs.** Runtime logs may contain local paths and device information; review before sharing.

## Music, overlays and final export

1. In **Studio**, set **Output size target** before capture.
2. Open **Options > Studio settings.** Set **Drive music folder**, **Crossfade seconds**, **Channel title** and optional **Route info**. The default music folder is `Music/`; supply your own permitted audio. MP3, M4A, AAC, WAV, FLAC and OGG are supported. Unreadable tracks are skipped; an empty usable playlist prevents rendering.
3. In **Live**, enable **Render overlay + music (Studio quality)**, then **Start Capture**. This checkbox defaults off. Music, title, route, crossfade and target are snapshotted at capture start. GUI changes are not saved between launches; `config.example.json` is a reference, not a loaded configuration.
4. Click **Stop Capture** when finished. Wait for background rendering to finish. Do not select **Stop background rendering** if you want remaining segments rendered.
5. Choose **Live > Options > Finalize saved capture.** Select that session folder, or select its parent row in Studio and click **Export selected**. Retain the same Studio target to avoid a second video encode.
6. Wait for **MP4 ready**. The output is `Capture_<...>/Finalized_<time>_<id>/Capture.mp4`.

Background rendering follows closed segments and keeps raw recordings. It uses one shuffled, crossfaded playlist with a cumulative music timeline, one opening and an ending on the final segment. Overlays follow source resolution without upscaling. Live rendering currently uses CPU H.264 with two threads, AAC music and an ending of up to 20 seconds. Studio's **Video encoder** and **End card seconds** apply to transferred-drive rendering, not live background rendering.

Raw capture and rendering use separate processes; render failure does not stop raw capture. Rendering can fall behind. There is no persisted renderer queue/resume implementation: keep the app open until it drains. Finalization is manual; recording does not automatically produce one final MP4.

Finalization checks closed sessions, complete segments, compatible parameters and space. Matching rendered video is copied; music is encoded once from the saved playlist to avoid per-segment AAC seams. A different hourly target requires encoding. Raw-only sessions can export silently. Complete interrupted rendered sessions can pass explicit recovery validation; arbitrary damaged/incomplete sessions are not guaranteed recoverable.

Each finalization creates a new exclusive directory and fast-start MP4, preserving raw files, rendered segments and previous exports. **Cancel finalization** stops only that export and retains `Capture.partial.mp4` for inspection.

## Storage and long captures

At approximately 3.4 Mbit/s, 720p raw video uses roughly **1.5 GB/hour**. Lower capture resolutions use variable-size encoding and need separate measurement.

For an illustrative eight-hour session at the **1 GB/hour** render target:

| Retained files | Approximate storage |
| --- | ---: |
| Raw 720p capture | 12 GB |
| Rendered segments | 8 GB |
| Final MP4 | 8 GB |
| Total before playlist, partial output and margin | 28 GB |

Plan at least **40 GB free** for that combination. Higher targets, longer sessions and repeated exports need more. This is a capacity estimate, **not an eight-hour test result**. Source-quality rendering has no fixed hourly size. Files are not automatically deleted to free space.

Capture monitors output growth and free space, stopping at a 512 MiB reserve. A started capture makes up to **three reconnect attempts total per session**, assigning new segment numbers without overwriting earlier files. Gaps may occur. After exhaustion it stops as interrupted; manually reconnect and start a new capture. Automatic resume after closure, sleep or prolonged outage is not guaranteed.

During active PC capture, background rendering or Studio/finalization export, the GUI temporarily requests that Windows remain awake. Overlapping jobs share the request; it releases after the last job and on close. The screen may turn off. Idle preview and transfers do not request wakefulness. Status reports active/unavailable requests. This uses [SetThreadExecutionState](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate), without changing saved power plans. It does not override explicit Sleep, lid-close actions, shutdown or battery depletion. Keep the PC and camera powered.

## Files and installation layouts

A source checkout keeps Python modules beside this README. An organized local installation supports:

```text
Dashcam/
  Launch DashGo.vbs          Main GUI launcher
  App/                      Program modules and CLI helper
  Captures/                 Raw, rendered and finalized live sessions
  Music/                    Default music library
  Transfers/                Downloads, history and logs
    Drives/                 Transferred-drive exports
  Support/
    Docs/                   Instructions
    Backups/                Original local source/launcher backups
```

`App/.installed-layout` marks this layout; media defaults resolve from its parent. Captures, music, transfers, history and absolute session paths need not move. The root VBS supports both layouts. The local organized installation retains CMD/PowerShell compatibility entry points. The repository does **not** ship an installer or private migration/backup artifacts; copying code into `App/` alone is not an installation procedure.

CLI examples for a flat checkout (use `App/` module paths in an organized installation):

```powershell
python -B dashcam_downloader.py --help
python -B dashcam_downloader.py --camera http://192.168.169.1
python -B dashcam_downloader.py --download --output D:\Dashcam\Transfers
python -B dashcam_stitch.py --source D:\Dashcam\Transfers --output D:\Dashcam\Transfers\Drives --target-size 1gbh --stitch
```

`dashcam_transfer.ps1` downloads then renders transferred drives. Old absolute-size CLI profiles remain available alongside hourly profiles.

## Protocol evidence

Observed on the supported VSQ10 firmware:

- `/app/getdeviceattr`: device/firmware information.
- `/app/getmediainfo`: RTSP root URL, TCP transport and a separate `port=5000` field. Verified RTSP uses the advertised URL on default port 554; the separate field is not assumed to be its port.
- `/app/getparamitems?param=all` and `/app/getparamvalue?param=all`: settings/options/current indexes. SD-resolution choices do not establish live qualities.
- `/app/getsdinfo`, `/app/getfilelist?folder=loop&start=0&end=99`, and returned `/mnt/card/video_front/..._f.ts` HTTP paths: inventory/download workflow.
- `/app/enterrecorder`: live-server activation verified on this firmware, with SD recording remaining on. No speculative exit, reset, format, erase or settings-write command is implemented.

The official [DashGo iOS listing](https://apps.apple.com/us/app/dashgo/id1303402312) describes preview/control. A [different Yantop-device investigation](https://randhana.com/blog/reverse-engineering-my-dashcams-hidden-rtsp-stream) supplied the activation lead, followed by direct VSQ10 validation. Other commands are not assumed portable.

## Tests and limitations

```powershell
python -B -m unittest discover -s tests -v
$env:DASHGO_MEDIA_TESTS = '1'
python -B -m unittest discover -s tests -v
```

The offline suite passes **70 tests**, including opt-in generated-media integration. Coverage includes URL safeguards, capabilities, unique segments, simulated disk exhaustion/disconnect, shared preview/capture, lower-resolution raw export, source-hash preservation, rendering, final MP4 decoding/audio continuity, repeated exports, history, keep-awake ownership/overlap/release, both path layouts and capture recycling safety. Recycling tests use generated fixtures and cover cancellation, overlapping/multiple selections, active-job protection, path changes, links/junctions, partial failure and permanent-deletion veto. Fixtures are generated locally; tests never connect to the physical camera. GUI tests need an interactive Windows desktop. Python 3.14 temporary-directory permissions can require a normal terminal outside a restricted sandbox.

Separately completed validation:

- Two **separate** 18-minute camera runs: continuous preview, four rendered segments, finalized MP4s, clean decoding and about 0.94 GB/hour at the lowest target.
- One 18-minute synthetic capture/render/finalization endurance run.
- A bounded camera transition test: controlled client EOF/reconnect, unchanged prior-segment hash, preview resumption, 360p raw export and a second unique session.
- A 25.8 MB closed-clip transfer with monotonic progress/ETA and preserved existing copy. The source had timestamp warnings; transfer integrity and source timestamps are distinct checks.
- Installed imports, launcher, library indexing and path preservation; brief real Windows keep-awake acquire/release. No power-plan change.

**Known limits:** no continuous hour-long, eight-hour or moving-drive validation; no renderer restart/resume queue; no persisted GUI settings; no verified rear camera or settings writes. The native-preview endurance run recorded one early **6.5-second UI-loop delay** with unresolved cause. GUI memory stayed near 71 MB and capture FFmpeg near 105 MB in that run, not a guarantee for other workloads.

An earlier interrupted drive retained four raw and four rendered segments totaling about 16m48s, all decodable. Historical Wi-Fi disconnect events aligned with stream termination, supporting connection interruption rather than a renderer crash. The adapter/camera/radio-level cause remains unproven. Complete retained renders were recovered into a new MP4 without changing originals.

No automated CI workflow is currently included. Local passing tests are not hardware certification. Packaging, signing, reproducible builds, accessibility, destination editing during preview, settings persistence and longer field validation remain future work.

## Privacy and license

Only source, generic examples and synthetic test definitions belong in this repository. `.gitignore` excludes footage, music, sessions, databases, logs, local configuration and support/QA artifacts. Review tracked files before publication; ignore rules cannot remove previously tracked data. Public defaults use a generic title; installed personal branding/configuration stays separate.

Camera HTTP is unencrypted on its local Wi-Fi. Do not expose it to the Internet. Live URLs cannot embed credentials, but queries and logs may still contain sensitive information. The app has no telemetry and does not upload footage.

[MIT](LICENSE), copyright 2026 Vincent Mossman. FFmpeg is installed separately and retains its build-specific licensing obligations.
