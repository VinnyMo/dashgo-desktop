"""Build an unsigned private-review portable package; never install or publish."""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
source_manifest = json.loads((ROOT/'packaging/SOURCE-MANIFEST.json').read_text(encoding='utf-8'))
for item in source_manifest:
    source = ROOT/'vendor-sources'/item['file']
    if hashlib.file_digest(source.open('rb'), 'sha256').hexdigest() != item['sha256']:
        raise SystemExit(f'Unexpected source archive: {source}')
data = ROOT/'dist/DashGo-0.1.0-windows-x64/Data'
if data.exists() and any(data.iterdir()):
    raise SystemExit('Preserve the existing portable Data folder before rebuilding; refusing to overwrite it.')
subprocess.run(['git', 'diff', '--exit-code', 'HEAD'], cwd=ROOT, check=True)
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
subprocess.run([sys.executable, str(ROOT/'packaging/make_icon.py')], check=True, cwd=ROOT)
build_env = os.environ.copy()
# Do not discover DLLs from unrelated applications on the host PATH.
build_env['PATH'] = os.pathsep.join([str(Path(sys.executable).parent),
    str(Path(os.environ['SystemRoot'])/'System32'), os.environ['SystemRoot']])
subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', 'packaging/dashgo.spec'],
               check=True, cwd=ROOT, env=build_env)
package = ROOT/'dist/DashGo-0.1.0-windows-x64'
if any(p.name.lower() in ('ffmpeg.exe', 'ffprobe.exe') for p in package.rglob('*')):
    raise SystemExit('External-prerequisite package must not contain FFmpeg executables.')
if any(p.suffix.lower() == '.dll' and p.name.lower().startswith(('vcruntime', 'msvcp', 'concrt', 'vcomp')) for p in package.rglob('*')):
    raise SystemExit('Microsoft runtime DLLs must remain an external prerequisite.')
licenses = package/'licenses'
licenses.mkdir(exist_ok=True)
shutil.copytree(ROOT/'packaging/licenses', licenses/'upstream-notices', dirs_exist_ok=True)
for name in ('THIRD-PARTY-NOTICES.txt', 'LICENSING-REVIEW.md', 'SOURCE-MANIFEST.json', 'QT-ATTRIBUTIONS.json', 'PROVENANCE-FOLLOWUP.md', 'MICROSOFT-RUNTIME-INVENTORY.json', 'WHEEL-PROVENANCE.json'):
    shutil.copy2(ROOT/'packaging'/name, package/name)
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
(package/'BUILD-INFO.json').write_text(json.dumps({'version':'0.1.0','display_version':'Release Version 0.1','commit':commit,'python':sys.version,'architecture':'AMD64','signed':False,'distribution_status':'RELEASE CANDIDATE - owner review pending','ffmpeg':'external prerequisite; not bundled','msvc_runtime':'user-installed Microsoft Visual C++ v14 x64, 14.44.35211.0 or newer; not bundled'},indent=2),encoding='utf-8')
inventory = {str(p.relative_to(package)): hashlib.file_digest(p.open('rb'), 'sha256').hexdigest()
             for p in sorted(package.rglob('*')) if p.is_file() and p.suffix.lower() in ('.dll', '.exe', '.pyd')}
(package/'BINARY-INVENTORY.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
archive = package.with_name(package.name + '.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as out:
    for path in sorted(package.rglob('*')):
        if path.is_file() and 'Data' not in path.relative_to(package).parts:
            out.write(path,path.relative_to(package.parent))
digest=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
source_zip = ROOT/'dist/DashGo-0.1.0-source-review.zip'
application_source = subprocess.check_output(['git', 'archive', '--format=tar', commit], cwd=ROOT)
with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_STORED) as out:
    out.writestr('dashgo-source.tar', application_source)
    for item in source_manifest:
        out.write(ROOT/'vendor-sources'/item['file'], 'upstream/'+item['file'])
    for name in ('SOURCE-MANIFEST.json', 'LICENSING-REVIEW.md'):
        out.write(ROOT/'packaging'/name, name)
source_digest = hashlib.file_digest(source_zip.open('rb'), 'sha256').hexdigest()
(ROOT/'dist/SHA256SUMS.txt').write_text(f'{digest}  {archive.name}\n{source_digest}  {source_zip.name}\n',encoding='ascii')
print(f'{archive}: {archive.stat().st_size} bytes; SHA256 {digest}')
print(f'{source_zip}: {source_zip.stat().st_size} bytes; SHA256 {source_digest}')
