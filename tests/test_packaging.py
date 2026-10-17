import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from dashcam_paths import data_root, python_executable
from dashcam_stitch import find_ffmpeg


class PortablePaths(unittest.TestCase):
    def test_frozen_paths_use_executable_not_unpack_or_current_directory(self):
        exe = str(Path('private-review/DashGo.exe').resolve())
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', exe):
            self.assertEqual(data_root(Path('unpack')), Path(exe).parent/'Data')
            self.assertEqual(python_executable(), str(Path(exe).with_name('DashGoWorker.exe')))

    def test_source_uses_current_interpreter(self):
        self.assertEqual(python_executable(), sys.executable)

    def test_frozen_media_tools_use_external_path(self):
        with patch.object(sys, 'frozen', True, create=True), patch('dashcam_stitch.shutil.which', return_value='external/ffmpeg.exe'):
            self.assertEqual(find_ffmpeg(None), 'external/ffmpeg.exe')

    def test_explicit_ffmpeg_precedes_path(self):
        with tempfile.TemporaryDirectory() as temp:
            exe = Path(temp)/'ffmpeg.exe'
            exe.touch()
            with patch('dashcam_stitch.shutil.which', side_effect=AssertionError('unexpected PATH lookup')):
                self.assertEqual(find_ffmpeg(exe), str(exe))

    def test_missing_ffmpeg_explains_prerequisite(self):
        with tempfile.TemporaryDirectory() as temp, patch('dashcam_stitch.shutil.which', return_value=None), patch('dashcam_stitch.Path.home', return_value=Path(temp)):
            with self.assertRaisesRegex(RuntimeError, 'winget install --id Gyan.FFmpeg --exact'):
                find_ffmpeg(None)

    def test_winget_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root/'AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_test/ffmpeg-test/bin'
            folder.mkdir(parents=True)
            (folder/'ffmpeg.exe').touch()
            with patch('dashcam_stitch.shutil.which', return_value=None), patch('dashcam_stitch.Path.home', return_value=root):
                self.assertEqual(find_ffmpeg(None), str(folder/'ffmpeg.exe'))
