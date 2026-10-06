import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dashcam_recycle import plan_recycle, recycle_plan, _RecycleSink


def fixture(root, name='Capture_fixture'):
    session = root / name
    session.mkdir(parents=True)
    (session / 'session.json').write_text(json.dumps({'state': 'stopped'}))
    (session / 'part_000000.mkv').write_bytes(b'generated raw fixture')
    rendered = session / 'Rendered'; rendered.mkdir()
    (rendered / 'render.json').write_text(json.dumps({'state': 'finished'}))
    (rendered / 'part_000000.mp4').write_bytes(b'generated rendered fixture')
    final = session / 'Finalized_fixture'; final.mkdir()
    (final / 'Capture.mp4').write_bytes(b'generated final fixture')
    return session


class RecycleSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / 'Captures'; self.root.mkdir()
        self.session = fixture(self.root)
        self.trash = self.root.parent / 'FixtureTrash'; self.trash.mkdir()
    def tearDown(self): self.temp.cleanup()
    def recycle(self, path, validate):
        validate()
        path.rename(self.trash / str(len(list(self.trash.iterdir()))))

    def test_whole_session_deduplicates_children_and_ignores_manifest_references(self):
        outside = self.root.parent / 'unrelated.mp4'; outside.write_bytes(b'untouched')
        (self.session/'session.json').write_text(json.dumps({'state':'stopped','output':str(outside)}))
        items = plan_recycle(self.root, [self.session, self.session/'part_000000.mkv', self.session])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].file_count, 5)
        moved, errors = recycle_plan(self.root, items, is_busy=lambda:False, recycle=self.recycle)
        self.assertEqual(moved, [self.session]); self.assertFalse(errors)
        self.assertEqual(outside.read_bytes(), b'untouched')

    def test_individual_raw_rendered_and_final_leave_session_records(self):
        paths = [self.session/'part_000000.mkv',self.session/'Rendered'/'part_000000.mp4',self.session/'Finalized_fixture'/'Capture.mp4']
        items = plan_recycle(self.root, paths)
        moved, errors = recycle_plan(self.root, items, is_busy=lambda:False, recycle=self.recycle)
        self.assertEqual(len(moved),3); self.assertFalse(errors)
        self.assertTrue((self.session/'session.json').exists())
        self.assertTrue((self.session/'Rendered'/'render.json').exists())

    def test_traversal_outside_and_library_parent_rejected(self):
        for path in (self.root,self.root.parent,self.session/'..'/self.session.name):
            with self.subTest(path=path), self.assertRaises(ValueError):plan_recycle(self.root,[path])

    def test_active_session_render_or_export_blocks_parent(self):
        for record in (self.session/'session.json', self.session/'Rendered'/'render.json', self.session/'Finalized_fixture'/'finalize.json'):
            original=record.read_bytes() if record.exists() else None
            record.write_text(json.dumps({'state':'recording'}))
            with self.assertRaises(ValueError):plan_recycle(self.root,[self.session])
            if original is None:record.unlink()
            else:record.write_bytes(original)

    def test_selection_changes_or_jobs_start_after_confirmation_are_rejected(self):
        items=plan_recycle(self.root,[self.session])
        with self.assertRaises(ValueError):recycle_plan(self.root,items,is_busy=lambda:True,recycle=self.recycle)
        (self.session/'new.txt').write_text('new file')
        with self.assertRaises(ValueError):recycle_plan(self.root,items,is_busy=lambda:False,recycle=self.recycle)
        self.assertTrue(self.session.exists())

    def test_failure_stops_batch_and_reports_prior_success(self):
        second=fixture(self.root,'Capture_second');third=fixture(self.root,'Capture_third')
        items=plan_recycle(self.root,[self.session,second,third])
        def fail_second(path,validate):
            if path==second:raise OSError('Fixture permission failure')
            self.recycle(path,validate)
        moved,errors=recycle_plan(self.root,items,is_busy=lambda:False,recycle=fail_second)
        self.assertEqual(moved,[self.session]);self.assertEqual(errors[0][0],second)
        self.assertTrue(second.exists());self.assertTrue(third.exists())

    def test_symlinks_or_junctions_are_not_followed(self):
        link=self.session/'linked'
        try:link.symlink_to(self.trash,target_is_directory=True)
        except OSError:
            if os.name!='nt':raise
            import subprocess
            result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(self.trash)],capture_output=True)
            if result.returncode:self.skipTest('Cannot create fixture link/junction')
        try:
            with self.assertRaises(ValueError):plan_recycle(self.root,[self.session])
        finally:
            if os.name=='nt' and not link.is_symlink():link.rmdir()
            else:link.unlink()

    @unittest.skipUnless(os.name=='nt','Windows COM callbacks')
    def test_native_sink_vetoes_permanent_deletion(self):
        sink=_RecycleSink(lambda:None)
        self.assertLess(sink.callbacks[11](None,0,None),0)
        self.assertIn('Permanent deletion was blocked',sink.error)
        allowed=_RecycleSink(lambda:None)
        self.assertEqual(allowed.callbacks[11](None,0x80,None),0)


