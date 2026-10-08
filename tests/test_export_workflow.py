import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dashcam_cleanup import generated_inputs, recycle_inputs
from dashcam_finalize import CaptureFinalizer, verify_playback
from test_finalize import fixture


class CleanupSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.session = self.root / 'Capture_fixture'; self.session.mkdir()
        fixture(self.session)
        self.parts = sorted((self.session / 'Rendered').glob('part_*.mp4'))
        self.playlist = self.session / 'Rendered' / '.capture.shuffled_playlist.m4a'
        self.files, self.guards = generated_inputs(self.session, self.parts, self.playlist)
        self.final = self.root / 'Exports' / 'Capture.mp4'; self.final.parent.mkdir()
        self.final.write_bytes(b'verified final fixture')
        self.trash = self.root / 'FixtureTrash'; self.trash.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def recycle(self, path, validate):
        validate()
        path.rename(self.trash / str(len(list(self.trash.iterdir()))))

    def run_cleanup(self, **kwargs):
        return recycle_inputs(self.session, self.files, self.guards, self.final, recycle=kwargs.pop('recycle', self.recycle), **kwargs)

    def test_exact_generated_media_only_final_music_metadata_and_unrelated_stay(self):
        unrelated = self.session / 'keep.mp4'; unrelated.write_bytes(b'keep')
        music = self.root / 'song.mp3'; music.write_bytes(b'original music')
        record = self.session / 'Rendered' / 'render.json'
        data = json.loads(record.read_text()); data['playlist_order'] = [str(music)]
        record.write_text(json.dumps(data))
        self.files, self.guards = generated_inputs(self.session, self.parts, self.playlist)
        result = self.run_cleanup()
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(len(result['recycled']), 5)
        self.assertTrue(self.final.exists()); self.assertTrue(record.exists())
        self.assertEqual(unrelated.read_bytes(), b'keep')
        self.assertEqual(music.read_bytes(), b'original music')

    def test_recycling_unavailable_retains_every_input_and_final(self):
        with patch('dashcam_cleanup.recycle_windows', side_effect=OSError('No Recycle Bin')):
            result = self.run_cleanup(recycle=None)
        self.assertEqual(result['state'], 'incomplete')
        self.assertFalse(result['recycled'])
        self.assertTrue(all(p.exists() for p in self.files)); self.assertTrue(self.final.exists())

    def test_partial_failure_stops_and_audits_remaining_files(self):
        def recycle(path, validate):
            if len(list(self.trash.iterdir())) == 1:
                raise OSError('Locked file')
            self.recycle(path, validate)
        records = []
        result = self.run_cleanup(recycle=recycle, audit=lambda value: records.append(json.loads(json.dumps(value))))
        self.assertEqual(len(result['recycled']), 1)
        self.assertEqual(sum(p.exists() for p in self.files), 4)
        self.assertEqual(records[-1]['state'], 'incomplete'); self.assertTrue(self.final.exists())

    def test_cancel_and_modified_source_or_active_status_block_cleanup(self):
        result = self.run_cleanup(cancelled=lambda: True)
        self.assertFalse(result['recycled'])
        next(iter(self.files)).write_bytes(b'changed after export started')
        result = self.run_cleanup()
        self.assertFalse(result['recycled'])
        self.files, self.guards = generated_inputs(self.session, self.parts, self.playlist)
        (self.session / 'session.json').write_text('{"state":"recording"}')
        result = self.run_cleanup()
        self.assertFalse(result['recycled'])

    def test_final_changes_during_cleanup_veto_next_item(self):
        def recycle(path, validate):
            self.final.write_bytes(b'changed')
            validate()
        result = self.run_cleanup(recycle=recycle)
        self.assertFalse(result['recycled'])
        self.assertIn('Final export changed', result['reason'])

    def test_final_or_external_path_cannot_be_input(self):
        for paths in ([self.final], [self.session / 'session.json']):
            with self.assertRaises(ValueError):
                generated_inputs(self.session, paths, None)

    def test_link_replacement_between_plan_and_cleanup_is_rejected(self):
        path = next(iter(self.files))
        original = path.read_bytes(); path.unlink()
        try:
            os.link(self.final, path)
            result = self.run_cleanup()
            self.assertFalse(result['recycled']); self.assertTrue(self.final.exists())
        finally:
            path.unlink(missing_ok=True); path.write_bytes(original)

    def test_failed_validation_never_invokes_cleanup_and_preserves_good_export(self):
        with patch('dashcam_finalize.read_rendered_video', side_effect=RuntimeError('bad source')), patch('dashcam_finalize.recycle_inputs') as recycle:
            job = CaptureFinalizer(self.session, cleanup=True)
            job.start(); job.wait()
        self.assertEqual(job.state, 'failed'); recycle.assert_not_called()
        self.assertTrue(self.final.exists()); self.assertTrue(all(p.exists() for p in self.files))

    def test_another_export_lock_is_not_removed(self):
        lock = self.session / '.export.lock'; lock.write_text('another job')
        job = CaptureFinalizer(self.session, cleanup=True)
        job.start(); job.wait()
        self.assertEqual(job.state, 'failed'); self.assertEqual(lock.read_text(), 'another job')
        self.assertTrue(all(p.exists() for p in self.files))

    def test_progress_uses_media_timestamps_and_emits_milestones(self):
        import time
        job = CaptureFinalizer(self.session); job.started = time.monotonic() - 12
        path = self.root / 'progress.log'
        path.write_text('out_time_us=5000000\nspeed=2.0x\nprogress=continue\n')
        job._progress(path, 10)
        self.assertEqual(job.percent, 49)
        self.assertIn('2.0x', job.message)
        self.assertIn('49%', job.logs.get_nowait())


