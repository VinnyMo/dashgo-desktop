# Release Version 0.1 (0.1.0) — Windows review build

Portable ZIP, Windows 10/11 x64. Extract the entire folder into a writable location and open DashGo.exe. Python and Qt are included. Keep _internal and DashGoWorker.exe beside it. ARM64 and 32-bit Windows are not supported by this build. Windows 11 x64 is the build/test host; a clean Windows 10 machine remains untested.

Install a complete FFmpeg build separately (ffmpeg.exe and ffprobe.exe), on PATH or in the supported Gyan WinGet location. FFmpeg provides capture, H.264/AAC encoding, decoding, resampling, music mixing and overlays. Music must be supplied by the user with appropriate rights. Arial is read from Windows, not redistributed.

The portable app defaults to Data/Captures, Data/Transfers and Data/Music beside DashGo.exe. It does not migrate the existing Documents/Dashcam installation or preferences. Existing media can be selected explicitly. GUI settings still are not persisted. Before moving or removing a portable folder, preserve Data and any media stored there. There is no installer, registry registration, upgrade action or uninstaller; removal is manual. Do not extract over another version or your existing installation.

## Build

Use CPython 3.14.4 x64 on Windows, an isolated checkout and a private venv:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r packaging/requirements-build.txt
.venv\Scripts\python.exe packaging/build.py
```

The build refuses a dirty tracked source tree. Pinning build dependencies and recording the commit makes this recipe repeatable; byte-identical reproducibility across machines has not been established. Build artifacts and SHA256SUMS.txt are under dist. No hosted CI, installation or signing occurs. GPL/LGPL texts are checked in from qt/qtbase v6.11.0 LICENSES; the build does not download them. PyInstaller uses separate GUI and console worker executables to preserve existing pipe and Windows Job ownership behavior. Qt DLLs remain external and replaceable under _internal/PySide6; replace compatible DLLs together, or rebuild from source with a modified Qt/PySide installation. No integrity check prevents replacement. Unused Qt PDF, QML, Quick and VirtualKeyboard components are excluded.

## Distribution gate — private review only

The project source is MIT. This package contains CPython, PySide6/Shiboken 6.11.0, Qt libraries/plugins, their third-party dependencies, Microsoft runtime DLLs and the PyInstaller bootloader. Included upstream metadata/license files and GPL/LGPL texts are a starting point, not a completed compliance audit.

Before public distribution: inventory every shipped DLL/plugin and third-party notice; provide corresponding Qt/PySide/Shiboken source for the exact wheel build, applicable patches/build information and a compliant source delivery mechanism; verify replacement/rebuild instructions; complete Microsoft runtime redistribution review. The PyPI wheel metadata exposes LGPL/GPL alternatives but its licenses directory only includes a commercial-license reference. That is not sufficient notice/source material for a public binary release. Do not describe this review artifact as license-cleared.

Sources and obligations:
- https://doc.qt.io/qtforpython-6/licenses.html
- https://www.qt.io/development/open-source-lgpl-obligations
- https://download.qt.io/archive/qt/6.11/6.11.0/submodules/
- https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.0-src/
- https://docs.python.org/3.14/license.html
- https://pyinstaller.org/en/stable/license.html
- https://ffmpeg.org/legal.html

FFmpeg is intentionally absent. The installed development build is Gyan FFmpeg 9.0 full, configured --enable-gpl --enable-version3 and libx264/libx265. Bundling that build would require its full GPLv3-compatible distribution/source obligations and dependency notices; codec patent considerations vary by jurisdiction. This package supplies no FFmpeg or codec licenses on the user's behalf.

Unsigned: Windows may display SmartScreen/unknown-publisher or antivirus warnings. There is no paid signing and no certificate. Public download behavior/SmartScreen reputation has not been tested.
