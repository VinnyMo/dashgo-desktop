"""Qt interaction regressions using disposable local fixtures only."""
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton, QMessageBox
from dashcam_desktop import Desktop
from dashcam_qt import Window


class QtWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.desktop=Desktop(self.root,auto_connect=False)
        self.window=Window(self.desktop);self.window.timer.stop()
        self.addCleanup(self.window.close)

    def drives(self):
        directory=self.desktop.transfer_dir;directory.mkdir()
        for hour in ('11','12'):(directory/f'2026-10-08_{hour}_00_00_f.ts').write_bytes(b'fixture')
        self.window.refresh_library()

    def final(self):
        path=self.desktop.capture_dir/'Exports'/'Capture_fixture'/'Finalized_fixture'/'Capture.mp4'
        path.parent.mkdir(parents=True);path.write_bytes(b'disposable final')
        (path.parent/'finalize.json').write_text('{"state":"finished"}')
        self.window.refresh_library();self.window.library.topLevelItem(0).setSelected(True)
        return path

    def test_live_has_no_export_and_preserves_studio_controls(self):
        self.assertFalse(any('export' in b.text().lower() for b in self.window.live_page.findChildren(QPushButton)))
        self.assertEqual([self.window.tabs.tabText(i) for i in range(3)],['Live','Transfer','Studio'])
        self.assertEqual(self.window.output_target.count(),5)
        self.assertFalse(self.window.render_option.isChecked())

    def test_refresh_keeps_one_transferred_drive_selected(self):
        self.drives();self.window.library.topLevelItem(0).setSelected(True)
        first=self.window.selected()[0]['drive'][0].started
        self.window.refresh_library()
        self.assertEqual(len(self.window.selected()),1)
        self.assertEqual(self.window.selected()[0]['drive'][0].started,first)

    def test_existing_partial_cancel_prevents_render(self):
        self.drives();self.window.library.topLevelItem(0).setSelected(True)
        partial=self.desktop.transfer_dir/'Drives'/'Drive_2026-10-08_11-00-00.mp4.part.mp4'
        partial.parent.mkdir();partial.write_bytes(b'keep partial')
        with patch.object(self.desktop,'render_drives') as render,patch('dashcam_qt.QMessageBox.question',return_value=QMessageBox.Cancel) as question:
            self.window.export_selected()
        question.assert_called_once();render.assert_not_called()
        self.assertEqual(partial.read_bytes(),b'keep partial')

    def test_final_delete_cancel_retains_file(self):
        final=self.final()
        with patch.object(self.window,'confirm_delete',return_value=False) as confirm:
            self.window.delete_selected()
        self.assertTrue(final.exists());self.assertFalse(self.desktop.media_busy)
        self.assertEqual(confirm.call_args.args[0][0][1],final)

    def test_final_delete_exact_file_and_completion(self):
        final=self.final();sibling=final.with_name('unrelated.txt');sibling.write_text('keep')
        trash=self.root/'FixtureTrash';trash.mkdir()
        def recycle(path,validate):validate();path.rename(trash/path.name)
        with patch.object(self.window,'confirm_delete',return_value=True),patch('dashcam_recycle.recycle_windows',side_effect=recycle):
            self.window.delete_selected()
            for worker in self.desktop._workers:worker.join(3)
            self.desktop.poll()
        self.assertFalse(final.exists());self.assertTrue(sibling.exists())
        self.assertIn('1 items moved',self.desktop.studio_status)
        self.assertTrue(self.desktop.refresh_needed)

    def test_close_blocks_remaining_recycle(self):
        self.final()
        def paused(root,items,is_busy):
            self.desktop.closed=True
            self.assertTrue(is_busy())
            return [],[(items[0].path,'Closed')]
        with patch.object(self.window,'confirm_delete',return_value=True),patch('dashcam_qt.recycle_plan',side_effect=paused):
            self.window.delete_selected()
            for worker in self.desktop._workers:worker.join(3)
            self.desktop.poll()
        self.assertIn('remaining files kept',self.desktop.studio_status)

    def test_settings_validate_all_before_applying(self):
        original=self.desktop.camera
        def fill():
            dialog=self.window.findChildren(QDialog)[-1]
            for editor in dialog.findChildren(QLineEdit):
                if editor.accessibleName()=='Camera address':editor.setText('http://192.0.2.1')
                if editor.accessibleName()=='Capture folder':editor.setText('')
            dialog.accept()
        QTimer.singleShot(0,fill)
        with self.assertRaises(ValueError):self.window.settings('live')
        self.assertEqual(self.desktop.camera,original)

    def test_capture_start_can_be_stopped(self):
        self.desktop.operation='capture_start';self.window.update_controls()
        self.assertTrue(self.window.capture_button.isEnabled())
        self.assertEqual(self.window.capture_button.text(),'Stop Capture')
        self.window.toggle_capture();self.assertTrue(self.desktop._capture_cancel.is_set())
        self.desktop.operation=''

    def test_new_final_becomes_selected(self):
        final=self.final();self.window.library.clearSelection();self.desktop.last_export=final
        self.window.refresh_library()
        self.assertEqual(self.window.selected()[0]['path'],final)
        self.assertTrue(self.window.open_button.isEnabled())


if __name__=='__main__':unittest.main()
