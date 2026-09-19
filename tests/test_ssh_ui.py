from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import ttkbootstrap as tb

from ui.ssh_dialog import SSHSetupDialog


class SSHDialogTests(unittest.TestCase):
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
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        home = patch('ssh_setup.Path.home', return_value=Path(directory.name))
        home.start()
        self.addCleanup(home.stop)
        self.key = Path(directory.name) / '.ssh' / 'id_ed25519'
        self.done = Mock()
        with patch.object(SSHSetupDialog, 'wait_window'):
            self.dialog = SSHSetupDialog(self.root, 'git@github.com:team/cad.git',
                                         'designer@example.com', self.done)
        self.addCleanup(self.close)

    def close(self):
        if self.dialog.winfo_exists():
            self.dialog.destroy()
        self.root.update()

    def wait(self):
        deadline = time.monotonic() + 3
        while self.dialog._busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.dialog._busy)

    def test_all_ssh_pages_fit(self):
        for index, page in enumerate(self.dialog.pages):
            self.dialog.tabs.select(index)
            self.root.update()
            for widget in page.winfo_children():
                self.assertTrue(widget.winfo_ismapped())
                self.assertLessEqual(widget.winfo_y() + widget.winfo_reqheight(), page.winfo_height(),
                                     'SSH page {} clips {}'.format(index + 1, widget.winfo_class()))

    def test_trust_requires_confirmation_and_finish_requires_success(self):
        self.dialog._key_done(('C:/private/key', 'ssh-ed25519 cHVibGlj'))
        candidate = {'host': 'github.com', 'port': 22, 'kind': 'ssh-ed25519',
                     'line': 'github.com ssh-ed25519 c2VydmVy', 'fingerprint': 'SHA256:example'}
        with patch('ui.ssh_dialog.scan_host', return_value=candidate), \
             patch('ui.ssh_dialog.trust_host', return_value='known_hosts') as trust, \
             patch('ui.ssh_dialog.ssh_command', return_value='ssh -i key'), \
             patch('ui.ssh_dialog.test_repository', return_value='ssh -i key'), \
             patch('ui.ssh_dialog.messagebox.showinfo'):
            self.dialog._scan()
            self.wait()
            trust.assert_not_called()
            self.dialog._test()
            trust.assert_not_called()
            self.dialog._finish()
            self.done.assert_not_called()
            self.dialog.confirm_var.set(True)
            self.dialog._test()
            self.wait()
            trust.assert_called_once_with(candidate)
            self.dialog._finish()
            self.done.assert_called_once_with('ssh -i key')

    def test_changing_key_clears_public_key_and_verified_state(self):
        self.dialog._key_done(('C:/private/key', 'ssh-ed25519 cHVibGlj'))
        self.dialog._command = 'ssh -i key'
        self.dialog.key_var.set('C:/private/different')
        self.assertEqual(self.dialog._public, '')
        self.assertIsNone(self.dialog._command)
        self.assertEqual(str(self.dialog.finish_btn['state']), 'disabled')

    def test_create_without_existing_keys_does_not_prompt(self):
        with patch('ui.ssh_dialog.create_key', return_value=(str(self.key), 'ssh-ed25519 cHVibGlj')) as create, \
             patch('ui.ssh_dialog.messagebox.askyesno') as confirm:
            self.dialog._create()
            self.wait()
            confirm.assert_not_called()
            create.assert_called_once_with('designer@example.com', overwrite=False)
        self.assertEqual(self.dialog.key_var.get(), str(self.key))

    def test_declining_replacement_of_either_key_does_not_generate(self):
        self.key.parent.mkdir()
        for path in (self.key, Path(str(self.key) + '.pub')):
            with self.subTest(path=path), \
                 patch('ui.ssh_dialog.create_key') as create, \
                 patch('ui.ssh_dialog.messagebox.askyesno', return_value=False) as confirm:
                path.write_text('original')
                self.dialog._create()
                confirm.assert_called_once()
                self.assertEqual(confirm.call_args.kwargs['default'], 'no')
                self.assertIn(str(path), confirm.call_args.args[1])
                create.assert_not_called()
                self.assertFalse(self.dialog._busy)
                self.assertEqual(path.read_text(), 'original')
                path.unlink()

    def test_confirming_replacement_generates_and_displays_new_key(self):
        self.key.parent.mkdir()
        self.key.write_text('original')
        with patch('ui.ssh_dialog.create_key', return_value=(str(self.key), 'ssh-ed25519 bmV3')) as create, \
             patch('ui.ssh_dialog.messagebox.askyesno', return_value=True) as confirm:
            self.dialog._create()
            self.wait()
            confirm.assert_called_once()
            create.assert_called_once_with('designer@example.com', overwrite=True)
        self.assertEqual(self.dialog._public, 'ssh-ed25519 bmV3')
        self.assertEqual(self.dialog.key_var.get(), str(self.key))

    def test_worker_error_restores_controls_and_cancel_does_not_configure_ssh(self):
        with patch('ui.ssh_dialog.create_key', side_effect=OSError('Cannot write key')), \
             patch('ui.ssh_dialog.messagebox.showerror') as error:
            self.dialog._create()
            self.dialog._cancel()
            self.assertTrue(self.dialog.winfo_exists())
            self.wait()
            error.assert_called_once()
        self.assertEqual(str(self.dialog.cancel_btn['state']), 'normal')
        self.dialog._cancel()
        self.done.assert_not_called()


if __name__ == '__main__':
    unittest.main()
