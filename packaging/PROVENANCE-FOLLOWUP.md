# Release 0.1 provenance follow-up — 2026-10-17

This is an audit supplement to the unchanged owner-review package built from
`f1f52d59d092c200a2f5eeac247f2efebc4d15f5`. It is not a new binary build or a
claim that the source-review ZIP is complete Corresponding Source.

## Verified Qt and runtime provenance

`WHEEL-PROVENANCE.json` records official PyPI download URLs and SHA-256 values.
Both complete wheels match PyPI's published hashes. All 133 shipped files found
in PySide6 Essentials and all five in Shiboken match their wheel bytes. This
covers the six Qt DLLs (Core, Gui, Network, OpenGL, Svg, Widgets), bindings,
plugins, translations, software renderer and wheel-bundled Microsoft DLLs.
There is no evidence of local modifications to these upstream binaries.
Versioned Qt/PySide source archives and attribution/license records were already
collected. An independently reproduced Qt build is not itself a prerequisite
for demonstrating that these files came from official wheels.

The official Qt renderer archive at
https://download.qt.io/development_releases/prebuilt/llvmpipe/windows/opengl32sw-64-mesa_11_2_2-signed_sha256.7z
matches the vendor checksum `c61f801c1760aa24b02c7a8354323cddf368b86f8f5c34b50b3b224f7d728afd`.
Its complete DLL hash differs from the wheel DLL, but **all eight PE section
contents match byte-for-byte**. This establishes matching compiled code/data;
it does not assert identical signatures or headers. Mesa 11.2.2 and LLVM 3.6.2
source and notices are retained. Their permissive licenses require notices,
not a mandatory reproducible-build source offer. This is no longer an unknown
binary-origin blocker.

## Microsoft DLLs: narrowed legal question

`MICROSOFT-RUNTIME-INVENTORY.json` lists all ten copies, their hashes, versions
and valid Authenticode results. Two root VCRUNTIME DLLs are 14.42.34438.0 from
CPython and byte-match the official python.org 3.14.4 AMD64 embedding ZIP; five PySide6 and three Shiboken DLLs are 14.44.35211.0. The latter eight
match official wheels. These are app-local upstream dependencies, not files
copied from Windows/System32 or another application's runtime.

