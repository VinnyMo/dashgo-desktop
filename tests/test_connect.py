import subprocess
import unittest
from unittest.mock import Mock, patch

from dashcam_connect import CameraConnection, ConnectionCancelled, FIRMWARE


class ConnectTests(unittest.TestCase):
    def test_rediscovery_uses_current_gateway_and_ignores_other_firmware(self):
        responses = [{'result': 0, 'info': {'softver': 'other-camera', 'camnum': 1}},
                     {'result': 0, 'info': {'softver': FIRMWARE, 'camnum': 2}}]
        with patch('dashcam_connect.gateway_candidates', return_value=['192.168.8.1', '192.168.9.1']), patch('dashcam_connect.get_json', side_effect=responses):
            found = CameraConnection().discover()
        self.assertEqual(found, [{'address': 'http://192.168.9.1', 'firmware': FIRMWARE}])

    def test_route_failure_preserves_known_factory_fallback(self):
        from dashcam_downloader import gateway_candidates
        with patch('dashcam_downloader.subprocess.run', side_effect=subprocess.TimeoutExpired('route', 10)):
            self.assertEqual(gateway_candidates(), ['192.168.169.1'])

    def test_capture_retry_budget_resets_only_after_sustained_output(self):
        from pathlib import Path
        from dashcam_live import CaptureSession
        job = CaptureSession('rtsp://camera', Path('.'), {}, reconnect_attempts=3)
        job.retry_streak = 3; job.reconnects = 7
        job._record_growth(100); job._record_growth(110)
        self.assertEqual(job.retry_streak, 3)
        job._record_growth(130)
        self.assertEqual(job.retry_streak, 0); self.assertEqual(job.reconnects, 7)
        job.retry_streak = 1; job._healthy_since = None
        job._record_growth(200)
        self.assertEqual(job.retry_streak, 1)

    def test_constructor_does_not_discover(self):
        with patch('dashcam_connect.gateway_candidates') as gateways:
            CameraConnection()
            gateways.assert_not_called()

    def test_multiple_candidates_require_selection_without_activation(self):
        response = {'result': 0, 'info': {'softver': FIRMWARE, 'camnum': 2}}
        with patch('dashcam_connect.gateway_candidates', return_value=['192.168.1.1', '192.168.2.1', '192.168.1.1']), patch('dashcam_connect.get_json', return_value=response) as get:
            result = CameraConnection().run()
        self.assertEqual(len(result['candidates']), 2)
        self.assertTrue(all(call.args[0].endswith('/app/getdeviceattr') for call in get.call_args_list))

    def test_connect_orders_identity_activation_measurement(self):
        calls = []
        caps = {'firmware': FIRMWARE, 'media': {'rtsp': 'rtsp://192.168.1.1'}}
        with patch('dashcam_connect.read_capabilities', side_effect=lambda *a, **k: calls.append('identify') or caps), patch('dashcam_connect.get_json', side_effect=lambda url, **k: calls.append(url.split('/')[-1]) or {'result': 0}), patch('dashcam_connect.inspect_stream', side_effect=lambda *a, **k: calls.append('measure') or {'streams': []}):
            result = CameraConnection().run('http://192.168.1.1')
        self.assertEqual(calls, ['identify', 'enterrecorder', 'measure'])
        self.assertEqual(result['url'], 'rtsp://192.168.1.1')

    def test_unknown_firmware_and_external_stream_never_activate(self):
        for caps in ({'firmware': 'unknown'}, {'firmware': FIRMWARE, 'media': {'rtsp': 'rtsp://other-host'}}):
            with patch('dashcam_connect.read_capabilities', return_value=caps), patch('dashcam_connect.get_json') as get:
                with self.assertRaises(RuntimeError):
                    CameraConnection().run('http://192.168.1.1')
                get.assert_not_called()

    def test_cancel_before_and_after_identity_prevents_activation(self):
        job = CameraConnection()
        job.cancel()
        with patch('dashcam_connect.gateway_candidates') as gateways:
            with self.assertRaises(ConnectionCancelled):
                job.run()
            gateways.assert_not_called()
        job = CameraConnection()
        def identify(*args, **kwargs):
            job.cancel()
            return {'firmware': FIRMWARE, 'media': {'rtsp': 'rtsp://camera'}}
        with patch('dashcam_connect.read_capabilities', side_effect=identify), patch('dashcam_connect.get_json') as get:
            with self.assertRaises(ConnectionCancelled):
                job.run('http://camera')
            get.assert_not_called()

    def test_cancel_during_probe_stops_owned_process(self):
        job = CameraConnection()
        process = Mock()
        process.poll.return_value = None
        def communicate(**kwargs):
            if kwargs:
                job.cancel()
                raise subprocess.TimeoutExpired('probe', 0.1)
            return b'', b''
        process.communicate.side_effect = communicate
        with patch('dashcam_connect.subprocess.Popen', return_value=process):
            with self.assertRaises(ConnectionCancelled):
                job.run_process(['probe'], capture_output=True, timeout=20)
        process.kill.assert_called_once()

    def test_absent_camera_is_retryable_without_activation(self):
        with patch('dashcam_connect.gateway_candidates', return_value=['192.168.1.1']), patch('dashcam_connect.get_json', side_effect=OSError), patch('dashcam_connect.inspect_stream') as probe:
            with self.assertRaisesRegex(RuntimeError, 'No camera found'):
                CameraConnection().run()
            probe.assert_not_called()


class ConnectUI(unittest.TestCase):
    def test_connected_and_multiple_camera_states(self):
        import tkinter as tk
        from types import SimpleNamespace
        from dashcam_camera_ui import CameraPanel
        root = tk.Tk()
        root.withdraw()
        try:
            app = SimpleNamespace(camera=tk.StringVar(), process=None, task_running=False)
            with patch('dashcam_connect.gateway_candidates') as gateways:
                panel = CameraPanel(root, app)
                gateways.assert_not_called()
            self.assertEqual(str(panel.record['state']), 'disabled')
            self.assertEqual(panel.advanced.state(), "withdrawn")
            panel.events.put(('connected', {'candidates': [{'address': 'http://camera', 'firmware': FIRMWARE}, {'address': 'http://other', 'firmware': FIRMWARE}]}))
            panel._poll()
            self.assertEqual(panel.candidate_picker.current(), -1)
            self.assertEqual(str(panel.record['state']), 'disabled')
            report = {'streams': [{'type': 'video', 'width': 1280, 'height': 720, 'codec': 'h264', 'fps': 25, 'sample_bitrate_bps': 3000000}]}
            result = {'address': 'http://camera', 'url': 'rtsp://camera', 'capabilities': {'firmware': FIRMWARE, 'cameras': 2, 'media': {'rtsp': 'rtsp://camera'}}, 'report': report}
            panel.events.put(('connected', result))
            panel._poll()
            self.assertEqual(str(panel.record['state']), 'normal')
            self.assertEqual(str(panel.play['state']), 'normal')
            self.assertEqual(app.camera.get(), 'http://camera')
            panel.report = panel.report_url = None
            panel.connection = CameraConnection()
            panel.connection.cancel()
            panel.events.put(('connected', result))
            panel._poll()
            self.assertEqual(str(panel.record['state']), 'disabled')
            self.assertIn('cancelled', panel.state.get())
        finally:
            for callback in root.tk.splitlist(root.tk.call("after", "info")):
                panel.after_cancel(callback)
            root.destroy()