class ExportUI(unittest.TestCase):
    def setUp(self):
        from dashcam_gui import DashcamGUI
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.app = DashcamGUI(auto_connect=False)
        self.app.output.set(str(self.root / 'Transfers'))
        self.panel = self.app.camera_panel
        self.panel.destination.set(str(self.root / 'Captures'))
        self.session = self.root / 'Captures' / 'Capture_fixture'; self.session.mkdir(parents=True)
        fixture(self.session)
        self.app._refresh_drives()

    def tearDown(self):
        for widget in (self.panel, self.app):
            for command in list(widget._tclCommands or []):
                for callback in self.app.tk.splitlist(self.app.tk.call('after', 'info')):
                    if command in self.app.tk.call('after', 'info', callback):
                        widget.after_cancel(callback)
        self.app.destroy(); self.temp.cleanup()

    def test_child_selection_exports_session_and_no_selection_explains_action(self):
        self.app._convert()
        self.assertIn('Select', self.panel.export_status.get())
        child = self.app.drive_tree.get_children('capture-Capture_fixture')[0]
        self.app.drive_tree.selection_set(child)
        with patch.object(self.panel, 'finalize_path') as export:
            self.app._convert(); export.assert_called_once_with(self.session)

    def test_queue_cancel_and_drain_are_explicit_and_visible_in_studio(self):
        self.panel.renderer = SimpleNamespace(active=True, capture=SimpleNamespace(directory=self.session))
        self.panel.finalize_path(self.session)
        self.assertEqual(self.panel.pending_export, self.session)
        self.assertIn('queued', self.app.status.get())
        self.panel._cancel_finalize()
        self.assertIsNone(self.panel.pending_export)
        self.assertTrue(self.panel.renderer.active)
        self.panel.finalize_path(self.session)
        self.panel.renderer = None
        with patch('dashcam_camera_ui.CaptureFinalizer') as constructor:
            job = constructor.return_value; job.active = True
            self.panel._poll_once()
            constructor.assert_called_once()
            self.assertTrue(constructor.call_args.kwargs['cleanup'])
            self.assertEqual(constructor.call_args.kwargs['output_root'], self.session.parent/'Exports'/self.session.name)
            self.panel.finalize_path(self.session)
            constructor.assert_called_once()
        self.panel.finalizer = None

    def test_preview_allows_destination_but_active_jobs_do_not(self):
        self.panel.preview = SimpleNamespace()
        self.panel._controls()
        self.assertEqual(str(self.panel.browse['state']), 'normal')
        self.panel.capture = SimpleNamespace(active=True)
        self.panel._controls()
        self.assertEqual(str(self.panel.browse['state']), 'disabled')
        self.panel.preview = self.panel.capture = None

    def test_new_final_rows_cannot_enter_legacy_delete_or_reexport(self):
        final = self.session.parent/'Exports'/self.session.name/'Finalized_fixture'/'Capture.mp4'
        final.parent.mkdir(parents=True); final.write_bytes(b'final')
        self.app._refresh_drives(); self.app.drive_tree.selection_set('export-0')
        with patch('dashcam_gui.messagebox.showinfo') as info:
            self.app._delete_mp4s(); info.assert_called_once()
        self.assertEqual(final.read_bytes(), b'final')
        self.app._convert()
        self.assertIn('completed final', self.panel.export_status.get())

    def test_preview_reconnect_is_bounded_cancellable_and_never_starts_capture(self):
        self.app.auto_connect = True
        with patch.object(self.panel, '_record') as record, patch.object(self.panel, '_connect'):
            for attempt in range(3):
                self.panel._schedule_reconnect()
                self.assertEqual(self.panel.connection_retries, attempt + 1)
                self.assertIsNotNone(self.panel.reconnect_timer)
                self.panel._cancel_connect()
                self.assertIsNone(self.panel.reconnect_timer)
            self.panel._schedule_reconnect()
            self.assertIsNone(self.panel.reconnect_timer)
            self.assertIn('three retries', self.panel.state.get())
            record.assert_not_called()
        self.app.auto_connect = False

    def test_running_export_progress_and_error_are_visible_from_studio(self):
        import queue
        logs = queue.Queue(); logs.put('Encoding started')
        job = SimpleNamespace(active=True, percent=42, message='Exporting 42%', logs=logs)
        self.panel.finalizer = job
        self.app.tabs.select(self.app.drives_tab)
        self.panel._poll_once()
        self.assertEqual(self.panel.export_percent.get(), 42)
        self.assertEqual(self.app.status.get(), 'Exporting 42%')
        self.assertIn('Encoding started', self.app.log.get('1.0', 'end'))
        job.active=False; job.state='failed'; job.reason='Disk unavailable; sources retained'
        self.panel._poll_once()
        self.assertIn('Disk unavailable', self.panel.export_status.get())
        self.assertIn('Disk unavailable', self.app.status.get())
        self.assertIsNone(self.panel.finalizer)


