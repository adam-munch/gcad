import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

import ttkbootstrap as tb

from dpi import s
from setup_ops import (check_requirements, install_requirements, get_identity,
                       validate_identity, validate_repository, prepare_repository)
from git_ops import get_remote_url
from ssh_setup import parse_ssh_url
from ui.ssh_dialog import SSHSetupDialog
from progress import operation_progress


class SetupWizard(tb.Toplevel):
    """Modal setup with all subprocess work off the Tk thread."""

    def __init__(self, master, on_complete, allow_skip=True):
        super().__init__(master)
        self.on_complete = on_complete
        self.result = None
        self._busy = False
        self._events = queue.Queue()
        self._step = 0
        self._requirements = None
        self._ssh_setup = None
        self.title('GCAD Setup' if allow_skip else 'New Repository')
        self.resizable(False, False)
        self.transient(master)
        self.protocol('WM_DELETE_WINDOW', self._cancel)
        self.bind('<Escape>', lambda event: self._cancel())

        self.name_var = tk.StringVar()
        self.email_var = tk.StringVar()
        self.url_var = tk.StringVar()
        self.path_var = tk.StringVar(value=os.path.expanduser('~/CADRepo'))
        self.existing_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar()

        outer = ttk.Frame(self, padding=s(24))
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Welcome to GCAD' if allow_skip else 'Set up a repository',
                  font=('', s(18), 'bold')).pack(anchor='w')
        self.step_label = ttk.Label(outer)
        self.step_label.pack(anchor='w', pady=(s(6), s(18)))
        self.body = ttk.Frame(outer, width=s(570), height=s(330))
        self.body.pack(fill='both', expand=True)
        self.body.pack_propagate(False)
        ttk.Separator(outer).pack(fill='x', pady=s(12))
        ttk.Label(outer, textvariable=self.status_var, wraplength=s(560)).pack(anchor='w')
        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.pack(fill='x', pady=s(8))
        buttons = ttk.Frame(outer)
        buttons.pack(fill='x')
        self.cancel_btn = ttk.Button(buttons, text='Cancel', command=self._cancel)
        self.cancel_btn.pack(side='left')
        self.next_btn = ttk.Button(buttons, text='Next', command=self._next)
        self.next_btn.pack(side='right')
        self.back_btn = ttk.Button(buttons, text='Back', command=self._back)
        self.back_btn.pack(side='right', padx=s(8))
        self._render()
        self._poll_id = self.after(100, self._poll)
        self._check_id = self.after(150, self._check_tools)
        self.wait_visibility()
        self.grab_set()
        self.lift()
        self.wait_window()

    def _label(self, text):
        ttk.Label(self.body, text=text, wraplength=s(550), justify='left').pack(
            anchor='w', pady=(0, s(10)))

    def _render(self):
        for widget in self.body.winfo_children():
            widget.destroy()
        self.status_var.set('')
        titles = ('Required tools', 'Your name and email', 'Your CAD repository', 'Ready to work')
        self.step_label.config(text='Step {} of 4 · {}'.format(self._step + 1, titles[self._step]))
        self.back_btn.config(state='normal' if 0 < self._step < 3 else 'disabled')
        self.next_btn.config(text='Open GCAD' if self._step == 3 else
                             'Set up repository' if self._step == 2 else 'Next', state='normal')
        self.cancel_btn.config(state='normal')
        if self._step == 0:
            self._label('GCAD uses Git to sync your files and Git LFS to manage large CAD files. '
                        'We will check this computer and help install anything missing.')
            self.tools_label = ttk.Label(self.body, text='Checking required tools…', wraplength=s(550))
            self.tools_label.pack(anchor='w', pady=s(10))
            actions = ttk.Frame(self.body)
            actions.pack(fill='x', pady=s(8))
            self.install_btn = ttk.Button(actions, text='Install missing tools', command=self._install_tools)
            self.install_btn.pack(side='left')
            ttk.Button(actions, text='Check again', command=self._check_tools).pack(side='left', padx=s(8))
            self._label('Installation uses Windows Package Manager and accepts the tools’ license '
                        'agreements. Windows may ask for administrator approval. This can take several minutes.')
            self._label('If automatic installation is unavailable, download the tools, keep the '
                        'installer defaults, then click Check again.')
            downloads = ttk.Frame(self.body)
            downloads.pack(fill='x')
            ttk.Button(downloads, text='Download Git', command=lambda: webbrowser.open(
                'https://git-scm.com/download/win')).pack(side='left')
            ttk.Button(downloads, text='Download Git LFS', command=lambda: webbrowser.open(
                'https://git-lfs.com/')).pack(side='left', padx=s(8))
            self._display_requirements()
        elif self._step == 1:
            self._label('Your teammates will see this name and email beside the changes you save. '
                        'These settings apply to this repository only.')
            self._label('Name')
            name = ttk.Entry(self.body, textvariable=self.name_var)
            name.pack(fill='x', pady=(0, s(14)))
            self._label('Email address')
            ttk.Entry(self.body, textvariable=self.email_var).pack(fill='x', pady=(0, s(14)))
            self._label('Use the email associated with your Git account, or your Git host’s private '
                        'email address. This is not a password or sign-in form.')
            name.focus_set()
        elif self._step == 2:
            ttk.Radiobutton(self.body, text='Download a repository', variable=self.existing_var,
                            value=False, command=self._repository_mode).pack(anchor='w')
            ttk.Radiobutton(self.body, text='Use an existing folder', variable=self.existing_var,
                            value=True, command=self._repository_mode).pack(anchor='w', pady=(0, s(10)))
            self._label('Repository link (HTTPS or SSH)')
            self.url_entry = ttk.Entry(self.body, textvariable=self.url_var)
            self.url_entry.pack(fill='x', pady=(0, s(10)))
            self._label('Folder for your CAD files')
            folder = ttk.Frame(self.body)
            folder.pack(fill='x', pady=(0, s(12)))
            ttk.Entry(folder, textvariable=self.path_var).pack(side='left', fill='x', expand=True)
            ttk.Button(folder, text='Browse…', command=self._browse).pack(side='right', padx=(s(8), 0))
            ttk.Button(self.body, text='Set up SSH access…', command=self._setup_ssh).pack(anchor='w', pady=(0, s(10)))
            self._label('HTTPS uses Git’s browser sign-in. For SSH, paste your team’s SSH clone link '
                        'and click Set up SSH access to create a key and connect your account.')
            self._label('Downloading requires a new or empty folder. If a previous download stopped '
                        'after creating the repository, choose Use an existing folder to continue.')
            self._repository_mode()
        else:
            self._label('Your repository is ready. Click Open GCAD to save setup and load your files.')
            self._label('CAD folder: ' + self.result['local_path'])
            self._label('Saved changes will be credited to {} <{}>.'.format(
                self.name_var.get().strip(), self.email_var.get().strip()))
            self._label('Select a file and click Lock before editing. When you are finished, '
                        'click Push to save your changes for the team and release the lock.')

    def _repository_mode(self):
        self.url_entry.config(state='disabled' if self.existing_var.get() else 'normal')

    def _setup_ssh(self):
        def open_dialog(url):
            try:
                parse_ssh_url(url or '')
            except Exception as exc:
                messagebox.showerror('SSH repository link needed', str(exc), parent=self)
                return
            def done(command):
                self._ssh_setup = (url, command)
                self.status_var.set('SSH access tested. Continue with Set up repository.')
            SSHSetupDialog(self, url, self.email_var.get().strip(), done)
        if self.existing_var.get():
            path = self.path_var.get().strip()
            self._work(lambda: get_remote_url(path), open_dialog, 'Reading the repository’s SSH link…')
        else:
            open_dialog(self.url_var.get().strip())

    def _browse(self):
        path = filedialog.askdirectory(parent=self, title='Choose your CAD folder')
        if path:
            self.path_var.set(path)

    def _display_requirements(self):
        ready = self._requirements and self._requirements['git'] and self._requirements['lfs']
        self.next_btn.config(state='normal' if ready else 'disabled')
        self.install_btn.config(state='disabled' if ready or not self._requirements else 'normal')
        if self._requirements:
            self.tools_label.config(text='Git: {}\nGit LFS: {}'.format(
                'Ready' if self._requirements['git'] else 'Needs installation',
                'Ready' if self._requirements['lfs'] else 'Needs installation'))

    def _set_busy(self, busy):
        self._busy = busy
        def update_widgets(parent):
            for widget in parent.winfo_children():
                if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Radiobutton)):
                    widget.config(state='disabled' if busy else 'normal')
                update_widgets(widget)
        update_widgets(self.body)
        for button in (self.back_btn, self.next_btn, self.cancel_btn):
            button.config(state='disabled' if busy else 'normal')
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()
            self.back_btn.config(state='normal' if 0 < self._step < 3 else 'disabled')
            if self._step == 0:
                self._display_requirements()
            elif self._step == 2:
                self._repository_mode()

    def _work(self, operation, on_done, message):
        if self._busy:
            return
        self._set_busy(True)
        self.status_var.set(message)
        def worker():
            try:
                with operation_progress(lambda message, *_: self._events.put((None, message, None))):
                    result = operation()
                self._events.put((on_done, result, None))
            except Exception as exc:
                self._events.put((on_done, None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            callback, result, error = self._events.get_nowait()
        except queue.Empty:
            pass
        else:
            if callback is None:
                self.status_var.set(result[:240])
                self._poll_id = self.after(20, self._poll)
                return
            self._set_busy(False)
            if error is not None:
                self.status_var.set('Setup could not finish. Review the message and try again.')
                messagebox.showerror('Setup needs attention', error, parent=self)
            else:
                self.status_var.set('')
                callback(result)
        if self.winfo_exists():
            self._poll_id = self.after(100, self._poll)

    def _tools_done(self, requirements):
        self._requirements = requirements
        self._display_requirements()

    def _check_tools(self):
        self._work(check_requirements, self._tools_done, 'Checking Git and Git LFS…')

    def _install_tools(self):
        self._work(install_requirements, self._tools_done,
                   'Installing required tools… Complete any Windows approval prompt that appears.')

    def _next(self):
        if self._busy:
            return
        if self._step == 0:
            if not self._requirements or not all(self._requirements[key] for key in ('git', 'lfs')):
                return
            def identity_done(identity):
                if not self.name_var.get():
                    self.name_var.set(identity[0])
                if not self.email_var.get():
                    self.email_var.set(identity[1])
                self._step = 1
                self._render()
            self._work(get_identity, identity_done, 'Reading your existing Git settings…')
        elif self._step == 1:
            try:
                validate_identity(self.name_var.get().strip(), self.email_var.get().strip())
            except Exception as exc:
                messagebox.showerror('Check your details', str(exc), parent=self)
                return
            self._step = 2
            self._render()
        elif self._step == 2:
            url, path = self.url_var.get().strip(), self.path_var.get().strip()
            existing = self.existing_var.get()
            name, email = self.name_var.get().strip(), self.email_var.get().strip()
            try:
                path = validate_repository(url, path, existing)
            except Exception as exc:
                messagebox.showerror('Check your repository', str(exc), parent=self)
                return
            def repository_done(config):
                self.result = config
                self._step = 3
                self._render()
            ssh_setup = self._ssh_setup
            def prepare():
                remote = get_remote_url(path) if existing else url
                command = ssh_setup[1] if ssh_setup and ssh_setup[0] == remote else None
                return prepare_repository(url, path, name, email, existing, ssh_command=command)
            self._work(prepare, repository_done,
                       'Preparing your CAD files… Complete Git’s sign-in prompt if one appears.')
        else:
            try:
                self.on_complete(self.result)
            except Exception as exc:
                messagebox.showerror('Could not save setup',
                                     'Your repository is ready, but GCAD could not save its settings. '
                                     'Check folder permissions and try Open GCAD again.\n\n' + str(exc), parent=self)
                return
            self.destroy()

    def _back(self):
        if not self._busy and 0 < self._step < 3:
            self._step -= 1
            self._render()

    def _cancel(self):
        if self._busy:
            return
        self.destroy()

    def destroy(self):
        for name in ('_poll_id', '_check_id'):
            callback = getattr(self, name, None)
            if callback:
                self.after_cancel(callback)
        super().destroy()
