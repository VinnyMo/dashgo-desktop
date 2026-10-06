import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from dashcam_paths import data_root
from dashcam_power import KeepAwake, ES_CONTINUOUS, ES_SYSTEM_REQUIRED


class PowerTests(unittest.TestCase):
    def test_overlapping_jobs_hold_one_request_until_last_finishes(self):
        setter = Mock(return_value=ES_CONTINUOUS)
        power = KeepAwake(setter)
        for reasons in ({'capture'}, {'capture', 'render'}, {'render'}, {'render', 'export'}, {'export'}, set()):
            power.update(reasons)
        self.assertEqual([call.args[0] for call in setter.call_args_list],
                         [ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS])
        self.assertFalse(power.active)
        power.close()
        self.assertEqual(setter.call_count, 2)

    def test_failure_does_not_claim_active_and_can_retry(self):
        setter = Mock(side_effect=[0, ES_CONTINUOUS, 0, ES_CONTINUOUS])
        power = KeepAwake(setter)
        with self.assertRaises(OSError): power.update({'capture'})
        self.assertFalse(power.active)
        power.update({'capture'})
        with self.assertRaises(OSError): power.close()
        self.assertTrue(power.active)
        power.close()
        self.assertFalse(power.active)

    def test_wrong_thread_cannot_clear_request(self):
        power = KeepAwake(Mock(return_value=ES_CONTINUOUS))
        power.update({'capture'})
        errors = []
        def other_thread():
            try: power.close()
            except RuntimeError as exc: errors.append(str(exc))
        worker = threading.Thread(target=other_thread)
        worker.start(); worker.join()
        self.assertTrue(errors)
        self.assertTrue(power.active)
        power.close()

    def test_gui_ignores_idle_preview_and_transfer_and_releases_on_destroy(self):
        from dashcam_gui import DashcamGUI
        app = DashcamGUI(auto_connect=False)
        setter = Mock(return_value=ES_CONTINUOUS)
        app.keep_awake = KeepAwake(setter)
        try:
            app.task_running = True  # A transfer alone does not inhibit sleep.
            app.camera_panel.preview = object()
            app._sync_awake()
            setter.assert_not_called()
            capture = SimpleNamespace(active=True)
            renderer = SimpleNamespace(active=True)
            app.camera_panel.capture = capture
            app.camera_panel.renderer = renderer
            app._sync_awake()
            capture.active = False
            app._sync_awake()
            self.assertTrue(app.keep_awake.active)
            renderer.active = False
            app.task_keeps_awake = True
            app._sync_awake()
            self.assertTrue(app.keep_awake.active)
            app.task_running = False
            app._sync_awake()
            self.assertFalse(app.keep_awake.active)
            app.camera_panel.finalizer = SimpleNamespace(active=True)
            app._sync_awake()
        finally:
            for widget in (app.camera_panel, app):
                for command in list(widget._tclCommands or []):
                    for callback in app.tk.splitlist(app.tk.call('after', 'info')):
                        if command in app.tk.call('after', 'info', callback):
                            widget.after_cancel(callback)
            app.destroy()
        self.assertFalse(app.keep_awake.active)
        self.assertEqual(setter.call_args.args[0], ES_CONTINUOUS)


class PathTests(unittest.TestCase):
    def test_flat_checkout_and_installed_layout_keep_media_at_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            app = root / 'App'; app.mkdir()
            self.assertEqual(data_root(root), root)
            self.assertEqual(data_root(app), app)
            (app / '.installed-layout').write_text('1')
            self.assertEqual(data_root(app), root)
