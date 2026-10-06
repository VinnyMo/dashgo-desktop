import unittest
from unittest.mock import patch

from dashcam_stitch import target_budget, calculate_target_encoding
import dashcam_process


class QualityTests(unittest.TestCase):
    def test_low_end_is_one_decimal_gb_per_hour_with_headroom(self):
        budget = target_budget('1gbh', 3600)
        self.assertEqual(budget, 960_000_000)
        self.assertEqual(target_budget('1gbh', 1800), budget // 2)
        _, audio, options = calculate_target_encoding(3600, 'libx264', budget)
        video = int(options[options.index('-b:v') + 1].rstrip('k'))
        self.assertLessEqual((video + audio) * 1000 * 3600 / 8, budget)
        self.assertNotIn('-crf', options)
        self.assertGreater(video, 1800)

    def test_hourly_profiles_scale_with_duration_and_absolute_profiles_remain(self):
        self.assertEqual(target_budget('4gbh', 900), target_budget('1gbh', 3600))
        self.assertEqual(target_budget('2gb', 900), 1_920_000_000)

    def test_windows_subprocesses_hide_consoles_even_without_explicit_flags(self):
        with patch.object(dashcam_process.os, 'name', 'nt'), patch.object(dashcam_process._subprocess, 'Popen') as launch:
            dashcam_process.Popen(['ffprobe'])
            self.assertTrue(launch.call_args.kwargs['creationflags'] & 0x08000000)

    def test_preview_resize_keeps_color_and_does_not_leak_gdi_handles(self):
        import ctypes
        import os
        if os.name != 'nt':
            self.skipTest('Windows GDI preview')
        from dashcam_preview import resize_ppm
        frame = b'P6\n1280 720\n255\n' + bytes((30, 100, 220)) * (1280 * 720)
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        user = ctypes.windll.user32
        user.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        before = user.GetGuiResources(kernel.GetCurrentProcess(), 0)
        for _ in range(30):
            result = resize_ppm(frame, 960, 540)
            header, width, maximum, data = result.split(b'\n', 3)
            self.assertEqual(width, b'960 540')
            self.assertEqual(len(data), 960 * 540 * 3)
            self.assertEqual(data[:3], bytes((30, 100, 220)))
        self.assertEqual(user.GetGuiResources(kernel.GetCurrentProcess(), 0), before)

    def test_main_gui_has_three_tabs_and_no_preview_border(self):
        import tkinter as tk
        from dashcam_gui import DashcamGUI
        app = DashcamGUI(auto_connect=False)
        try:
            self.assertEqual([app.tabs.tab(tab, 'text') for tab in app.tabs.tabs()], ['Live', 'Transfer', 'Studio'])
            panel = app.camera_panel
            self.assertEqual(int(panel.canvas['borderwidth']), 0)
            self.assertEqual(int(panel.canvas['highlightthickness']), 0)
            self.assertFalse(panel.play.winfo_manager())
            self.assertFalse(panel.stop_preview.winfo_manager())
            self.assertEqual(app.logs_window.state(), 'withdrawn')
            app._size_changed(0)
            self.assertEqual(app.output_mode.get(), '1gbh')
        finally:
            for widget in (app.camera_panel, app):
                for command in list(widget._tclCommands or []):
                    if command.endswith(('_poll', '_drain_events', '_initial_refresh')):
                        for callback in app.tk.splitlist(app.tk.call('after', 'info')):
                            if command in app.tk.call('after', 'info', callback):
                                widget.after_cancel(callback)
            app.destroy()
