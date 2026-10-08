"""Disposable command trees only; no camera, FFmpeg or user media."""
import ctypes
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from dashcam_jobs import OwnedCommand


class OwnedJobs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def command(self, code):
        job = OwnedCommand([sys.executable, '-u', '-c', code])
        self.addCleanup(job.close)
        return job

    def line(self, job):
        result = queue.Queue()
        thread = threading.Thread(target=lambda: result.put(job.process.stdout.readline()), daemon=True)
        thread.start()
        return result.get(timeout=8)

    def child_handle(self, pid):
        from ctypes import wintypes as wt
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]; api.OpenProcess.restype = wt.HANDLE
        api.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]; api.WaitForSingleObject.restype = wt.DWORD
        api.CloseHandle.argtypes = [wt.HANDLE]; api.CloseHandle.restype = wt.BOOL
        handle = api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE, our fixture child only.
        self.assertTrue(handle)
        self.addCleanup(api.CloseHandle, handle)
        return api, handle

    def test_output_and_exit_status(self):
        job = self.command("import sys; print('fixture output'); print('fixture error',file=sys.stderr); sys.exit(7)")
        self.assertEqual(self.line(job).strip(), 'fixture output')
        self.assertEqual(self.line(job).strip(), 'fixture error')
        self.assertEqual(job.wait(timeout=8), 7)
        self.assertEqual(job.poll(), 7)
        self.assertEqual(self.line(job), '')
        job.close(); job.close()

    def test_cancel_does_not_touch_another_owned_tree(self):
        first = self.command("import time; print('first',flush=True); time.sleep(60)")
        second = self.command("import time; print('second',flush=True); time.sleep(60)")
        self.assertEqual(self.line(first).strip(), 'first')
        self.assertEqual(self.line(second).strip(), 'second')
        first.cancel(); first.wait(timeout=8)
        self.assertIsNone(second.poll())
        second.cancel(); second.wait(timeout=8)

    @unittest.skipUnless(os.name == 'nt', 'Windows job tree integration')
    def test_cancel_kills_owned_child_and_releases_stdout(self):
        job = self.command("import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],creationflags=subprocess.CREATE_NO_WINDOW); print(p.pid,flush=True); time.sleep(60)")
        api, handle = self.child_handle(int(self.line(job)))
        job.cancel(); job.wait(timeout=8)
        self.assertEqual(api.WaitForSingleObject(handle, 5000), 0)
        self.assertEqual(self.line(job), '')

    @unittest.skipUnless(os.name == 'nt', 'Windows job tree integration')
    def test_normal_parent_exit_kills_orphan_without_wait_or_close(self):
        gate = self.root/'finish'
        code = ("import subprocess,sys,time; from pathlib import Path; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],creationflags=subprocess.CREATE_NO_WINDOW); "
                "print(p.pid,flush=True)\n"
                f"while not Path({str(gate)!r}).exists(): time.sleep(.01)\n")
        job = self.command(code)
        api, handle = self.child_handle(int(self.line(job)))
        gate.write_text('finish disposable parent')
        # No explicit job.wait/close: watcher must close tree while caller reads.
        self.assertEqual(self.line(job), '')
        self.assertEqual(api.WaitForSingleObject(handle, 5000), 0)
        self.assertEqual(job.wait(timeout=8), 0)

    @unittest.skipUnless(os.name == 'nt', 'Windows assignment guard')
    def test_failed_assignment_never_starts_command(self):
        marker = self.root/'must-not-exist'
        with patch('dashcam_jobs._WindowsJob.assign', side_effect=OSError('Fixture assignment denied')):
            with self.assertRaises(OSError):
                self.command(f'from pathlib import Path; Path({str(marker)!r}).write_text("started")')
        self.assertFalse(marker.exists())

    def test_bootstrap_eof_without_go_does_not_run_command(self):
        marker = self.root/'must-not-exist'
        worker = Path(__file__).resolve().parents[1]/'dashcam_worker.py'
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        result = subprocess.run([sys.executable, '-B', str(worker), sys.executable, '-c',
            f'from pathlib import Path; Path({str(marker)!r}).write_text("started")'],
            input=b'', capture_output=True, timeout=8, **options)
        self.assertEqual(result.returncode, 125)
        self.assertFalse(marker.exists())


if __name__ == '__main__': unittest.main()
