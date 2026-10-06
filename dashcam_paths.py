"""Stable media paths for flat development and organized installations."""
from pathlib import Path


def data_root(app_dir: Path) -> Path:
    app_dir = Path(app_dir).resolve()
    return app_dir.parent if (app_dir / '.installed-layout').is_file() else app_dir


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = data_root(APP_DIR)
