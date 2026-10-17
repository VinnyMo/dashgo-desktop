# Release 0.1 distribution review

Engineering review dated 2026-10-17. This records evidence and unresolved
rights/provenance questions; it is not legal certification. The all-in-one
binary is usable for owner review but is **not ready for public distribution**.

## Follow-up supersedes unresolved provenance wording

See [PROVENANCE-FOLLOWUP.md](PROVENANCE-FOLLOWUP.md) for verified official wheel
file hashes, matched Mesa PE sections, all ten signed Microsoft DLLs, the
downstream distribution clause, and an exact FFmpeg missing-material list.
The earlier table below records the initial review; the follow-up narrows its
open questions. A personal Visual Studio purchase is not established as needed.

## Actual components and evidence

| Component | Evidence / action | Remaining issue |
| --- | --- | --- |
| DashGo | MIT source/icon; source snapshot and commit recorded | Owner review |
| CPython 3.14.4 x64 | Installed interpreter version; original LICENSE.txt; official 3.14.4 source archive | No Python source modification; dependent runtime issues below |
| Qt/PySide/Shiboken 6.11.0 | qVersion and QLibraryInfo report dynamic MSVC 2022 build; PyPI metadata; Qt source archives for qtbase, qtsvg, qtimageformats, qttranslations and pyside-setup; license files and upstream attribution records collected | Release-version source is available, but the precise wheel build options/patch provenance and a replacement-library rebuild have not been independently reproduced |
| Qt third parties | Upstream qt_attribution.json and its referenced LicenseFile content preserved; complete source archives retained; actual binary inventory supplied | Confirm compiled-in component selection against vendor wheel build configuration; notice collection is deliberately broader than shipped code |
| Python dependencies | OpenSSL reports 3.0.19; SQLite reports 3.50.4. CPython 3.14.4 PCbuild/get_externals.bat pins libffi 3.4.4, bzip2 1.0.8, XZ 5.2.5, zlib-ng 2.2.4, Zstd 1.5.7; Python and extra vendor notices included | Exact static-component mapping is based on CPython's release build recipe, not a rebuild of python.org binaries |
| Mesa/LLVM | opengl32sw.dll strings identify Mesa 11.2.2 / LLVM 3.6.2; both source archives and license/copyright files retained | Exact Qt prebuilt software-renderer build/patch provenance remains unverified |
| Microsoft runtimes | Unmodified MSVCP140*, VCRUNTIME140* from Python/PySide/Shiboken; their hashes recorded | Microsoft's redistribution page limits distribution to appropriately licensed Visual Studio users under the relevant terms. No developer license entitlement has been established here, and no agreement was accepted |
| PyInstaller 6.16.0 | Original COPYING.txt includes bootloader exception; pinned build recipe | Its exception does not waive Qt/FFmpeg/Microsoft obligations |
| FFmpeg/ffprobe | Gyan 9.0.2 Essentials GPLv3 static x64; vendor SHA-256 matched; -version/-buildconf/-L retained; no enable-nonfree; core tag n9.0.2 resolves to 946fcce07b6dcd0331c8cc609192aeff5e1924f8 matching vendor README | Core source alone is insufficient for the statically linked dependencies. Exact dependency sources, patches, configuration/build scripts and complete attribution must be obtained or replaced by a documented build from source before distribution |

The Microsoft DLL provenance was traced to the Python/PySide distributions,
not an arbitrary system directory. Their original copyright metadata remains.
Being included by another distributor does not itself establish this owner's
redistribution rights. An alternative is making the Microsoft redistributable
a prerequisite, but that weakens the all-in-one goal and is not applied here.

## Source delivery and user rights

The separate `DashGo-0.1.0-source-review.zip` contains application source at the
exact build commit and nine versioned upstream source archives with URLs,
lengths and SHA-256 hashes. This closes the absence-of-source-material gap;
it is not advertised as a complete Corresponding Source package.

Use direct accompanying source delivery when the missing material is complete.
Do not substitute a link to a moving upstream branch for corresponding source.
Do not publish a three-year written source offer unless the owner explicitly
undertakes and can fulfill that ongoing obligation. No such offer is made or
accepted by this task. Public hosting should place the completed source bundle
and notices beside the matching binary/checksum assets.

The LGPL libraries remain external DLLs, not inside a one-file self-extractor.
The notice file describes replacement and permits reverse engineering for
debugging library modifications. Full MIT application source and the build
recipe are supplied. A matching modified-library rebuild test remains pending.

## FFmpeg choice

The owner requested all-in-one distribution. The package includes both tools
and selects `_internal/ffmpeg/bin` before any host installation. Gyan Essentials
retains libx264, AAC, RTSP, audio mixing, drawtext and the app's other tested
filters; its GPLv3 status is disclosed. An LGPL-only alternative would omit
libx264 and require feature/encoder changes, so it was not silently substituted.
No proprietary/nonfree codec or paid license was acquired. Separate-process
invocation does not excuse distributing FFmpeg's corresponding source and
notices; the precise combined-work and codec-patent analysis remains a legal
question rather than an engineering certification.

## Portable ZIP and installer decision

Portable ZIP was chosen because it needs no administrator access, preserves
the existing installed app, keeps Qt libraries replaceable, and avoids an
uninstaller touching recordings. The owner launches DashGo.exe from the fully
extracted folder. No registry registration or automatic migration occurs.

A simple NSIS per-user Setup.exe can be built with free tools and no account.
NSIS's default installer code and zlib compression use the zlib/libpng license;
choosing zlib avoids the extra LZMA/CPL terms. This does not require a paid
signing service or a new click-through agreement. It still has open-source
conditions and inherits every dependency gate above. No installer was built or
installed in this pass. Before preparing one, define a stable data location and
an explicit file manifest so upgrade/uninstall can remove only program files
and always preserve Data/user-selected media. Packaging into Setup.exe alone
does not resolve licensing or signing.

## Primary references

- Qt obligations: https://www.qt.io/development/open-source-lgpl-obligations
- Qt for Python licenses: https://doc.qt.io/qtforpython-6/licenses.html
- Qt source archives: https://download.qt.io/archive/qt/6.11/6.11.0/submodules/
- PySide source: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.0-src/
- Python source/license: https://www.python.org/downloads/release/python-3144/ and the bundled 3.14.4 LICENSE.txt
- Microsoft redistribution: https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution
- PyInstaller exception: https://pyinstaller.org/en/v6.16.0/license.html
- FFmpeg obligations: https://ffmpeg.org/legal.html
- Gyan build/license/provenance: https://www.gyan.dev/ffmpeg/builds/ and the retained version-specific README.txt
- Qt software renderer: https://doc.qt.io/qt-6/windows-graphics.html
- Mesa archive: https://archive.mesa3d.org/older-versions/11.x/11.2.2/
- LLVM license: https://releases.llvm.org/3.6.2/LICENSE.TXT
- NSIS license: https://nsis.sourceforge.io/License

No public publication, merge, purchase, signing, new legal agreement, camera
capture or installed-app modification was performed. Clean Windows VM testing
and owner taskbar appearance review remain pending. A stripped-PATH test with
isolated profile environment variables on VANLIFE is not a clean-machine test.
