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

# Release 0.1 distribution review

Review dated 2026-10-17. The current candidate requires user-installed FFmpeg
and ffprobe. Neither executable nor its vendor/source distribution material is
shipped. The earlier all-in-one candidate is superseded; provider contact and
FFmpeg source collection are stopped. No email was sent.

## Bundled components

- DashGo source and camera icon: MIT.
- CPython3.14.4: original binary LICENSE.txt retained, including Additional
  Conditions for this Windows binary build. It explicitly addresses onward
  Microsoft-code distribution and required protective downstream terms.
  Both runtime DLLs match Python's official embedding distribution.
- PySide6/Qt/Shiboken6.11.0: external replaceable libraries under applicable
  LGPLv3 and third-party terms. All 138 checked shipped wheel files match
  official PyPI artifacts. Qt module/PySide source archives and their license
  and attribution material are included in the source-review deliverable.
- Mesa11.2.2/LLVM3.6.2: all eight PE sections match Qt's official renderer;
  permissive license/copyright files and versioned sources retained.
- PyInstaller6.16.0: bootloader distribution exception retained.
- Microsoft runtime: ten signed unmodified copies; exact inventory retained.
  Eight Qt/Shiboken copies are14.44.35211.0; two Python copies14.42.34438.0.

See PROVENANCE-FOLLOWUP.md, WHEEL-PROVENANCE.json, QT-ATTRIBUTIONS.json,
MICROSOFT-RUNTIME-INVENTORY.json and the built BINARY-INVENTORY.json.

## Specific outstanding runtime question

Microsoft's Visual Studio terms allow upstream licensees to authorize downstream
distributors. Microsoft documentation permits app-local redistributable DLLs
subject to licensing. Therefore no personal Visual Studio purchase is established
as necessary. Python's binary license supplies redistribution conditions and
is already carried in the package.

The remaining item is Qt's authorization/terms for downstream shipment of the
Microsoft DLLs in the PySide6/Shiboken6.11.0 Windows wheels, including required
protective end-user terms. The wheel metadata declares the Qt binding license;
its packaged LicenseRef-Qt-Commercial.txt contains no Microsoft-specific grant.
That is a missing permission-chain confirmation, not proof of infringement.
Qt's deployment guide recommends official vc_redist installation but also
lists runtime DLLs in app archives; it does not conclusively settle this exact
wheel-repackaging case. Qualified review or Qt confirmation can resolve it.
Switching to a redistributable installer is not an automatic licensing cure.
No new agreement, purchase or provider contact was undertaken.

## Source delivery and replacement

The source-review ZIP contains the exact application source and eight upstream
source archives listed in SOURCE-MANIFEST.json. Keep source/notices alongside
the eventual binary download. No three-year written source offer is made.
Qt DLLs remain external and replaceable; DashGo permits reverse engineering
for debugging modifications to those libraries. Source and build recipe are
provided. A modified-library rebuild/replacement validation remains pending;
no failed replacement test has been observed.

## Publication and validation decisions

Portable ZIP preserves the installed app, avoids registry/upgrade/uninstall
actions, and keeps libraries replaceable. The builder refuses to overwrite
nonempty portable Data. Users must preserve Data before manual folder removal.
No installer/uninstaller was built or tested. A future installer requires an
explicit program-only removal manifest; it is outside this candidate.

Before public publication: settle the specific Qt/Microsoft terms item, run the
clean-Windows plan, and obtain owner visual/package approval. The current app
is unsigned; SmartScreen/unknown-publisher warnings are expected possibilities.
No signing purchase, hosted CI, public release or merge was performed.

## Primary sources

- Python embedding: https://github.com/python/cpython/blob/v3.14.4/Doc/using/windows.rst
- Python binary license: licenses/CPython-LICENSE.txt in the package and official
  https://www.python.org/ftp/python/3.14.4/python-3.14.4-embed-amd64.zip
- Qt obligations: https://www.qt.io/development/open-source-lgpl-obligations
- Qt licenses: https://doc.qt.io/qtforpython-6/licenses.html
- Qt deployment: https://doc.qt.io/qt-6.11/windows-deployment.html
- Microsoft terms: https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/
- App-local deployment: https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files
- PyInstaller: https://pyinstaller.org/en/v6.16.0/license.html