@unittest.skipUnless(os.environ.get('DASHGO_MEDIA_TESTS') == '1', 'Generated FFmpeg integration')
class ExportFailureIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        from dashcam_live import media_tool
        cls.fixture_temp=tempfile.TemporaryDirectory()
        path=Path(cls.fixture_temp.name)/'source.mkv'
        subprocess.run([media_tool('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=25',
                        '-t','2','-c:v','libx264','-threads','2','-preset','ultrafast',str(path)],check=True,timeout=15)
        cls.source=path.read_bytes()

    @classmethod
    def tearDownClass(cls): cls.fixture_temp.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        self.session=self.root/'Capture_fixture';self.session.mkdir()
        (self.session/'session.json').write_text('{"state":"stopped"}')
        for index in range(2): (self.session/f'part_{index:06d}.mkv').write_bytes(self.source)
        self.good=self.root/'previous-final.mp4';self.good.write_bytes(b'untouched previous final fixture')

    def tearDown(self): self.temp.cleanup()

    def job(self): return CaptureFinalizer(self.session,raw_only=True,output_root=self.root/'Exports',cleanup=True)

    def assert_sources(self):
        self.assertTrue(all(p.read_bytes()==self.source for p in self.session.glob('part_*.mkv')))
        self.assertEqual(len(list(self.session.glob('part_*.mkv'))),2)
        self.assertEqual(self.good.read_bytes(),b'untouched previous final fixture')

    def test_verified_final_survives_cleanup_failure(self):
        with patch('dashcam_cleanup.recycle_windows',side_effect=OSError('Fixture Recycle Bin unavailable')):
            job=self.job();job.start();job.wait(20)
        self.assertEqual(job.state,'finished',job.reason)
        self.assertTrue(job.output.is_file());self.assertIn('cleanup incomplete',job.reason)
        self.assertEqual(job.cleanup_result['state'],'incomplete');self.assert_sources()

    def test_playback_validation_failure_retains_sources_and_partial(self):
        with patch('dashcam_finalize.verify_playback',side_effect=RuntimeError('Fixture playback failed')),patch('dashcam_finalize.recycle_inputs') as recycle:
            job=self.job();job.start();job.wait(20)
        self.assertEqual(job.state,'failed');recycle.assert_not_called()
        self.assertIsNone(job.output);self.assertTrue((job.directory/'Capture.partial.mp4').exists());self.assert_sources()

    def test_duration_validation_failure_never_recycles(self):
        from dashcam_finalize import read_rendered_video
        def probe(path,**kwargs):
            result=read_rendered_video(path,**kwargs)
            if path.name=='Capture.partial.mp4':result['duration']+=10
            return result
        with patch('dashcam_finalize.read_rendered_video',side_effect=probe),patch('dashcam_finalize.recycle_inputs') as recycle:
            job=self.job();job.start();job.wait(20)
        self.assertEqual(job.state,'failed');self.assertIn('duration',job.reason);recycle.assert_not_called();self.assert_sources()

    def test_cancelling_during_verification_preserves_sources(self):
        def cancel(path,duration,audio,stopped):stopped.set()
        with patch('dashcam_finalize.verify_playback',side_effect=cancel),patch('dashcam_finalize.recycle_inputs') as recycle:
            job=self.job();job.start();job.wait(20)
        self.assertEqual(job.state,'cancelled');recycle.assert_not_called();self.assert_sources()

    def test_cancelling_running_ffmpeg_stops_only_owned_job(self):
        import time
        import dashcam_process
        original=dashcam_process.Popen
        def slow(command,**kwargs):
            command=list(command);command.insert(command.index('-f'),'-re')
            return original(command,**kwargs)
        with patch('dashcam_finalize.subprocess.Popen',side_effect=slow),patch('dashcam_finalize.recycle_inputs') as recycle:
            job=self.job();job.start()
            deadline=time.monotonic()+10
            while job.state!='assembling' and job.active and time.monotonic()<deadline:time.sleep(.02)
            self.assertEqual(job.state,'assembling',job.reason)
            time.sleep(.3);job.stop();job.wait(10)
        self.assertEqual(job.state,'cancelled');self.assertIsNotNone(job.process.poll())
        recycle.assert_not_called();self.assert_sources()


if __name__ == '__main__':
    unittest.main()
