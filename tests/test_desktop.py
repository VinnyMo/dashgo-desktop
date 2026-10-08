"""Offline controller lifecycle checks; never starts a camera or media process."""
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dashcam_desktop import Desktop, inventory
from dashcam_connect import CameraConnection


class DesktopLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.desktop = Desktop(data_dir=Path(self.temp.name), auto_connect=False)

    def test_constructor_is_offline_and_idle(self):
        self.assertFalse(self.desktop.media_busy)
        self.assertIsNone(self.desktop.preview)
        self.assertIsNone(self.desktop.retry_at)
        self.assertFalse(list(Path(self.temp.name).iterdir()))

    def test_capture_and_transfer_reject_competing_jobs(self):
        self.desktop.operation = 'studio'
        with self.assertRaises(RuntimeError): self.desktop.start_capture()
        with self.assertRaises(RuntimeError): self.desktop.transfer()
        with self.assertRaises(RuntimeError): self.desktop.connect()

    def test_cancel_connection_discards_queued_success(self):
        self.desktop.operation = 'connection'
        self.desktop.connection = CameraConnection()
        self.desktop.events.put(('result', 'connection', {
            'address':'http://192.0.2.1', 'url':'rtsp://192.0.2.1',
            'report':{'streams':[]}, 'capabilities':{}}))
        self.desktop.cancel_connection()
        self.desktop.poll()
        self.assertIsNone(self.desktop.report, 'Cancelled connection result must not reopen preview')

    def test_queued_export_keeps_selected_target_and_cancel_keeps_rendering(self):
        session = Path(self.temp.name)/'Capture_fixture'
        renderer = SimpleNamespace(active=True, capture=SimpleNamespace(directory=session))
        self.desktop.renderer = renderer
        self.desktop.target = '1gbh'
        self.desktop.export_capture(session)
        self.assertEqual(self.desktop.pending_export, (session, '1gbh'))
        self.desktop.target = 'original'
        self.desktop.cancel_export()
        self.assertIsNone(self.desktop.pending_export)
        self.assertTrue(renderer.active)

    def test_orphan_final_stays_visible_in_inventory(self):
        final = self.desktop.capture_dir/'Exports'/'Capture_fixture'/'Finalized_fixture'/'Capture.mp4'
        final.parent.mkdir(parents=True); final.write_bytes(b'disposable final')
        rows = inventory(self.desktop)
        self.assertEqual([r['path'] for r in rows], [final])
        self.assertEqual(final.read_bytes(), b'disposable final')

    def test_close_stops_capture_that_is_still_starting(self):
        entered, release = threading.Event(), threading.Event()
        capture = SimpleNamespace(active=False, directory=Path(self.temp.name)/'Capture_fixture')
        stopped = threading.Event()
        def start():
            entered.set()
            if not release.wait(2): raise TimeoutError('Fixture was not released')
            capture.active = True
        def stop():
            stopped.set(); capture.active = False
        capture.start = start; capture.stop = stop; capture.wait = Mock()
        self.desktop.report = {'streams': []}
        with patch('dashcam_desktop.CaptureSession', return_value=capture):
            self.desktop.start_capture()
            self.assertTrue(entered.wait(2))
            timer = threading.Timer(.05, release.set); timer.start()
            try:
                self.desktop.close()
            finally:
                release.set(); timer.join(2)
                for worker in self.desktop._workers: worker.join(2)
        self.assertTrue(stopped.is_set(), 'A capture started during close must be stopped')

    def test_stop_during_capture_start_is_not_lost(self):
        entered, release = threading.Event(), threading.Event()
        capture = SimpleNamespace(active=False, directory=Path(self.temp.name)/'Capture_fixture')
        stopped = threading.Event()
        def start():
            entered.set()
            if not release.wait(2): raise TimeoutError('Fixture was not released')
            capture.active = not stopped.is_set()
        capture.start = start; capture.stop = stopped.set; capture.wait = Mock()
        self.desktop.report = {'streams': []}
        with patch('dashcam_desktop.CaptureSession', return_value=capture):
            self.desktop.start_capture()
            self.assertTrue(entered.wait(2))
            self.desktop.stop_capture()
            release.set()
            for worker in self.desktop._workers: worker.join(2)
        self.assertTrue(stopped.is_set(), 'Stop during startup must reach the starting capture')

    def test_poll_does_not_discard_a_starting_capture(self):
        capture=SimpleNamespace(active=False)
        self.desktop.capture=capture;self.desktop.operation='capture_start'
        renderer=SimpleNamespace(active=False)
        self.desktop.renderer=renderer
        self.desktop.poll()
        self.assertIs(self.desktop.capture,capture)
        self.assertIs(self.desktop.renderer,renderer)
        self.desktop.capture=None;self.desktop.renderer=None;self.desktop.operation=''

    def test_partial_drive_is_listed_once_as_partial(self):
        directory=self.desktop.transfer_dir/'Drives';directory.mkdir(parents=True)
        partial=directory/'Drive_2026-10-08_11-00-00.mp4.part.mp4';partial.write_bytes(b'fixture')
        (directory.parent/'2026-10-08_11_00_00_f.ts').write_bytes(b'fixture')
        rows=inventory(self.desktop)
        matches=[r for r in rows+[c for row in rows for c in row['children']] if r['path']==partial]
        self.assertEqual([r['kind'] for r in matches],['Partial render'])

    def test_render_status_distinguishes_work_from_completed_count(self):
        renderer=SimpleNamespace(active=True,state='preparing',completed=0)
        self.desktop.renderer=renderer
        for state,expected in [('preparing','Preparing music'),('waiting','Waiting for the next closed capture segment'),('rendering','Rendering segment 1')]:
            renderer.state=state;self.desktop.poll()
            self.assertEqual(self.desktop.studio_status,expected+' · 0 completed')
        count=len(self.desktop.logs);self.desktop.poll()
        self.assertEqual(len(self.desktop.logs),count,'Unchanged state should not flood logs')
        renderer.completed=1;self.desktop.poll()
        self.assertEqual(self.desktop.studio_status,'Rendering segment 2 · 1 completed')
        self.desktop.renderer=None


if __name__ == '__main__': unittest.main()
