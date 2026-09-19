"""Tk smoke tests; require a Windows desktop with Tcl/Tk available."""
import time
import unittest
from unittest.mock import Mock, patch

import ttkbootstrap as tb

from ui.setup_wizard import SetupWizard


class WizardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tb.Window(themename='flatly')
            cls.root.update()
        except Exception as exc:
            raise unittest.SkipTest('Tk desktop unavailable: {}'.format(exc))

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.complete = Mock()
        self.check = patch.object(SetupWizard, '_check_tools')
        self.check.start()
        self.addCleanup(self.check.stop)
        with patch.object(SetupWizard, 'wait_window'):
            self.wizard = SetupWizard(self.root, self.complete)
        self.addCleanup(self.close_wizard)

    def close_wizard(self):
        if self.wizard.winfo_exists():
            self.wizard.destroy()
        self.root.update()

    def wait_for_worker(self):
        deadline = time.monotonic() + 3
        while self.wizard._busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.wizard._busy, 'Wizard worker failed to complete')

    def test_all_steps_fit_and_finish_saves_once(self):
        self.wizard._tools_done({'git': True, 'lfs': True})
        with patch('ui.setup_wizard.get_identity', return_value=('Designer', 'designer@example.com')):
            self.wizard._next()
            self.wait_for_worker()
        self.assertEqual(self.wizard._step, 1)
        self.wizard._next()
        self.assertEqual(self.wizard._step, 2)
        settings = {'local_path': 'C:/CAD', 'repo_url': 'https://host/team/cad.git'}
        self.wizard.url_var.set(settings['repo_url'])
        with patch('ui.setup_wizard.prepare_repository', return_value=settings), \
             patch('ui.setup_wizard.validate_repository', return_value='C:/CAD'):
            self.wizard._next()
            self.wait_for_worker()
        self.assertEqual(self.wizard._step, 3)
        self.complete.assert_not_called()
        for step in range(4):
            self.wizard._step = step
            self.wizard._render()
            self.root.update()
            for widget in self.wizard.body.winfo_children():
                self.assertLessEqual(widget.winfo_y() + widget.winfo_reqheight(),
                                     self.wizard.body.winfo_height(),
                                     'Step {} clips {}'.format(step + 1, widget.winfo_class()))
                self.assertTrue(widget.winfo_ismapped(), 'Step {} hides a control'.format(step + 1))
        self.wizard._next()
        self.complete.assert_called_once_with(settings)

    def test_cancel_never_saves(self):
        self.wizard._cancel()
        self.complete.assert_not_called()

    def test_ssh_selection_applies_only_to_matching_repository(self):
        self.wizard._step = 2
        self.wizard._render()
        self.wizard.url_var.set('git@host:team/cad.git')
        self.wizard.name_var.set('Designer')
        self.wizard.email_var.set('designer@example.com')
        for selected in ('git@host:team/cad.git', 'git@other:team/cad.git'):
            self.wizard._step = 2
            self.wizard._render()
            self.wizard._ssh_setup = (selected, 'ssh -i selected-key')
            with patch('ui.setup_wizard.validate_repository', return_value='C:/CAD'), \
                 patch('ui.setup_wizard.prepare_repository', return_value={'local_path': 'C:/CAD'}) as prepare:
                self.wizard._next()
                self.wait_for_worker()
            expected = 'ssh -i selected-key' if selected == self.wizard.url_var.get() else None
            self.assertEqual(prepare.call_args.kwargs['ssh_command'], expected)

    def test_operation_error_restores_controls_and_does_not_save(self):
        with patch('ui.setup_wizard.messagebox.showerror') as error:
            self.wizard._work(Mock(side_effect=OSError('Permission denied')), Mock(), 'Working')
            self.wizard._cancel()
            self.assertTrue(self.wizard.winfo_exists())
            self.wait_for_worker()
            error.assert_called_once()
        self.assertEqual(str(self.wizard.cancel_btn['state']), 'normal')
        self.complete.assert_not_called()

    def test_save_error_keeps_finish_available_for_retry(self):
        self.wizard.result = {'local_path': 'C:/CAD'}
        self.wizard._step = 3
        self.wizard._render()
        self.complete.side_effect = [OSError('Read only'), None]
        with patch('ui.setup_wizard.messagebox.showerror') as error:
            self.wizard._next()
            error.assert_called_once()
        self.assertTrue(self.wizard.winfo_exists())
        self.wizard._next()
        self.assertEqual(self.complete.call_count, 2)


if __name__ == '__main__':
    unittest.main()
