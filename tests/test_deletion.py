"""Associated deletion uses disposable fixtures, never user media."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from dashcam_deletion import plan_deletion, recycle_deletion


class AssociatedDeletion(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.captures=self.root/'Captures';self.captures.mkdir()
        self.transfers=self.root/'Transfers';self.transfers.mkdir()
        self.trash=self.root/'FixtureTrash';self.trash.mkdir()
        self.session=self.captures/'Capture_fixture'
        self.put(self.session/'session.json','{"state":"stopped"}')

    def put(self,path,value='fixture'):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value);return path

    def final(self,name='Finalized_fixture',session=None):
        directory=self.captures/'Exports'/(session or self.session.name)/name
        final=self.put(directory/'Capture.mp4')
        for name in ('segments.ffconcat','progress.log','ffmpeg.log','cleanup.json','cleanup.json.tmp'):
            self.put(directory/name)
        self.put(directory/'finalize.json','{"state":"finished"}')
        return final

    def render(self):
        directory=self.session/'Rendered'
        self.put(directory/'render.json','{"state":"finished"}')
        for name in ('render.json.tmp','.capture.shuffled_playlist.m4a','track-0.txt','channel.txt','route.txt'):
            self.put(directory/name)
        return self.put(directory/'part_000000.mp4')

    def plan(self,captures=(),transfers=(),**kw):
        return plan_deletion(self.captures,self.transfers,captures,transfers,**kw)

    def recycle(self,path,validate):
        validate();path.rename(self.trash/str(len(list(self.trash.iterdir()))))

    def execute(self,plan,**kw):
        moved,failed=recycle_deletion(plan,is_busy=lambda:False,recycle=self.recycle,**kw)
        self.assertFalse(failed,failed);return moved

    def test_final_removes_owned_audit_hierarchy_and_empty_working_session(self):
        final=self.final();self.render().unlink()  # disposable fixture setup
        music=self.put(self.root/'Music'/'original.mp3')
        plan=self.plan([final]);self.execute(plan)
        self.assertFalse(self.session.exists());self.assertFalse((self.captures/'Exports').exists())
        self.assertTrue(self.captures.exists());self.assertTrue(music.exists())
        self.assertEqual(sum(1 for p in self.trash.rglob('*') if p.is_file()),14)

    def test_selected_export_leaves_sibling_export_and_unselected_raw(self):
        final=self.final();sibling=self.final('Finalized_other')
        raw=self.put(self.session/'part_000000.mkv')
        self.execute(self.plan([final]))
        self.assertFalse(final.parent.exists());self.assertTrue(sibling.exists());self.assertTrue(raw.exists())
        self.assertTrue((self.session/'session.json').exists())

    def test_unrelated_files_and_empty_unknown_subfolders_remain(self):
        final=self.final();unknown=self.put(final.parent/'notes.txt');empty=final.parent/'Personal';empty.mkdir()
        self.execute(self.plan([final]))
        self.assertTrue(unknown.exists());self.assertTrue(empty.exists())
        self.assertFalse((final.parent/'finalize.json').exists())
        self.assertEqual(set(p.name for p in final.parent.iterdir()),{'notes.txt','Personal'})

    def test_last_raw_selection_removes_session_support_and_folder(self):
        raw=self.put(self.session/'part_000000.mkv')
        self.put(self.session/'session.json.tmp')
        self.execute(self.plan([raw]))
        self.assertFalse(self.session.exists())

    def test_render_deletion_preserves_raw_and_removes_render_support(self):
        raw=self.put(self.session/'part_000000.mkv');render=self.render()
        self.execute(self.plan([render]))
        self.assertTrue(raw.exists());self.assertTrue((self.session/'session.json').exists())
        self.assertFalse(render.parent.exists())

    def test_unselected_partial_retains_render_support(self):
        render=self.render();partial=self.put(render.with_name('part_000001.partial.mp4'))
        self.execute(self.plan([render]))
        self.assertTrue(partial.exists());self.assertTrue((render.parent/'render.json').exists())
        self.assertTrue((self.session/'session.json').exists())

    def test_capture_parent_keeps_external_final_and_unrelated_content(self):
        raw=self.put(self.session/'part_000000.mkv');self.render();final=self.final()
        personal=self.put(self.session/'notes.txt')
        self.execute(self.plan([self.session,raw]))
        self.assertTrue(final.exists());self.assertTrue(personal.exists())
        self.assertEqual(list(self.session.iterdir()),[personal])

    def test_legacy_final_folder_removed_with_metadata(self):
        folder=self.session/'Finalized_old';final=self.put(folder/'Capture.mp4')
        self.put(folder/'finalize.json','{"state":"finished"}');self.put(folder/'progress.log')
        self.execute(self.plan([final]));self.assertFalse(self.session.exists())

    def test_historical_sibling_leftovers_are_not_swept(self):
        final=self.final();old=final.parent.parent/'Finalized_old'
        audit=self.put(old/'finalize.json','{"state":"finished"}')
        self.execute(self.plan([final]))
        self.assertTrue(audit.exists());self.assertFalse(final.parent.exists())

    def test_transfer_source_partial_and_shared_history(self):
        source=self.put(self.transfers/'2026-10-08_11_00_00_f.ts')
        partial=self.put(source.with_name(source.name+'.part'))
        history=self.put(self.transfers/'.dashcam_history.sqlite3');log=self.put(self.transfers/'dashcam_transfer.log')
        callback=Mock();self.execute(self.plan(transfers=[source]),source_removed=callback)
        self.assertFalse(source.exists());self.assertFalse(partial.exists())
        callback.assert_called_once_with(source);self.assertTrue(history.exists());self.assertTrue(log.exists())

    def drive(self,stem='Drive_2026-10-08_11-00-00_1GBH'):
        output=self.put(self.transfers/'Drives'/(stem+'.mp4'))
        for suffix in ('drive.ffconcat','shuffled_playlist.m4a','track-0.txt','channel.txt','route.txt'):
            self.put(output.parent/('.'+stem+'.1234.'+suffix))
        return output

    def test_drive_output_removes_exact_sidecars_and_empty_directory(self):
        output=self.drive();self.execute(self.plan(transfers=[output]))
        self.assertFalse(output.parent.exists());self.assertTrue(self.transfers.exists())

    def test_other_quality_and_unrecognized_files_are_preserved(self):
        output=self.drive();other=self.drive('Drive_2026-10-08_11-00-00_2GBH')
        note=self.put(output.parent/'notes.txt')
        self.execute(self.plan(transfers=[output]))
        self.assertTrue(other.exists());self.assertTrue(note.exists())
        self.assertFalse(any('1GBH' in p.name for p in output.parent.iterdir()))

    def test_whole_drive_includes_partial_and_abandoned_preparation(self):
        source=self.put(self.transfers/'2026-10-08_11_00_00_f.ts');output=self.drive()
        partial=self.put(output.with_name(output.name+'.part.mp4'))
        orphan=self.put(output.parent/'.Drive_2026-10-08_11-00-00_2GBH.88.shuffled_playlist.m4a')
        self.execute(self.plan(transfers=[source],drive_prefixes=['Drive_2026-10-08_11-00-00']))
        self.assertFalse(source.exists());self.assertFalse(output.parent.exists())

    def test_changed_sidecar_blocks_everything_before_recycling(self):
        final=self.final();plan=self.plan([final]);self.put(final.parent/'progress.log','changed')
        recycle=Mock();moved,failed=recycle_deletion(plan,is_busy=lambda:False,recycle=recycle)
        self.assertFalse(moved);self.assertTrue(failed);recycle.assert_not_called()

    def test_new_unknown_file_blocks_directory_scope(self):
        final=self.final();plan=self.plan([final]);self.put(final.parent/'new.txt')
        moved,failed=recycle_deletion(plan,is_busy=lambda:False,recycle=self.recycle)
        self.assertFalse(moved);self.assertTrue(failed);self.assertTrue(final.exists())

    def test_busy_and_native_callback_race_preserve_remaining_files(self):
        final=self.final();plan=self.plan([final]);busy=False
        def raced(path,validate):
            nonlocal busy
            busy=True;validate()
        moved,failed=recycle_deletion(plan,is_busy=lambda:busy,recycle=raced)
        self.assertFalse(moved);self.assertTrue(failed);self.assertTrue(final.exists())

    def test_export_lock_or_active_status_rejects_plan(self):
        final=self.final();lock=self.put(self.session/'.export.lock')
        with self.assertRaises(ValueError):self.plan([final])
        lock.unlink();self.put(final.parent/'finalize.json','{"state":"assembling"}')
        with self.assertRaises(ValueError):self.plan([final])

    def test_failure_stops_batch_and_repeat_uses_fresh_plan(self):
        raw=self.put(self.session/'part_000000.mkv');final=self.final();plan=self.plan([raw,final])
        def fail_second(path,validate):
            if list(self.trash.iterdir()):raise OSError('Fixture failure')
            self.recycle(path,validate)
        moved,failed=recycle_deletion(plan,is_busy=lambda:False,recycle=fail_second)
        self.assertEqual(len(moved),1);self.assertTrue(failed)
        remaining=[p for p in (raw,final) if p.exists()]
        self.execute(self.plan(remaining))
        self.assertFalse(self.session.exists());self.assertFalse(final.parent.exists())
        with self.assertRaises((OSError,ValueError)):self.plan([final])

    def test_manifest_path_is_never_followed(self):
        final=self.final();outside=self.put(self.root/'private.txt')
        self.put(final.parent/'finalize.json',json.dumps({'state':'finished','output':str(outside)}))
        self.execute(self.plan([final]));self.assertTrue(outside.exists())

    def test_hardlinked_owned_file_rejected(self):
        final=self.final();alias=self.root/'alias.mp4'
        os.link(final,alias)
        with self.assertRaises(ValueError):self.plan([final])

    def test_final_selection_includes_its_exact_partial(self):
        final=self.final();partial=self.put(final.with_name('Capture.partial.mp4'))
        self.execute(self.plan([final]))
        self.assertFalse(final.parent.exists());self.assertFalse(partial.exists())

    def test_partial_selection_preserves_final_and_its_records(self):
        final=self.final();partial=self.put(final.with_name('Capture.partial.mp4'))
        self.execute(self.plan([partial]))
        self.assertTrue(final.exists());self.assertTrue((final.parent/'finalize.json').exists())

    def test_drive_final_selection_includes_its_partial(self):
        output=self.drive();self.put(output.with_name(output.name+'.part.mp4'))
        self.execute(self.plan(transfers=[output]));self.assertFalse(output.parent.exists())

    def test_permanent_delete_or_recycle_failure_leaves_scope_intact(self):
        final=self.final();plan=self.plan([final])
        def unavailable(path,validate):raise OSError('Recycle Bin unavailable')
        moved,failed=recycle_deletion(plan,is_busy=lambda:False,recycle=unavailable)
        self.assertFalse(moved);self.assertTrue(failed);self.assertTrue(final.exists())

    def test_linked_owned_support_is_rejected(self):
        final=self.final();outside=self.put(self.root/'outside.txt')
        linked=final.parent/'progress.log';linked.unlink()
        junction=False
        try:linked.symlink_to(outside)
        except OSError:
            if os.name!='nt':raise
            import subprocess
            directory=self.root/'Outside';directory.mkdir()
            result=subprocess.run(['cmd','/c','mklink','/J',str(linked),str(directory)],capture_output=True)
            if result.returncode:self.skipTest('Fixture link/junction unavailable')
            junction=True
        try:
            with self.assertRaises(ValueError):self.plan([final])
            self.assertTrue(outside.exists())
        finally:
            if junction:linked.rmdir()
            else:linked.unlink()

    def test_status_change_after_first_move_stops_remaining_scope(self):
        raw=self.put(self.session/'part_000000.mkv');final=self.final()
        # Keep working folder from collapsing; its record remains a guard.
        self.put(self.session/'part_000001.mkv')
        plan=self.plan([raw,final]);calls=0
        def change(path,validate):
            nonlocal calls
            self.recycle(path,validate);calls+=1
            self.put(self.session/'session.json','{"state":"recording"}')
        moved,failed=recycle_deletion(plan,is_busy=lambda:False,recycle=change)
        self.assertEqual(calls,1);self.assertEqual(len(moved),1);self.assertTrue(failed)

    def test_multi_session_plan_and_overlapping_selections(self):
        first=self.final();second=self.final(session='Capture_second')
        raw=self.put(self.session/'part_000000.mkv')
        self.execute(self.plan([first,second,raw,self.session]))
        self.assertFalse(self.session.exists());self.assertFalse((self.captures/'Exports').exists())

    def test_source_history_failure_is_reported_after_successful_move(self):
        source=self.put(self.transfers/'2026-10-08_11_00_00_f.ts')
        callback=Mock(side_effect=RuntimeError('History unavailable'))
        moved,failed=recycle_deletion(self.plan(transfers=[source]),is_busy=lambda:False,recycle=self.recycle,source_removed=callback)
        self.assertEqual(moved,[source]);self.assertTrue(failed);self.assertFalse(source.exists())

    def test_custom_nested_library_root_is_never_recycled(self):
        output=self.drive()
        plan=plan_deletion(output.parent,self.transfers,transfer_paths=[output])
        self.execute(plan)
        self.assertTrue(output.parent.is_dir());self.assertFalse(list(output.parent.iterdir()))


if __name__=='__main__':unittest.main()
