# Build from repository root: python -m PyInstaller packaging/dashgo.spec
from pathlib import Path
root = Path(SPECPATH).parent
common = dict(pathex=[str(root)], excludes=['tkinter'], noarchive=False)
ffmpeg = root/'vendor/ffmpeg-9.0.2/ffmpeg-9.0.2-essentials_build/bin'
gui = Analysis([str(root/'dashcam_qt.py')], datas=[(str(root/'assets/dashgo.ico'),'assets'),
    (str(ffmpeg/'ffmpeg.exe'), 'ffmpeg/bin'), (str(ffmpeg/'ffprobe.exe'), 'ffmpeg/bin')], **common)
# PyInstaller's broad Qt plugin hook pulls in unused PDF/virtual-keyboard/QML
# libraries. Keep this Widgets application free of those optional components.
unused = ('Qt6Pdf', 'Qt6VirtualKeyboard', 'Qt6Qml', 'Qt6Quick')
gui.binaries = [item for item in gui.binaries if not (
    Path(item[0]).name.startswith(unused) or
    'platforminputcontexts' in item[0] or Path(item[0]).name == 'qpdf.dll')]
worker = Analysis([str(root/'dashgo_cli.py')], hiddenimports=['dashcam_worker','dashcam_downloader','dashcam_stitch'], **common)
g = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name='DashGo', console=False, icon=str(root/'assets/dashgo.ico'), version=str(root/'packaging/windows-version.txt'), upx=False)
w = EXE(PYZ(worker.pure), worker.scripts, [], exclude_binaries=True, name='DashGoWorker', console=True, icon=str(root/'assets/dashgo.ico'), version=str(root/'packaging/windows-version.txt'), upx=False)
COLLECT(g,w,gui.binaries,gui.datas,worker.binaries,worker.datas,strip=False,upx=False,name='DashGo-0.1.0-windows-x64')