class RecycleUI(unittest.TestCase):
    def setUp(self):
        from dashcam_gui import DashcamGUI
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()/'Captures';self.root.mkdir()
        self.session=fixture(self.root)
        self.app=DashcamGUI(auto_connect=False)
        self.app.output.set(str(self.root.parent/'Transfers'))
        self.app.camera_panel.destination.set(str(self.root))
        self.app._refresh_drives()
        self.key='capture-'+self.session.name
        self.app.drive_tree.selection_set(self.key)
    def tearDown(self):
        for widget in (self.app.camera_panel,self.app):
            for command in list(widget._tclCommands or []):
                for callback in self.app.tk.splitlist(self.app.tk.call('after','info')):
                    if command in self.app.tk.call('after','info',callback):widget.after_cancel(callback)
        self.app.destroy();self.temp.cleanup()

    def test_cancel_does_not_touch_files_and_preserves_selection(self):
        with patch.object(self.app,'_confirm_capture_recycle',return_value=False),patch('dashcam_gui.recycle_plan') as recycle:
            self.app._delete_captures();recycle.assert_not_called()
        self.assertTrue(self.session.exists());self.assertEqual(self.app.drive_tree.selection(),(self.key,))

    def test_overlap_multiselect_success_refresh_and_repeated_empty_action(self):
        second=fixture(self.root,'Capture_second');self.app._refresh_drives()
        child=self.app.drive_tree.get_children(self.key)[0]
        self.app.drive_tree.selection_set(self.key,child,'capture-'+second.name)
        trash=self.root.parent/'FixtureTrash';trash.mkdir()
        def fake(path,validate):validate();path.rename(trash/path.name)
        with patch.object(self.app,'_confirm_capture_recycle',return_value=True),patch('dashcam_recycle.recycle_windows',side_effect=fake):
            self.app._delete_captures()
        self.assertFalse(self.app.drive_tree.selection());self.assertFalse(self.app.capture_rows)
        with patch('dashcam_gui.messagebox.showerror') as error:self.app._delete_captures();error.assert_called_once()

    def test_active_jobs_and_confirmation_race_block_deletion(self):
        for attr in ('capture','renderer','finalizer'):
            setattr(self.app.camera_panel,attr,SimpleNamespace(active=True))
            with patch('dashcam_gui.messagebox.showinfo'),patch.object(self.app,'_confirm_capture_recycle') as confirm:
                self.app._delete_captures();confirm.assert_not_called()
            setattr(self.app.camera_panel,attr,None)
        def start_transfer(*args):self.app.task_running=True;return True
        with patch.object(self.app,'_confirm_capture_recycle',side_effect=start_transfer),patch('dashcam_gui.messagebox.showerror'),patch('dashcam_recycle.recycle_windows') as recycle:
            self.app._delete_captures();recycle.assert_not_called()
        self.assertTrue(self.session.exists());self.app.task_running=False

    def test_existing_raw_delete_action_uses_recycle_and_exact_scope(self):
        with patch.object(self.app,'_confirm_capture_recycle',return_value=False) as confirm:
            self.app._delete_sources()
        items=confirm.call_args.args[1]
        self.assertEqual([item.kind for item in items],['Raw segment'])
        self.assertTrue((self.session/'Rendered'/'part_000000.mp4').exists())
