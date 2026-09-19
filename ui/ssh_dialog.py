import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

import ttkbootstrap as tb

from dpi import s
from ssh_setup import (create_key, public_key, scan_host, trust_host, ssh_command,
                       test_repository, host_guidance, ssh_tools, key_paths)


class SSHSetupDialog(tb.Toplevel):
    def __init__(self, master, url, email, on_complete):
        super().__init__(master)
        self.url, self.email, self.on_complete = url, email, on_complete
        self._busy = False
        self._events = queue.Queue()
        self._candidate = None
        self._command = None
        self._public = ''
        self.key_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.confirm_var = tk.BooleanVar(value=False)
        self.key_var.trace_add('write', self._key_changed)
        self.confirm_var.trace_add('write', self._confirmation_changed)
        self.title('Set up SSH access')
        self.transient(master)
        self.resizable(False, False)
        self.protocol('WM_DELETE_WINDOW', self._cancel)
        self.bind('<Escape>', lambda event: self._cancel())
        self.settings_url, self.fingerprint_url, guidance = host_guidance(url)
        outer = ttk.Frame(self, padding=s(20))
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Connect with SSH', font=('', s(16), 'bold')).pack(anchor='w')
        ttk.Label(outer, text=url, wraplength=s(590)).pack(anchor='w', pady=(s(6), s(12)))
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill='both', expand=True)
        pages = []
        for title in ('1. Your key', '2. Add to account', '3. Verify and test'):
            page = ttk.Frame(self.tabs, padding=s(12), width=s(600), height=s(360))
            page.pack_propagate(False)
            self.tabs.add(page, text=title)
            pages.append(page)
        self.pages = pages

        self._label(pages[0], 'Create a key in ~/.ssh/id_ed25519, or select an existing private key. '
                    'Replacing existing keys requires confirmation. Only the public key is copied or displayed.')
        self._label(pages[0], 'The generated key has no passphrase so GCAD can connect without a terminal. '
                    'Keep the private key on this Windows account. If your team requires an encrypted key, '
                    'select one below and use the encrypted-key instructions.')
        ttk.Button(pages[0], text='Create key without passphrase', command=self._create).pack(anchor='w', pady=s(8))
        self._label(pages[0], 'Private key file (without .pub)')
        row = ttk.Frame(pages[0])
        row.pack(fill='x', pady=(0, s(10)))
        ttk.Entry(row, textvariable=self.key_var).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Browse…', command=self._browse).pack(side='right', padx=s(6))
        ttk.Button(pages[0], text='Use selected key', command=self._load_key).pack(anchor='w')
        ttk.Button(pages[0], text='Encrypted-key instructions', command=self._agent_help).pack(anchor='w', pady=s(10))

        self._label(pages[1], 'Complete this step in your own Git account. GCAD cannot sign in for you, '
                    'add account keys, grant repository access, or approve your organization’s SSO.')
        self._label(pages[1], guidance)
        self.public_text = tk.Text(pages[1], height=4, width=65, wrap='char', state='disabled')
        self.public_text.pack(fill='x', pady=s(8))
        row = ttk.Frame(pages[1])
        row.pack(fill='x')
        ttk.Button(row, text='Copy public key', command=self._copy).pack(side='left')
        if self.settings_url:
            ttk.Button(row, text='Open account SSH settings', command=lambda: webbrowser.open(
                self.settings_url)).pack(side='left', padx=s(8))
        self._label(pages[1], 'After saving the key, accept any repository invitation from your team. '
                    'Then open “3. Verify and test”. Never upload the private key file.')

        self._label(pages[2], 'First check that you are connecting to the right server. Fetch its '
                    'fingerprint, then compare it with the host’s official documentation or a fingerprint '
                    'provided separately by your team administrator.')
        row = ttk.Frame(pages[2])
        row.pack(fill='x', pady=s(8))
        ttk.Button(row, text='Fetch server fingerprint', command=self._scan).pack(side='left')
        if self.fingerprint_url:
            ttk.Button(row, text='Official fingerprints', command=lambda: webbrowser.open(
                self.fingerprint_url)).pack(side='left', padx=s(8))
        self.fingerprint_text = tk.Text(pages[2], height=3, width=65, wrap='char', state='disabled')
        self.fingerprint_text.pack(fill='x', pady=s(8))
        ttk.Checkbutton(pages[2], text='I compared the fingerprint and it matches.',
                        variable=self.confirm_var).pack(anchor='w', pady=s(8))
        ttk.Button(pages[2], text='Trust server and test repository access', command=self._test).pack(anchor='w')
        self._label(pages[2], 'If it differs, stop and contact your administrator. A successful test '
                    'confirms read access; your team must also grant write access for Push and Lock. '
                    'Git LFS may separately ask you to sign in through HTTPS.')

        ttk.Label(outer, textvariable=self.status_var, wraplength=s(600)).pack(anchor='w', pady=s(8))
        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.pack(fill='x')
        row = ttk.Frame(outer)
        row.pack(fill='x', pady=(s(12), 0))
        self.cancel_btn = ttk.Button(row, text='Cancel', command=self._cancel)
        self.cancel_btn.pack(side='left')
        self.finish_btn = ttk.Button(row, text='Use SSH for this repository', command=self._finish, state='disabled')
        self.finish_btn.pack(side='right')
        self._poll_id = self.after(100, self._poll)
        self.wait_visibility()
        self.grab_set()
        self.wait_window()
        if master.winfo_exists():
            master.grab_set()

    @staticmethod
    def _label(page, text):
        ttk.Label(page, text=text, wraplength=s(565), justify='left').pack(anchor='w', pady=(0, s(10)))

    @staticmethod
    def _text(widget, text):
        widget.config(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', text)
        widget.config(state='disabled')

    def _invalidate(self):
        self._command = None
        if hasattr(self, 'finish_btn'):
            self.finish_btn.config(state='disabled')

    def _key_changed(self, *args):
        self._invalidate()
        self._public = ''
        if hasattr(self, 'public_text'):
            self._text(self.public_text, '')

    def _confirmation_changed(self, *args):
        self._invalidate()

    def _key_done(self, result):
        path, value = result
        self.key_var.set(path)
        self._public = value
        self._text(self.public_text, value)
        self.tabs.select(1)
        self.status_var.set('Public key ready. Add it to your account before testing access.')

    def _create(self):
        if self._busy:
            return
        paths = key_paths()
        overwrite = any(os.path.lexists(path) for path in paths)
        if overwrite and not messagebox.askyesno(
                'Replace existing SSH keys?',
                'Creating a new key will replace these SSH key files:\n\n'
                + '\n'.join(str(path) for path in paths)
                + '\n\nAccess using the old key may stop working. You will need to add the new '
                'public key to your Git account. Replace the existing keys?',
                parent=self, default=messagebox.NO, icon=messagebox.WARNING):
            return
        self._job(lambda: create_key(self.email, overwrite=overwrite),
                  self._key_done, 'Creating a new SSH key…')

    def _browse(self):
        value = filedialog.askopenfilename(parent=self, title='Select private SSH key',
                                          initialdir=os.path.expanduser('~/.ssh'))
        if value:
            self.key_var.set(value)

    def _load_key(self):
        path = os.path.abspath(os.path.expanduser(self.key_var.get().strip()))
        self._job(lambda: (path, public_key(path)), self._key_done, 'Reading the public key…')

    def _copy(self):
        if not self._public:
            messagebox.showinfo('Select a key first', 'Create or select a key on the first tab.', parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(self._public)
        self.status_var.set('Public key copied. Paste it into your account’s SSH key form.')

    def _scan(self):
        self._candidate = None
        self.confirm_var.set(False)
        self._text(self.fingerprint_text, '')
        def done(candidate):
            self._candidate = candidate
            self._text(self.fingerprint_text, '{}:{} ({})\n{}'.format(
                candidate['host'], candidate['port'], candidate['kind'], candidate['fingerprint']))
            self.status_var.set('Compare this fingerprint before selecting the confirmation box.')
        self._job(lambda: scan_host(self.url), done, 'Fetching the server fingerprint…')

    def _test(self):
        if not self._public or not self._candidate or not self.confirm_var.get():
            messagebox.showinfo('Finish SSH setup', 'Select a key, add its public key to your account, '
                                'then fetch and confirm the server fingerprint.', parent=self)
            return
        key, candidate = self.key_var.get(), dict(self._candidate)
        self._invalidate()
        def run():
            known_hosts = trust_host(candidate)
            return test_repository(self.url, ssh_command(key, known_hosts))
        def done(command):
            self._command = command
            self.finish_btn.config(state='normal')
            self.status_var.set('SSH repository access confirmed. You can now use SSH for this repository.')
        self._job(run, done, 'Testing SSH access to your repository…')

    def _agent_help(self):
        try:
            tools = ssh_tools()
        except Exception as exc:
            messagebox.showerror('OpenSSH tools', str(exc), parent=self)
            return
        windows = 'system32' in tools['ssh'].lower()
        instructions = (
            'Ask your administrator to enable the Windows OpenSSH Authentication Agent. '
            'In an administrator PowerShell window:\n\n'
            'Set-Service -Name ssh-agent -StartupType Automatic\nStart-Service ssh-agent\n\n'
            'Then, in a normal PowerShell window, run ssh-add followed by your private key path '
            'in double quotes. Enter its passphrase there, and return to GCAD to test access.'
            if windows else
            'Open Git Bash and run:\n\neval "$(ssh-agent -s)"\nssh-add /path/to/your/private-key\n\n'
            'Enter the passphrase there. Launch GCAD from that same Git Bash window so it inherits '
            'the agent connection, then select the key and test again.')
        messagebox.showinfo('Using an encrypted key', instructions + '\n\n'
                            'To create an encrypted key manually, run ssh-keygen -t ed25519 in that '
                            'terminal, choose a NEW filename, and enter a passphrase when asked. '
                            'Keep its matching .pub file alongside it. GCAD never stores your passphrase.', parent=self)

    def _job(self, operation, callback, message):
        if self._busy:
            return
        self._busy = True
        self._controls(False)
        self.status_var.set(message)
        self.progress.start(12)
        def worker():
            try:
                self._events.put((callback, operation(), None))
            except Exception as exc:
                self._events.put((callback, None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _controls(self, enabled):
        def update(parent):
            for widget in parent.winfo_children():
                if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Checkbutton)):
                    widget.config(state='normal' if enabled else 'disabled')
                update(widget)
        update(self)
        self.finish_btn.config(state='normal' if enabled and self._command else 'disabled')

    def _poll(self):
        try:
            callback, value, error = self._events.get_nowait()
        except queue.Empty:
            pass
        else:
            self._busy = False
            self.progress.stop()
            self._controls(True)
            if error is not None:
                self.status_var.set('Review the instructions, correct the problem, and try again.')
                messagebox.showerror('SSH setup needs attention', error, parent=self)
            else:
                callback(value)
        if self.winfo_exists():
            self._poll_id = self.after(100, self._poll)

    def _finish(self):
        if not self._busy and self._command:
            self.on_complete(self._command)
            self.destroy()

    def _cancel(self):
        if not self._busy:
            self.destroy()

    def destroy(self):
        callback = getattr(self, '_poll_id', None)
        if callback:
            self.after_cancel(callback)
        super().destroy()
