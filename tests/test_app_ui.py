"""Main-window regressions, using fake operations and no user repository."""
import threading
import time
import unittest
import tkinter as tk
import ttkbootstrap as tb
from unittest.mock import Mock, patch

from app import App
from progress import report


FILES = [dict(path='Chassis/frame.step', status='locked_by_me_modified', is_lfs=True,
              locked_by='Designer'),
         dict(path='Chassis/bracket.step', status='unchanged', is_lfs=True, locked_by=None)]


class AppUITests(unittest.TestCase):
    def setUp(self):
        try:
            self.app = App()
        except Exception as exc:
            raise unittest.SkipTest('Tk desktop unavailable: {}'.format(exc))
        self.addCleanup(self.app.root.destroy)
        self.app.config = {'local_path': 'C:/Example/CAD'}
        self.app._build_ui()
        self.app._populate(FILES)
        self.app._read_repo_title = Mock(return_value=('CAD', 'main'))
        self.app.root.update()

    def drain(self):
        while not self.app._op_queue.empty():
            self.app._op_queue.get_nowait()()
        self.app.root.update()

    def wait(self):
        deadline = time.monotonic() + 3
        while self.app._busy and time.monotonic() < deadline:
            self.drain()
            time.sleep(0.01)
        self.assertFalse(self.app._busy)

    def test_busy_guard_progress_and_completion(self):
        release = threading.Event()
        self.addCleanup(release.set)
        duplicate = Mock()
        def worker():
            report('Locking frame.step', 0, 2)
            release.wait(2)
            return FILES
        def done(result):
            self.app._populate(result)
            self.app._set_status('Locked 2 files.')
        self.app._async(worker, on_done=done, title='Locking files')
        self.app._async(duplicate)
        self.app._on_close()
        self.assertTrue(self.app.root.winfo_exists())
        self.assertEqual(str(self.app.toolbar.buttons['pull']['state']), 'disabled')
        self.drain()
        self.assertIn('Locking frame.step', self.app.activity.detail.cget('text'))
        release.set()
        self.wait()
        duplicate.assert_not_called()
        self.assertIn('Complete', self.app.activity.heading.cget('text'))
        self.assertEqual(self.app.activity.detail.cget('text'), 'Locked 2 files.')
        self.assertEqual(float(self.app.activity.bar['value']), 100)
        self.assertEqual(str(self.app.toolbar.buttons['pull']['state']), 'normal')

    def test_error_retained_and_controls_restored(self):
        self.app._async(Mock(side_effect=RuntimeError('Network unavailable')), title='Pulling')
        self.wait()
        self.assertIn('Failed', self.app.activity.heading.cget('text'))
        self.assertIn('Network unavailable', self.app.activity.log.get('1.0', 'end'))
        self.assertTrue(self.app.activity._expanded)
        self.assertEqual(str(self.app.file_menu.entrycget(1, 'state')), 'normal')

    def test_warning_is_not_displayed_as_unqualified_success(self):
        self.app._async(lambda: report('Lock server unavailable', level='warning'))
        self.wait()
        self.assertIn('warnings', self.app.activity.heading.cget('text'))
        self.assertIn('Lock server unavailable', self.app.activity.log.get('1.0', 'end'))

    def test_selection_is_deduplicated_and_survives_refresh(self):
        tree = self.app.file_table.tree
        tree.selection_set(['dir:Chassis/', 'file:Chassis/frame.step'])
        tree.item('dir:Chassis/', open=False)
        self.assertEqual(len(self.app.file_table.get_selected_files()), 2)
        self.app._populate(FILES)
        self.assertEqual(len(self.app.file_table.get_selected_files()), 2)
        self.assertFalse(tree.item('dir:Chassis/', 'open'))
        self.assertEqual(str(self.app.summary_labels['changed']['text']), '1')
        self.assertEqual(str(self.app.summary_labels['mine']['text']), '1')

    def test_feedback_and_toolbar_fit_at_minimum_size(self):
        width, height = self.app.root.minsize()
        self.app.root.geometry('{}x{}'.format(width, height))
        self.app.activity.begin('Pulling latest changes')
        self.app.activity.finish('Offline. Please reconnect and try Pull again.', error=True)
        self.app.root.update()
        for button in self.app.toolbar.buttons.values():
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_x() + button.winfo_width(), self.app.toolbar.winfo_width())
        activity = self.app.activity
        self.assertLessEqual(activity.winfo_y() + activity.winfo_height(), self.app.root.winfo_height())
        self.assertGreater(self.app.file_table.winfo_height(), 80)
        self.assertGreater(activity.log.winfo_height(), 50)
        self.assertTrue(activity.detail.winfo_ismapped())

    def test_unverified_lock_counts_are_not_reported_as_zero(self):
        self.app._populate([dict(FILES[1], locks_verified=False)])
        self.assertEqual(str(self.app.summary_labels['others']['text']), '—')
        self.assertEqual(self.app.file_table.tree.item('file:Chassis/bracket.step', 'values'),
                         ('Unchanged', 'Not verified'))

    def test_theme_switch_preserves_selection_and_activity(self):
        tree = self.app.file_table.tree
        tree.selection_set('file:Chassis/frame.step')
        self.app.activity.begin('Refreshing files')
        self.app.activity.finish('All files are up to date.')
        history = self.app.activity.log.get('1.0', 'end')
        for mode in ('dark', 'light', 'dark'):
            self.app.theme.set_preference(mode)
            self.app.root.update()
            self.assertEqual(tree.selection(), ('file:Chassis/frame.step',))
            self.assertEqual(self.app.activity.log.get('1.0', 'end'), history)
            colors = self.app.theme.style.colors
            self.assertEqual(tree.tag_configure('modified')['foreground'], str(colors.warning))
            self.assertEqual(self.app.activity.log.cget('background'), str(colors.inputbg))
            self.assertEqual(self.app.theme.style.lookup('Card.TFrame', 'background'), str(colors.inputbg))

    def test_new_dialog_inputs_follow_theme(self):
        self.app.theme.set_preference('dark')
        dialog = tb.Toplevel(self.app.root)
        self.addCleanup(dialog.destroy)
        text = tk.Text(dialog)
        text.pack()
        files = tk.Listbox(dialog)
        files.pack()
        self.app.root.update()
        self.assertEqual(text.cget('background'), '#192334')
        self.assertEqual(files.cget('foreground'), '#E4EAF5')
        self.app.theme.set_preference('light')
        self.app.root.update()
        self.assertEqual(text.cget('background'), '#FFFFFF')

    def test_appearance_is_saved_and_failed_save_keeps_previous_theme(self):
        self.app.theme_var.set('Dark')
        with patch('app.save_config') as save:
            self.app._change_theme()
        self.assertEqual(save.call_args.args[0]['theme'], 'dark')
        self.assertEqual(self.app.config['local_path'], 'C:/Example/CAD')
        self.app.theme_var.set('Light')
        with patch('app.save_config', side_effect=OSError('Read only')), patch('app.show_error') as error:
            self.app._change_theme()
        error.assert_called_once()
        self.assertEqual(self.app.theme.preference, 'dark')
        self.assertEqual(self.app.theme_var.get(), 'Dark')

    def test_system_changes_followed_only_in_system_mode(self):
        with patch('ui.theme.system_theme', return_value='light'):
            self.app.theme.set_preference('system')
        with patch('ui.theme.system_theme', return_value='dark'):
            self.app.theme._apply()
        self.assertEqual(self.app.theme.resolved, 'dark')
        self.app.theme.set_preference('light')
        with patch('ui.theme.system_theme', return_value='dark'):
            self.app.theme._apply()
        self.assertEqual(self.app.theme.resolved, 'light')

    def test_repository_switch_retains_appearance(self):
        self.app.theme.set_preference('dark')
        with patch('app.save_config') as save, patch.object(self.app, '_refresh'):
            self.app._on_clone_complete({'local_path': 'C:/Other CAD'})
        self.assertEqual(save.call_args.args[0]['theme'], 'dark')


if __name__ == '__main__':
    unittest.main()
