# Current packaging decision: external Microsoft runtime

The owner approved excluding all app-local Microsoft runtime DLLs. The current
package requires user-installed Microsoft Visual C++ v14 X64 Redistributable
14.44.35211.0 or newer, obtained directly from Microsoft. No installer is bundled
or invoked. This removes the specific redistribution question for those DLLs;
no Qt permission inquiry or new agreement is needed for files not distributed.
Python's existing binary-license conditions for linked-in Microsoft code remain
included. The records below are historical provenance, not the current file list.
WHEEL-PROVENANCE.json separates eight excluded wheel runtime copies from the
130 retained wheel-file matches. MICROSOFT-RUNTIME-INVENTORY.json records ten
excluded copies. BINARY-INVENTORY.json identifies actual package contents.

Remaining checks: unsigned-app/Smart App Control policy, current GUI and clean
Windows validation with both prerequisites installed, owner review. No public
release/merge or claim of successful current GUI startup. No security changes.

---

# Release 0.1 provenance follow-up — 2026-10-17

The current candidate uses external user-installed FFmpeg/ffprobe. Its build
commit is recorded in BUILD-INFO.json. The prior all-in-one package is superseded.
The evidence below concerns unchanged bundled Qt/Python dependencies.

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

## External media prerequisite

FFmpeg and ffprobe are not distributed. Their source/build collection and
provider-contact work are stopped. README.md documents user setup and the
9.0.2 Essentials build used for external-tool checks.

## Clean Windows validation

No usable existing clean Windows environment was established: WindowsSandbox.exe
is absent, Hyper-V's root/virtualization/v2 namespace is unavailable, and the
queried VirtualBox/VMware installation records were absent. Running vmcompute
alone does not establish a Windows VM. Nothing was installed/enabled/booted.

For an owner-provided disposable Windows 10/11 x64 environment: use a standard
user with no Python or Qt installed; first test without FFmpeg, then install the documented external prerequisite; copy and verify the current ZIP
against SHA256SUMS; extract to a writable path containing spaces; run the
packaged smoke-windows.ps1 and smoke-media.py using a separate test harness
where needed; visually inspect camera/taskbar identity; launch without camera;
verify the documented external ffmpeg/ffprobe are the executed tools and a short synthetic
H.264/AAC export decodes; close and reopen to check preferences; delete only
the disposable program folder after preserving its Data folder and prove an
outside sentinel/media folder remains unchanged. There is no installer or
uninstaller in this release candidate, so no installer safety claim is made.

The switch to an external prerequisite requires a targeted package rebuild,
missing-prerequisite check, startup check and short external-tool render check.
Results are recorded in VALIDATION.md. No lengthy captures or full suite rerun.
Remaining publication gates: Qt/Shiboken Microsoft-runtime permission/terms,
clean Windows validation and owner visual/package approval. FFmpeg source
collection is no longer a gate. Modified-Qt replacement remains a useful
focused validation, not evidence of a currently failed test.
