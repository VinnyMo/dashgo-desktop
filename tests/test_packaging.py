import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from dashcam_paths import data_root, python_executable


class PortablePaths(unittest.TestCase):
    def test_frozen_paths_use_executable_not_unpack_or_current_directory(self):
        exe = str(Path('private-review/DashGo.exe').resolve())
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', exe):
            self.assertEqual(data_root(Path('unpack')), Path(exe).parent/'Data')
            self.assertEqual(python_executable(), str(Path(exe).with_name('DashGoWorker.exe')))

    def test_source_uses_current_interpreter(self):
        self.assertEqual(python_executable(), sys.executable)
