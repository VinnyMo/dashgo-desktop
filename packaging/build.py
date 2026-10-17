"""Build an unsigned private-review portable package; never install or publish."""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import json
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
subprocess.run(['git', 'diff', '--exit-code', 'HEAD'], cwd=ROOT, check=True)
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
subprocess.run([sys.executable, str(ROOT/'packaging/make_icon.py')], check=True, cwd=ROOT)
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', 'packaging/dashgo.spec'], check=True, cwd=ROOT)
package = ROOT/'dist/DashGo-0.1.0-windows-x64'
licenses = package/'licenses'
licenses.mkdir(exist_ok=True)
for name in ('LICENSE', 'README.md'):
    shutil.copy2(ROOT/name, package/name)
for name in ('README.md', 'RELEASE-NOTES.md'):
    shutil.copy2(ROOT/'packaging'/name, package/('RELEASE-'+name if name == 'README.md' else name))
shutil.copy2(Path(sys.base_prefix)/'LICENSE.txt', licenses/'CPython-LICENSE.txt')
for name in ('PySide6', 'PySide6_Essentials', 'shiboken6', 'pyinstaller'):
    dist = metadata.distribution(name)
    dest = licenses/name
    dest.mkdir(exist_ok=True)
    (dest/'METADATA.txt').write_text(dist.read_text('METADATA'), encoding='utf-8')
    for item in dist.files or []:
        if 'license' in str(item).lower() and dist.locate_file(item).is_file():
            shutil.copy2(dist.locate_file(item), dest/Path(item).name)
for name in ('LGPL-3.0.txt', 'GPL-3.0.txt'):
    shutil.copy2(ROOT/'packaging/licenses'/name, licenses/name)
(package/'BUILD-INFO.json').write_text(json.dumps({'version':'0.1.0','display_version':'Release Version 0.1','commit':commit,'python':sys.version,'architecture':'AMD64','signed':False,'distribution_status':'PRIVATE REVIEW - licensing audit incomplete'},indent=2),encoding='utf-8')
inventory = {str(p.relative_to(package)): hashlib.file_digest(p.open('rb'), 'sha256').hexdigest()
             for p in sorted(package.rglob('*')) if p.is_file() and p.suffix.lower() in ('.dll', '.exe', '.pyd')}
(package/'BINARY-INVENTORY.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
archive = package.with_suffix('.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as out:
    for path in sorted(package.rglob('*')):
        if path.is_file() and 'Data' not in path.relative_to(package).parts:
            out.write(path,path.relative_to(package.parent))
digest=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
(ROOT/'dist/SHA256SUMS.txt').write_text(f'{digest}  {archive.name}\n',encoding='ascii')
print(f'{archive}: {archive.stat().st_size} bytes; SHA256 {digest}')
