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

    def test_frozen_media_tools_never_fall_back_to_host_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root/'ffmpeg/bin'
            folder.mkdir(parents=True)
            with patch.object(sys, 'frozen', True, create=True), patch('dashcam_stitch.__file__', str(root/'dashcam_stitch.py')), patch('dashcam_stitch.shutil.which', side_effect=AssertionError('host lookup')):
                with self.assertRaisesRegex(RuntimeError, 'complete DashGo ZIP'):
                    find_ffmpeg(None)
                (folder/'ffmpeg.exe').touch()
                (folder/'ffprobe.exe').touch()
                self.assertEqual(find_ffmpeg(None), str(folder/'ffmpeg.exe'))
