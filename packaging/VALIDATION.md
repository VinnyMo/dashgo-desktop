# Release 0.1 local validation

Host: VANLIFE, Windows 11 Pro 10.0.26300 x64. No camera was connected by the
checks, and the original installed app/media were not changed.

- 24 focused source tests passed during initial packaging (6 owned-job, 11 Qt,
  5 power/path, 2 portable path tests). The expanded packaging test file now has
  3 passing tests, including bundled FFmpeg preference and refusal to fall back
  to a host installation when the bundled tools are missing.
- The all-in-one ZIP was extracted into a fresh workspace directory with spaces
  in its name. Startup used an unrelated working directory, Windows-only PATH,
  isolated USERPROFILE/APPDATA/LOCALAPPDATA directories, and cleared Python/Qt
  import/plugin overrides. Camera auto-connect was disabled for this test.
- Native release window title, small/large icon handles, clean close and both
  packaged CLI helper entry points passed. ICO frames include 16, 24, 32, 48,
  64, 128 and 256 pixels. Taskbar visual/pinned-shortcut review remains pending.
- A four-second synthetic 320x180 H.264 clip plus generated sine-wave music was
  processed by the packaged gated worker and stitcher without an explicit
  FFmpeg override. Bundled ffprobe verified H.264/AAC streams, bundled FFmpeg
  fully decoded the short output, and the original synthetic clip hash matched.
  This checks bundled tool discovery, worker routing, music, overlays and
  rendering without a real capture or existing media.
- The executable is NotSigned. Actual downloaded-file SmartScreen reputation
  and a separate clean Windows VM have not been tested.

This is an isolated profile-environment test on a development machine, not a
new Windows user account or a clean-machine test. Windows system libraries and
Arial remain host-provided. No installer/uninstaller was executed. The portable
format does not register an app or migrate/remove data; its builder refuses to
overwrite nonempty portable Data.

Run `packaging/smoke-windows.ps1 -Package <fresh extracted folder>` and
`python packaging/smoke-media.py <fresh extracted folder>` for the focused
checks. Synthetic fixtures and profile directories are retained in TEMP for
inspection. Exact final artifact commit/hashes are in BUILD-INFO.json,
BINARY-INVENTORY.json and SHA256SUMS.txt; do not infer them from this document.
