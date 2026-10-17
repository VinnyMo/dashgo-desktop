# Final candidate: external Microsoft runtime and FFmpeg

Binary source: cb8f7deeb763cd3620096ffb5bf5c2d3da4312de.
Both FFmpeg/ffprobe and Microsoft Visual C++ v14 x64 runtime are user prerequisites.
No automatic prerequisite installation, download or new agreement.

- Confirmed no app-local Microsoft runtime DLLs and no FFmpeg executables.
- 629 Microsoft runtime import symbols across 49 packaged importers match the
  exports of five installed x64 System32 runtime DLLs, version14.51.36247.0.
  This read-only PE check covers Python/Qt dependencies without loading the GUI.
- Both packaged Python console helper entry points passed --help with a
  system-only PATH and no app-local Microsoft runtime DLLs.
- 130 retained Qt/Shiboken files match official wheel hashes; eight wheel
  runtime copies and two CPython runtime copies were excluded.
- Both archive CRC checks passed. Expanded program folder:102,164,390 bytes.
- GUI was NOT launched. Current GUI SHA256:
  7936983cf40c74122ed7466c1b54b96df0dfbfb969241eb83aa6863c5368e445.
  Prior candidate was blocked by VerifiedAndReputableDesktop/Smart App Control.
  No security changes, unblock or repeated GUI launch were attempted.
- ZIP:41,493,793 bytes; SHA256:
  288fc965f0f574c778069a5075326f2adbd728971d55d01247319deb60ab379d.
- Source-review ZIP:121,764,278 bytes; SHA256:
  c6195e3d2c74834ce3f50bbd62b651395ca41568154c650143f8ded14281f1c2.

The specific Qt Microsoft-DLL redistribution question is avoided because those
DLLs are not shipped. Python's existing binary license for linked-in code is
retained. Remaining checks: unsigned-app distribution/Smart App Control handling,
GUI startup and visual review, clean Windows with official prerequisites, owner
approval before publishing. Static import checks are not a GUI launch test.
No full suite or media-render repeat was necessary for DLL exclusion alone.

The following results concern the previous external-FFmpeg candidate only.

---

# Release 0.1 current candidate validation

Binary source commit: 6e5039e07358ad9612d88789dd6945e2cbfe2620.
Host: VANLIFE, Windows 11 x64. FFmpeg/ffprobe are external prerequisites.

- Six targeted packaging/discovery tests passed: portable data/helper paths,
  source interpreter, frozen PATH discovery, explicit override, missing-tool
  instructions and Gyan WinGet fallback.
- Fresh ZIP extraction under a path with spaces passed the packaged missing-
  FFmpeg check with Windows-only PATH and isolated profile environment. It
  reported the installation command, returned failure and created no output.
- GUI startup was BLOCKED by Windows Application Control before app startup.
  CodeIntegrity events3077 and3033 identify DashGo.exe failing the Enterprise
  signing-level/code-integrity policy. No policy settings were changed and no
  alternate launch route was attempted to evade it. Current GUI/taskbar startup
  is therefore unverified, despite passing on the earlier candidate.
- The packaged console helper passed a four-second synthetic H.264/AAC export
  with external FFmpeg/ffprobe9.0.2 Essentials on PATH: gated worker, music,
  overlays, short full decode and source hash preservation. No camera or user
  media was used. This is not a clean Windows VM test.
- Both ZIP CRC checks passed; no FFmpeg/ffprobe executable, vendor manifest,
  license directory or source archive entries are in either current ZIP or
  the application source tar. All138 official Qt/Shiboken file hashes matched.
- Binary ZIP:42,224,761 bytes; expanded package:104,042,685 bytes.
  SHA256:83168dd337996f22b7567b9e21bcd676b4c08900dba160537958614d7bd75139.
- Source-review ZIP:121,752,931 bytes.
  SHA256:96342bae787eaebadaf9a811d0636f541ab222c1974edad4286bbe22311724e8.

Earlier focused tests and icon checks are historical evidence, not a successful
GUI startup result for this newly rebuilt executable. No full suite repeated.
No real capture, installer/uninstaller, installation replacement, paid signing,
new agreement, provider contact, hosted CI, public release or merge occurred.

Remaining gates: resolve the observed Application Control restriction through
an owner/admin-approved distribution path; current GUI/visual and clean-Windows
validation; specific Qt/Shiboken Microsoft-runtime permission/terms; owner
approval. Do not disable security policy as a workaround. FFmpeg source-contact
and redistribution work is stopped and is no longer a release requirement.

Reproduction scripts: smoke-prerequisite.py <package>, smoke-windows.ps1
-Package <package>, smoke-media.py <package> <external ffmpeg.exe>. Each uses
disposable fixtures; no installed app/media is changed. Exact package commit
is BUILD-INFO.json; this post-build evidence update does not change the ZIPs.
