"""Stable media paths for flat development and organized installations."""
from pathlib import Path
import sys


def data_root(app_dir: Path) -> Path:
    app_dir = Path(app_dir).resolve()
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / 'Data'
    return app_dir.parent if (app_dir / '.installed-layout').is_file() else app_dir


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = data_root(APP_DIR)


def python_executable():
    """The packaged console helper preserves pipe/worker semantics."""
    if getattr(sys, 'frozen', False):
        return str(Path(sys.executable).with_name('DashGoWorker.exe'))
    return sys.executable
