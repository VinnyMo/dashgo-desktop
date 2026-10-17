# Release Version 0.1 (0.1.0) — Windows review build

Portable ZIP, Windows 10/11 x64. Extract the entire folder into a writable location and open DashGo.exe. Python and Qt are included. Keep _internal and DashGoWorker.exe beside it. ARM64 and 32-bit Windows are not supported by this build. Windows 11 x64 is the build/test host; a clean Windows 10 machine remains untested.

FFmpeg and ffprobe 9.0.2 Essentials are bundled under _internal/ffmpeg/bin. No separate FFmpeg installation is needed; packaged execution does not fall back to PATH. FFmpeg provides capture, H.264/AAC encoding, decoding, resampling, music mixing and overlays. Music must be supplied by the user with appropriate rights. Arial is read from Windows, not redistributed.

The portable app defaults to Data/Captures, Data/Transfers and Data/Music beside DashGo.exe. It does not migrate the existing Documents/Dashcam installation or preferences. Existing media can be selected explicitly. GUI settings still are not persisted. Before moving or removing a portable folder, preserve Data and any media stored there. There is no installer, registry registration, upgrade action or uninstaller; removal is manual. Do not extract over another version or your existing installation.

## Build

Use CPython 3.14.4 x64 on Windows, an isolated checkout and a private venv:

```powershell
pwsh -File packaging/fetch-vendor.ps1
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r packaging/requirements-build.txt
.venv\Scripts\python.exe packaging/build.py
```

The build refuses a dirty tracked source tree. Pinning build dependencies and recording the commit makes this recipe repeatable; byte-identical reproducibility across machines has not been established. Build artifacts, a source-review ZIP and SHA256SUMS.txt are under dist. The fetch script verifies pinned archives before use. No hosted CI, installation or signing occurs. GPL/LGPL texts are checked in from qt/qtbase v6.11.0 LICENSES; the build does not download them. PyInstaller uses separate GUI and console worker executables to preserve existing pipe and Windows Job ownership behavior. Qt DLLs remain external and replaceable under _internal/PySide6; replace compatible DLLs together, or rebuild from source with a modified Qt/PySide installation. No integrity check prevents replacement. Unused Qt PDF, QML, Quick and VirtualKeyboard components are excluded.

## Distribution review

Read [LICENSING-REVIEW.md](LICENSING-REVIEW.md) and [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt). Version-specific source archives, notices and attribution records are now included in the local review deliverables. Exact vendor build/dependency source coverage and Microsoft runtime redistribution entitlement remain unresolved; this is not a license-cleared public release. No unfulfilled source offer is made.

The owner requested an all-in-one package. Gyan FFmpeg 9.0.2 Essentials (GPLv3, no enable-nonfree) preserves libx264/AAC and required filters. See FFMPEG-MANIFEST.json for binary/archive hashes and provenance. FFmpeg core source is supplied in the source-review ZIP, but exact statically linked dependency sources/build scripts must still be obtained before distribution. No paid codec license or signing was acquired.

A free NSIS installer is technically possible; the portable ZIP was chosen to preserve the current installation and simplify media/uninstall safety. See the review for the tradeoff. Do not install this portable folder over the existing app.

Unsigned: Windows may display SmartScreen/unknown-publisher or antivirus warnings. There is no paid signing and no certificate. Public download reputation and a clean Windows VM remain untested. The isolated-profile / stripped-PATH check is performed on VANLIFE and is not a clean-machine test.