The full [Visual Studio Community 2022 terms](https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/)
expressly permit the licensee to authorize downstream distribution of runtime
code with its applications. They also impose protection and distribution
conditions. Therefore the general Microsoft redistribution webpage does **not**
establish that this owner personally must purchase or install Visual Studio.
Conversely, signatures and upstream possession do not establish the specific
downstream grant. The [runtime end-user terms](https://visualstudio.microsoft.com/license-terms/vs2022-cruntime/)
grant installation/use and are not by themselves a general redistribution grant.

Remaining legal interpretation: confirm that Python/Qt's upstream distribution
permission covers repackaging these unmodified runtimes with their libraries
inside DashGo, and identify the end-user notice/terms required for that route.
Correction from the subsequent binary-license inspection: the bundled
CPython-LICENSE.txt contains Additional Conditions for this Windows binary
build, explicitly addressing redistribution and Microsoft-code protections.
This supports Python redistribution subject to those conditions; no equivalent
Microsoft-specific statement was found in the Qt/Shiboken wheel license files. Do not call this an established
license violation or require a new paid agreement. Owner decision is whether
to obtain upstream confirmation/legal review of that existing route before
public distribution. No agreement was accepted here.

## FFmpeg: exact documentation gap

The provider's public repository is a support/release mirror, not the build
recipe. The 9.0.2 binary's README supplies the revisions below; the existing
source-review ZIP contains FFmpeg core source, **not these dependency sources**.
The matching provider build scripts, patches, transitive dependency manifest
and source bundle were not found among the published records inspected.

| Dependency | Provider's exact recorded version/revision |
| --- | --- |
| AMF | v1.5.2-2-gc35f613 |
| aom | v3.15.0-25-g023743a7d7 |
| AviSynthPlus | v3.7.5-383-g5c82777b |
| cairo | 1.18.5 (exact commit unresolved) |
| ffnvcodec | n13.1.15.0-1-geddcea9 |
| freetype | VER-2-14-3 |
| fribidi | v1.0.16-19-gc928e4c |
| gsm | 1.0.24 |
| harfbuzz | 14.4.0-108-g64e2b532 |
| lame | 3.100 |
| libass | 0.17.5-8-gb2fe9d8 |
| libgme | 0.6.6 (exact commit unresolved) |
| opencore-amrnb / amrwb | 0.1.6 |
| libssh | 0.12.2 |
| libtheora | v1.2.0 |
| libwebp | v1.6.0-249-g1f34635 |
| openal-soft | 1.25.2-48-g7532541 |
| openjpeg2 | 2.5.4 |
| openmpt | libopenmpt-0.6.30-3-g6c0a06bc |
| opus | v1.6.1-68-g503d81b1 |
| rubberband | v4.0.0 |
| SDL | release-2.32.0-234-gb90ac9502 |
| speex | Speex-1.2.1-51-g0589522 |
| srt | v1.5.7-7-gcae8f62 |
| VAAPI | 2.25.0. (confirm libva tag) |
| vidstab | v1.1.2-214-ge2445c4 |
| vmaf | v3.2.0-13-gf85a8536 |
| vo-amrwbenc | 0.1.3 |
| vorbis | v1.3.7-37-g1b75110b |
| VPL | 2.17 |
| vpx | v1.17.0-57-gd2413e2ca |
| x264 | v0.165.3223 (confirm source commit) |
| x265 | 4.3-45-g116b875 |
| xvid | v1.3.7 |
| zeromq | 4.3.5 |
| zimg | release-3.0.6-253-g67e0603 |

Configured libraries without exact versions in that list: fontconfig, iconv,
GnuTLS, libxml2, GMP, bzip2, XZ/liblzma and zlib. Obtain the transitive manifest
too (including any nettle, pixman, libpng, ogg and MinGW/GCC runtime components
actually linked); do not borrow versions inferred for another release.
Build requirements include the gcc16.2.0/MSYS2 package revisions, dependency
configure options, local patches and the scripts controlling compilation.

A directly relevant [provider issue #246](https://github.com/GyanD/codexffmpeg/issues/246)
asks for the same missing material for an earlier build. On 2026-10-13 the
maintainer [requested contact from an official email address](https://github.com/GyanD/codexffmpeg/issues/246#issuecomment-6141911951).
This supplies a concrete next step, not evidence that the requested material
is already public. No email or issue was sent on the owner's behalf.

Owner action: authorize a source-manifest request identifying **9.0.2 Essentials**
and executable hashes in FFMPEG-MANIFEST.json, or choose a separately documented
source build. Merely collecting generic release tarballs cannot establish
matching patches/transitive inputs. This is missing documentation, distinct
from the remaining codec patent/combined-work legal interpretation.

## Clean Windows validation

No usable existing clean Windows environment was established: WindowsSandbox.exe
is absent, Hyper-V's root/virtualization/v2 namespace is unavailable, and the
queried VirtualBox/VMware installation records were absent. Running vmcompute
alone does not establish a Windows VM. Nothing was installed/enabled/booted.

For an owner-provided disposable Windows 10/11 x64 environment: use a standard
user with no Python, Qt or FFmpeg installed; copy and verify the current ZIP
against SHA256SUMS; extract to a writable path containing spaces; run the
packaged smoke-windows.ps1 and smoke-media.py using a separate test harness
where needed; visually inspect camera/taskbar identity; launch without camera;
verify bundled ffmpeg/ffprobe are the executed tools and a short synthetic
H.264/AAC export decodes; close and reopen to check preferences; delete only
the disposable program folder after preserving its Data folder and prove an
outside sentinel/media folder remains unchanged. There is no installer or
uninstaller in this release candidate, so no installer safety claim is made.

Already-passed owner-machine smoke tests were not repeated: no packaged code
or binaries changed in this audit. Remaining public-release gates are the
FFmpeg source/build packet, Microsoft pass-through confirmation/terms, clean
Windows check, and owner approval. Qt modified-library replacement remains
a useful focused validation, not evidence of a currently failed test.
