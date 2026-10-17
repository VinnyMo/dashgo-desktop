# Release Version 0.1 (0.1.0) — Windows review build

Portable ZIP, Windows 10/11 x64. Extract the entire folder into a writable location and open DashGo.exe. Python and Qt are included. Keep _internal and DashGoWorker.exe beside it. ARM64 and 32-bit Windows are not supported by this build. Windows 11 x64 is the build/test host; a clean Windows 10 machine remains untested.

FFmpeg and ffprobe are external prerequisites installed by the user. See the main README for WinGet/manual installation, PATH verification and the tested 9.0.2 Essentials build. Packaged and source execution use PATH then the standard per-user Gyan.FFmpeg WinGet directory. FFmpeg provides capture, H.264/AAC encoding, decoding, resampling, music mixing and overlays. Music must be supplied by the user with appropriate rights. Arial is read from Windows, not redistributed.

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

Read [LICENSING-REVIEW.md](LICENSING-REVIEW.md) and [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt). Version-specific source archives, notices and attribution records for bundled components accompany the review deliverables. The specific Qt/Shiboken Microsoft runtime downstream permission/terms question remains recorded in the licensing review. Python's binary license explicitly describes its redistribution conditions. No personal paid Visual Studio license is established as necessary. No unfulfilled source offer is made.

FFmpeg/ffprobe binaries, vendor distribution notices and source archives are excluded. The build does not fetch them. Users obtain a complete FFmpeg installation separately. No provider contact or paid license/signing was acquired.

A free NSIS installer is technically possible; the portable ZIP was chosen to preserve the current installation and simplify media/uninstall safety. See the review for the tradeoff. Do not install this portable folder over the existing app.

Unsigned: Windows may display SmartScreen/unknown-publisher or antivirus warnings. There is no paid signing and no certificate. Public download reputation and a clean Windows VM remain untested. The isolated-profile / stripped-PATH check is performed on VANLIFE and is not a clean-machine test.
