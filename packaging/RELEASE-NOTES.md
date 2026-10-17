# Release Version 0.1

Draft — owner review required; not approved for public distribution.

First portable Windows x64 review package of the current DashGo Desktop. Adds a simple blue camera icon for the application/window/taskbar and executable resources. Tooling version: 0.1.0.

Existing Live, Transfer and Studio workflows are retained. Python 3.14.4 and PySide6/Qt 6.11.0 are included. **FFmpeg and ffprobe are required separately**: install with `winget install --id Gyan.FFmpeg --exact`, or use the manual Essentials ZIP/PATH instructions in README.md. External 9.0.2 Essentials was the tested build. Restart DashGo after installation. Supply your own music. Extract the whole ZIP to a writable folder, then open DashGo.exe. Media defaults to the portable Data directory. No installer or existing-install migration is included.

This is unsigned software; Windows may warn about its publisher or reputation. NEXPOW VSQ10 is the tested camera family. Rear camera, full iOS parity, persisted settings, renderer restart/resume and continuous eight-hour reliability remain unverified or unavailable. No new hardware/capture certification was performed for this release.

Public release remains pending the specific Qt/Shiboken Microsoft runtime downstream permission/terms confirmation, clean-Windows validation and owner review. FFmpeg distribution/source collection is no longer a release task because its binaries are not shipped. Versioned source-review archives, notices and build provenance are supplied; these are not a completed compliance certification. GitHub Releases can host the eventual ZIP and checksums; no release is published automatically by the build.
