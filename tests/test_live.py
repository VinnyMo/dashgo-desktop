import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dashcam_live import CaptureSession, RESERVE_BYTES, enable_live_stream, inspect_stream, read_capabilities, summarize_probe, validate_stream
from dashcam_history import DownloadHistory
from dashcam_stitch import scan_clips, group_drives
import datetime as dt


class FakeProcess:
    def __init__(self):
        self.stdin = io.BytesIO()
        self.code = None
    def poll(self):
        return self.code
    def wait(self, timeout=None):
        self.code = 0
        return 0
    def terminate(self):
        self.code = -1


class StreamTests(unittest.TestCase):
    def test_activation_refuses_unknown_firmware_without_command(self):
        with patch("dashcam_live.read_capabilities", return_value={"firmware": "unknown"}), patch("dashcam_live.get_json") as get:
            with self.assertRaises(RuntimeError):
                enable_live_stream("http://camera")
            get.assert_not_called()

    def test_malformed_audio_falls_back_to_video_without_setting_writes(self):
        data = {"streams": [{"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720}]}
        results = [SimpleNamespace(returncode=1), SimpleNamespace(returncode=0),
                   SimpleNamespace(returncode=0, stdout=json.dumps(data).encode())]
        with patch("dashcam_live.media_tool", side_effect=lambda name: name), \
             patch("dashcam_live.subprocess.run", side_effect=results) as run, patch("dashcam_live.get_json") as get:
            report = inspect_stream("rtsp://camera")
        self.assertIn("video-only", report["audio_note"])
        self.assertIn("-an", run.call_args_list[1].args[0])
        get.assert_not_called()

    def test_reject_command_and_credential_urls(self):
        for url in ("file:///x", "http://a/app/enterrecorder", "rtsp://u:p@a", "-i x", "http://a/x y"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_stream(url)

    def test_measurement_uses_packets_not_resolution_assumptions(self):
        report = summarize_probe({"streams": [{"index": 0, "codec_type": "video", "codec_name": "h264",
                                               "width": 1280, "height": 720, "avg_frame_rate": "30000/1001"}],
                                  "packets": [{"stream_index": 0, "pts_time": "0", "size": "1000"},
                                              {"stream_index": 0, "pts_time": "1", "size": "1000"}]})
        stream = report["streams"][0]
        self.assertEqual(stream["sample_bitrate_bps"], 16000)
        self.assertAlmostEqual(stream["fps"], 29.97002997)
        self.assertEqual(stream["height"], 720)

    def test_missing_rate_is_not_fabricated(self):
        stream = summarize_probe({"streams": [{"codec_type": "video", "avg_frame_rate": "0/0"}]})["streams"][0]
        self.assertIsNone(stream["fps"])
        self.assertIsNone(stream["sample_bitrate_bps"])

    def test_reject_audio_only(self):
        with self.assertRaises(RuntimeError):
            summarize_probe({"streams": [{"codec_type": "audio"}]})

    def test_device_discovery_is_only_reads(self):
        responses = [{"result": 0, "info": {"softver": "test", "camnum": 2}},
                     {"result": 0, "info": {"rtsp": "rtsp://camera", "port": 5000}},
                     {"result": 0, "info": []}, {"result": 0, "info": []}]
        with patch("dashcam_live.get_json", side_effect=responses) as get:
            result = read_capabilities("http://camera")
        self.assertEqual(result["media"]["rtsp"], "rtsp://camera")
        self.assertEqual(result["camera_controls"], "Unverified")
        self.assertTrue(all("/app/get" in call.args[0] for call in get.call_args_list))

    def test_low_disk_prevents_process_start(self):
        with tempfile.TemporaryDirectory() as tmp, patch("dashcam_live.media_tool", return_value="ffmpeg"), \
             patch("dashcam_live.shutil.disk_usage", return_value=SimpleNamespace(free=0)), \
             patch("dashcam_live.subprocess.Popen") as process:
            with self.assertRaises(RuntimeError):
                CaptureSession("rtsp://camera", Path(tmp), {}).start()
            process.assert_not_called()

    def test_manifest_failure_after_spawn_cleans_up_process(self):
        process = FakeProcess()
        with tempfile.TemporaryDirectory() as tmp, patch("dashcam_live.media_tool", return_value="ffmpeg"), \
             patch("dashcam_live.subprocess.Popen", return_value=process), \
             patch.object(CaptureSession, "_manifest", side_effect=[None, OSError("disk full"), OSError("disk full")]):
            session = CaptureSession("rtsp://camera", Path(tmp), {})
            with self.assertRaises(OSError):
                session.start()
            self.assertIsNotNone(process.poll())
            self.assertFalse(session.active)
            self.assertTrue(process.stdin.closed)

    def test_unique_sessions_stop_and_private_manifest(self):
        with tempfile.TemporaryDirectory() as tmp, patch("dashcam_live.media_tool", return_value="ffmpeg"), \
             patch("dashcam_live.subprocess.Popen", side_effect=lambda *a, **kw: FakeProcess()) as popen:
            sessions = [CaptureSession("rtsp://camera/live?private=hidden", Path(tmp), {}) for _ in range(2)]
            for session in sessions:
                session.start()
                session.stop()
                session.wait()
                self.assertEqual(session.state, "stopped")
                manifest = (session.directory / "session.json").read_text()
                self.assertNotIn("hidden", manifest)
                self.assertNotIn("rtsp", manifest)
            self.assertNotEqual(sessions[0].directory, sessions[1].directory)
            command = popen.call_args.args[0]
            self.assertIn("-n", command)
            self.assertIn("copy", command)
            self.assertNotIn("-y", command)
            self.assertIn("-an", command)

    def test_disk_full_during_recording_stops_owned_process(self):
        with tempfile.TemporaryDirectory() as tmp, patch("dashcam_live.media_tool", return_value="ffmpeg"), \
             patch("dashcam_live.subprocess.Popen", return_value=FakeProcess()), \
             patch("dashcam_live.shutil.disk_usage", side_effect=[SimpleNamespace(free=RESERVE_BYTES*2), SimpleNamespace(free=0)]):
            session = CaptureSession("rtsp://camera", Path(tmp), {})
            session.start()
            session.wait(3)
            self.assertEqual(session.state, "interrupted")
            self.assertIn("512 MiB", session.reason)
            self.assertTrue((session.directory / "session.json").is_file())

    def test_disconnect_keeps_segments(self):
        process = FakeProcess()
        process.code = 1
        with tempfile.TemporaryDirectory() as tmp, patch("dashcam_live.media_tool", return_value="ffmpeg"), \
             patch("dashcam_live.subprocess.Popen", return_value=process):
            session = CaptureSession("rtsp://camera", Path(tmp), {})
            session.start()
            session.wait()
            self.assertEqual(session.state, "interrupted")
            self.assertIn("Stream ended", session.reason)


class TransferRegressionTests(unittest.TestCase):
    def test_local_deletion_does_not_erase_download_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "2026-01-01_10_00_00_f.ts"
            (root / name).write_bytes(b"test")
            with DownloadHistory(root / "history.sqlite3") as history:
                self.assertEqual(history.import_local_sources(root), 1)
                (root / name).unlink()
                history.reconcile(root)
                self.assertTrue(history.was_downloaded("/mnt/card/video_front/" + name))
                self.assertEqual(history.stats(), (1, 0, 1))

    def test_live_segments_do_not_enter_legacy_drive_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("2026-01-01_10_00_00_f.ts", "2026-01-01_10_01_00_f.ts", "part_000001.mkv"):
                (root/name).write_bytes(b"test")
            self.assertEqual(len(scan_clips(root)), 2)
            self.assertEqual(len(group_drives(scan_clips(root), dt.timedelta(minutes=5))), 1)


if __name__ == "__main__":
    unittest.main()
