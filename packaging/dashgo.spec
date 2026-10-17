# Build from repository root: python -m PyInstaller packaging/dashgo.spec
from pathlib import Path
root = Path(SPECPATH).parent
common = dict(pathex=[str(root)], excludes=['tkinter'], noarchive=False)
gui = Analysis([str(root/'dashcam_qt.py')], datas=[(str(root/'assets/dashgo.ico'),'assets')], **common)
# PyInstaller's broad Qt plugin hook pulls in unused PDF/virtual-keyboard/QML
# libraries. Keep this Widgets application free of those optional components.
unused = ('Qt6Pdf', 'Qt6VirtualKeyboard', 'Qt6Qml', 'Qt6Quick')
gui.binaries = [item for item in gui.binaries if not (
    Path(item[0]).name.startswith(unused) or
    'platforminputcontexts' in item[0] or Path(item[0]).name == 'qpdf.dll')]
worker = Analysis([str(root/'dashgo_cli.py')], hiddenimports=['dashcam_worker','dashcam_downloader','dashcam_stitch'], **common)
# Microsoft runtime DLLs are supplied by the user's official x64 Redistributable.
def is_microsoft_runtime(item):
    name = Path(item[0]).name.lower()
    return name.endswith('.dll') and name.startswith(('vcruntime', 'msvcp', 'concrt', 'vcomp'))

for analysis in (gui, worker):
    analysis.binaries = [item for item in analysis.binaries if not is_microsoft_runtime(item)]
    analysis.datas = [item for item in analysis.datas if not is_microsoft_runtime(item)]

g = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name='DashGo', console=False, icon=str(root/'assets/dashgo.ico'), version=str(root/'packaging/windows-version.txt'), upx=False)
w = EXE(PYZ(worker.pure), worker.scripts, [], exclude_binaries=True, name='DashGoWorker', console=True, icon=str(root/'assets/dashgo.ico'), version=str(root/'packaging/windows-version.txt'), upx=False)
COLLECT(g,w,gui.binaries,gui.datas,worker.binaries,worker.datas,strip=False,upx=False,name='DashGo-0.1.0-windows-x64')
