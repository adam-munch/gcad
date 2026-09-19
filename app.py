import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as ttk
import os
import sys
import queue
import threading

import ttkbootstrap as tb

from dpi import s
from config import load_config, save_config
from setup_ops import refresh_tool_path
from git_ops import (
    check_git, check_git_lfs, pull_repo, get_file_statuses,
    lock_files, unlock_files, commit_and_push, restore_files,
    hard_reset_repo, install_lfs, checkout_branch,
    get_current_branch, get_repo_name, clone_repo,
    GitError,
)
from ui.file_table import FileTable
from ui.toolbar import Toolbar
from ui.activity import ActivityPanel
from ui.theme import ThemeManager, THEME_OPTIONS
from progress import operation_progress, report
from ui.dialogs import SetupWizard, CommitDialog, show_error, show_info, show_confirm, _raise_on_top


class App:
    def __init__(self, theme=None):
        if sys.platform == 'win32':
            # Give source and packaged launches their own Windows taskbar group.
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MMR.GCAD')
        self.root = tb.Window(themename='flatly')
        self._set_app_icon()
        saved = load_config() or {}
        self.theme = ThemeManager(self.root, theme or saved.get('theme', 'system'))
        self.root.title('GCAD - Git for CAD')
        self.root.geometry('{}x{}+{}+{}'.format(
            min(s(1100), self.root.winfo_screenwidth() - s(60)),
            min(s(800), self.root.winfo_screenheight() - s(100)), s(20), s(10)))
        self.root.minsize(s(900), s(700))

        self.config = None
        self._busy = False
        self._status_text = 'Ready'
        self._op_queue = queue.Queue()

    def _start(self):
        self.config = load_config()
        if not self.config or not self._is_repo_path(self.config.get('local_path')):
            # First launch, deleted/corrupt configuration, or a moved repository.
            # The wizard must open before checking prerequisites: it installs them.
            self.config = None
            self.root.deiconify()
            SetupWizard(self.root, self._on_setup_complete)
            if not self.config:
                self.root.destroy()
                return
        else:
            refresh_tool_path()
            git_ok, git_msg = check_git()
            if not git_ok:
                self._abort_startup('Git Not Found', git_msg)
                return
            lfs_ok, lfs_msg = check_git_lfs()
            if not lfs_ok:
                self._abort_startup('Git LFS Not Found', lfs_msg)
                return

        self._build_ui()
        self.root.deiconify()
        self.root.after(100, self._process_queue)
        self._refresh()
        self.root.after(500, self._initial_pull)

    def _abort_startup(self, title, message):
        self.root.deiconify()
        show_error(title, message, parent=self.root)
        self.root.destroy()

    def _safe_start(self):
        try:
            self._start()
        except Exception as e:
            self._abort_startup(
                'Startup Error',
                'GCAD could not finish starting.\n\n{}'.format(str(e)),
            )

    @staticmethod
    def _is_repo_path(repo_path):
        if not isinstance(repo_path, str) or not repo_path:
            return False
        if not os.path.isdir(repo_path):
            return False
        git_dir = os.path.join(repo_path, '.git')
        # A linked Git worktree has a .git file rather than a directory.
        return os.path.isdir(git_dir) or os.path.isfile(git_dir)

    def _on_setup_complete(self, config):
        config = dict(config, theme=self.theme.preference)
        save_config(config)
        self.config = config

    def _on_clone_repo(self):
        if self._busy:
            return
        SetupWizard(self.root, self._on_clone_complete, allow_skip=False)

    def _on_clone_complete(self, config):
        config = dict(config, theme=self.theme.preference)
        save_config(config)
        self.config = config
        self._set_status('Switched to repository: {}'.format(
            os.path.basename(config.get('local_path', ''))))
        self._refresh()

    def _build_ui(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label='New Repository...', command=self._on_clone_repo)
        file_menu.add_command(label='Settings...', command=self._show_settings)
        file_menu.add_separator()
        file_menu.add_command(label='Hard Reset...', command=self._on_hard_reset)
        file_menu.add_separator()
        file_menu.add_command(label='Exit', command=self._on_close)
        self.file_menu = file_menu
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        menubar.add_cascade(label='File', menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label='About GCAD', command=self._show_about)
        menubar.add_cascade(label='Help', menu=help_menu)

        header = ttk.Frame(self.root, padding=(s(16), s(8)))
        header.pack(fill='x')
        header.columnconfigure(0, weight=1)
        self.branch_label = ttk.Label(header, text='Loading repository…', font=('Segoe UI', 12, 'bold'))
        self.branch_label.grid(row=0, column=0, sticky='ew', padx=(0, s(12)))
        self.repo_label = ttk.Label(header, text=self._repo_path(), bootstyle='secondary', anchor='w')
        self.repo_label.grid(row=1, column=0, sticky='ew', padx=(0, s(12)))
        appearance = ttk.Frame(header)
        appearance.grid(row=0, column=1, rowspan=2, sticky='e')
        ttk.Label(appearance, text='Appearance', bootstyle='secondary').pack(side='left', padx=(0, s(6)))
        self.theme_var = tk.StringVar(value=next(label for label, value in THEME_OPTIONS.items()
                                               if value == self.theme.preference))
        self.theme_picker = ttk.Combobox(appearance, textvariable=self.theme_var,
                                        values=list(THEME_OPTIONS), state='readonly', width=14)
        self.theme_picker.pack(side='left')
        self.theme_picker.bind('<<ComboboxSelected>>', self._change_theme)

        summary = ttk.Frame(self.root)
        summary.pack(fill='x', padx=s(16), pady=(0, s(6)))
        self.summary_labels = {}
        for column, (key, label, color) in enumerate((('total', 'FILES', 'primary'),
                ('changed', 'CHANGED', 'warning'), ('mine', 'LOCKED BY YOU', 'info'),
                ('others', 'LOCKED BY TEAM', 'danger'))):
            card = ttk.Frame(summary, padding=(s(10), s(4)), style='Card.TFrame')
            card.grid(row=0, column=column, sticky='ew', padx=(0 if column == 0 else s(6), 0))
            summary.columnconfigure(column, weight=1, uniform='cards')
            ttk.Label(card, text=label, font=('Segoe UI', 9, 'bold'), style='Muted.Card.TLabel').pack(side='left')
            value = ttk.Label(card, text='—', style=color + '.Metric.TLabel')
            value.pack(side='right', padx=(s(8), 0))
            self.summary_labels[key] = value

        self.toolbar = Toolbar(self.root)
        self.toolbar.pack(fill='x', padx=s(14), pady=(0, s(4)))

        self.toolbar.set_command('refresh', self._on_refresh)
        self.toolbar.set_command('pull', self._on_pull)
        self.toolbar.set_command('commit_push', self._on_commit_push)
        self.toolbar.set_command('restore', self._on_restore)
        self.toolbar.set_command('lock', self._on_lock)
        self.toolbar.set_command('unlock', self._on_unlock)
        self.toolbar.set_command('open_file', self._on_open_file)
        self.toolbar.set_command('open_folder', self._on_open_folder)

        # Pack feedback first so it remains visible when the file area shrinks.
        self.activity = ActivityPanel(self.root)
        self.activity.pack(side='bottom', fill='x', padx=s(16), pady=(s(6), s(8)))

        files_header = ttk.Frame(self.root)
        files_header.pack(fill='x', padx=s(16), pady=(0, s(4)))
        ttk.Label(files_header, text='Repository files', font=('Segoe UI', 10, 'bold')).pack(side='left')
        self.selection_label = ttk.Label(files_header, text='Select files or folders to get started', bootstyle='secondary')
        self.selection_label.pack(side='right')
        self.file_table = FileTable(self.root, on_file_select=self._selection_changed)
        self.file_table.pack(fill='both', expand=True, padx=s(16))

        self._selection_changed([])

    def _change_theme(self, event=None):
        preference = THEME_OPTIONS[self.theme_var.get()]
        settings = dict(self.config, theme=preference)
        try:
            save_config(settings)
        except OSError as exc:
            self.theme_var.set(next(label for label, value in THEME_OPTIONS.items()
                                    if value == self.theme.preference))
            show_error('Appearance could not be saved', str(exc), parent=self.root)
            return
        self.config = settings
        self.theme.set_preference(preference)

    def _selection_changed(self, selected):
        count = len(selected)
        self.selection_label.configure(text='{} file{} selected'.format(count, '' if count == 1 else 's')
                                       if count else 'Select files or folders to get started')
        if not self._busy:
            for key in ('lock', 'unlock', 'commit_push', 'restore'):
                self.toolbar.set_enabled(key, bool(count))
            self.toolbar.set_enabled('open_file', count == 1 and selected[0]['status'] != 'deleted')
            self.toolbar.set_enabled('open_folder', count == 1)

    def _populate(self, statuses):
        self.file_table.populate(statuses)
        counts = dict(total=len(statuses),
                      changed=sum(f['status'] not in ('unchanged', 'locked_by_me', 'locked_by_other') for f in statuses),
                      mine=sum(f['status'].startswith('locked_by_me') for f in statuses),
                      others=sum(f['status'].startswith('locked_by_other') for f in statuses))
        for key, value in counts.items():
            if key in ('mine', 'others') and any(not f.get('locks_verified', True) for f in statuses):
                value = '—'
            self.summary_labels[key].configure(text=str(value))
        self._selection_changed(self.file_table.get_selected_files())

    def _on_close(self):
        if self._busy:
            self.activity.hint.configure(text='Please wait for this operation to finish before closing GCAD.')
            self.root.bell()
            return
        self.root.destroy()

    def _read_repo_title(self):
        """Read Git metadata on the worker, along with the file status scan."""
        repo_path = self._repo_path()
        branch = get_current_branch(repo_path)
        return get_repo_name(repo_path), '(detached)' if branch == 'HEAD' else branch

    def _update_title(self, metadata=None):
        if metadata:
            name, branch = metadata
            self.root.title('GCAD - {} [{}]'.format(name, branch))
            self.branch_label.configure(text='{}  /  {}'.format(name, branch))
            self.repo_label.configure(text=self._repo_path())

    def _process_queue(self):
        try:
            while True:
                fn = self._op_queue.get_nowait()
                fn()
        except queue.Empty:
            pass
        self.root.after(100, self._process_queue)

    def _enqueue(self, fn):
        self._op_queue.put(fn)

    def _async(self, fn, on_done=None, on_error=None, title='Refreshing files'):
        if self._busy:
            return
        def progress(message, completed=None, total=None, level='info'):
            self._enqueue(lambda: self.activity.update_progress(message, completed, total, level))

        def finish(result, metadata, error):
            try:
                if error is not None:
                    self.activity.finish(str(error) + '\nEarlier steps may have completed. Refresh to check the current file state.', error=True)
                    if on_error:
                        on_error(error)
                else:
                    self._update_title(metadata)
                    if on_done:
                        on_done(result)
                    self.activity.finish(self._status_text)
            except Exception as exc:
                self.activity.finish('Could not update the display. Try Refresh.\n' + str(exc), error=True)
            finally:
                self._set_busy(False)

        def wrapper():
            result, metadata, error = None, None, None
            try:
                with operation_progress(progress):
                    result = fn()
                    try:
                        metadata = self._read_repo_title()
                    except GitError as exc:
                        report('Could not read repository details: ' + str(exc), level='warning')
            except Exception as exc:
                error = exc
            finally:
                self._enqueue(lambda: finish(result, metadata, error))

        self._set_busy(True)
        self._status_text = 'Operation completed.'
        self.activity.begin(title)
        t = threading.Thread(target=wrapper, daemon=True)
        t.start()

    def _set_busy(self, busy):
        self._busy = busy
        self.theme_picker.configure(state='disabled' if busy else 'readonly')
        if busy:
            self.toolbar.set_all_enabled(False)
        else:
            self.toolbar.enable_defaults()
            self._selection_changed(self.file_table.get_selected_files())
        for index in (0, 1, 3):
            self.file_menu.entryconfigure(index, state='disabled' if busy else 'normal')

    def _set_status(self, text):
        self._status_text = text
        if not self._busy:
            self.activity.heading.configure(text='Ready to work', style='secondary.Card.TLabel')
            self.activity.detail.configure(text=text)

    def _repo_path(self):
        return self.config.get('local_path', '')

    def _assert_repo(self):
        if self._busy:
            return None
        repo_path = self._repo_path()
        if not self._is_repo_path(repo_path):
            show_error('No Repository',
                'No repository is configured.\n\n'
                'Go to File > Settings to configure one.')
            return None
        return repo_path

    def _initial_pull(self):
        if self._busy or self.root.grab_current():
            self.root.after(200, self._initial_pull)
            return
        repo_path = self._repo_path()
        if self._is_repo_path(repo_path):
            self._on_pull()

    def _on_refresh(self):
        self._refresh()

    def _on_open_file(self):
        self._open_selected_path()

    def _on_open_folder(self):
        self._open_selected_path(containing_folder=True)

    def _open_selected_path(self, containing_folder=False):
        repo_path = self._assert_repo()
        if not repo_path:
            return
        selected = self.file_table.get_selected_files()
        if len(selected) != 1:
            show_error('Select One File', 'Please select exactly one file to open.', parent=self.root)
            return

        path = os.path.abspath(os.path.join(repo_path, selected[0]['path']))
        if containing_folder:
            path = os.path.dirname(path)
        exists = os.path.isdir(path) if containing_folder else os.path.isfile(path)
        if not exists:
            show_error('Cannot Open', 'The {} no longer exists:\n\n{}'.format(
                'folder' if containing_folder else 'file', path), parent=self.root)
            return
        if not containing_folder and not selected[0]['status'].startswith('locked_by_me'):
            if not show_confirm(
                'Open Read-Only File?',
                'This file is not locked by you and will be read-only.\n\n'
                '{}\n\nDo you want to continue?'.format(selected[0]['path']),
                parent=self.root,
            ):
                return
        try:
            os.startfile(path)
        except OSError as exc:
            show_error('Cannot Open', 'Windows could not open:\n\n{}\n\n{}'.format(path, exc),
                       parent=self.root)

    def _refresh(self):
        repo_path = self._assert_repo()
        if not repo_path:
            return

        def do_refresh():
            install_lfs(repo_path)
            return get_file_statuses(repo_path)

        def on_done(statuses):
            self._populate(statuses)
            total = len(statuses)
            locked = sum(1 for s in statuses if 'locked' in s['status'])
            modified = sum(1 for s in statuses if 'modified' in s['status'])
            deleted = sum(1 for s in statuses if s['status'] == 'deleted')
            file_new = sum(1 for s in statuses if s['status'] == 'new')
            conflicted = sum(1 for s in statuses if s['status'] == 'conflicted')
            ready = sum(f['status'] == 'unchanged' and f.get('locks_verified', True) for f in statuses)
            parts = ['{} files'.format(total), '{} ready'.format(ready)]
            if modified:
                parts.append('{} modified'.format(modified))
            if file_new:
                parts.append('{} new'.format(file_new))
            if deleted:
                parts.append('{} deleted'.format(deleted))
            if conflicted:
                parts.append('{} conflicted'.format(conflicted))
            if locked:
                parts.append('{} locked'.format(locked))
            if any(not f.get('locks_verified', True) for f in statuses):
                parts.append('lock ownership unavailable')
            self._set_status(' \u2014 '.join(parts))

        self._async(do_refresh, on_done=on_done, title='Refreshing files')

    def _on_pull(self):
        repo_path = self._assert_repo()
        if not repo_path:
            return

        def do_pull():
            install_lfs(repo_path)
            pull_repo(repo_path)
            return get_file_statuses(repo_path)

        def on_done(statuses):
            self._populate(statuses)
            self._set_status('Pull complete.')

        self._async(do_pull, on_done=on_done, title='Pulling latest changes')

    def _on_lock(self):
        repo_path = self._assert_repo()
        if not repo_path:
            return

        selected = self.file_table.get_selected_files()
        if not selected:
            show_error('No Selection', 'Please select one or more files to lock.')
            return

        non_lfs = [f['path'] for f in selected if not f['is_lfs']]
        deleted = [f['path'] for f in selected if f['status'] == 'deleted']
        already_locked = [f['path'] for f in selected if f['status'].startswith('locked_by_me')]
        locked_other = [f['path'] for f in selected if f['status'].startswith('locked_by_other')]
        conflicted = [f['path'] for f in selected if f['status'] == 'conflicted']

        if non_lfs or deleted or already_locked or locked_other or conflicted:
            parts = []
            if non_lfs:
                parts.append('Not tracked by Git LFS:\n  ' + '\n  '.join(non_lfs))
            if deleted:
                parts.append('Deleted:\n  ' + '\n  '.join(deleted))
            if already_locked:
                parts.append('Already locked by you:\n  ' + '\n  '.join(already_locked))
            if locked_other:
                parts.append('Locked by another user:\n  ' + '\n  '.join(locked_other))
            if conflicted:
                parts.append('Has merge conflicts:\n  ' + '\n  '.join(conflicted))
            show_error('Cannot Lock', '\n\n'.join(parts))
            return

        paths = [f['path'] for f in selected]

        def do_lock():
            lock_files(repo_path, paths)
            return get_file_statuses(repo_path)

        def on_done(statuses):
            self._populate(statuses)
            self._set_status('Locked {} file(s).'.format(len(paths)))

        self._async(do_lock, on_done=on_done, title='Locking files')

    def _on_unlock(self):
        repo_path = self._assert_repo()
        if not repo_path:
            return

        selected = self.file_table.get_selected_files()
        if not selected:
            show_error('No Selection', 'Please select one or more files to unlock.')
            return

        locked_by_me = [
            f for f in selected
            if f['status'] in ('locked_by_me', 'locked_by_me_new', 'locked_by_me_modified')
        ]
        if not locked_by_me:
            show_error('Cannot Unlock',
                'None of the selected files are locked by you.')
            return

        has_modified = any(f['status'] == 'locked_by_me_modified' for f in locked_by_me)
        has_new = any(f['status'] == 'locked_by_me_new' for f in locked_by_me)

        if has_modified:
            show_error('Cannot Unlock',
                'Some files have uncommitted changes.\n\n'
                '  \u2022 Push the files to save and auto-unlock\n'
                '  \u2022 Restore to discard changes, then unlock')
            return

        force = False
        if has_new:
            if not show_confirm('Unlock New File?',
                'New files that are locked but not yet committed have\n'
                'uncommitted changes. Git LFS needs to force-unlock them.\n\n'
                'The file will remain on disk. Continue?'
            ):
                return
            force = True

        paths = [f['path'] for f in locked_by_me]

        def do_unlock():
            unlock_files(repo_path, paths, force=force)
            return get_file_statuses(repo_path)

        def on_done(statuses):
            self._populate(statuses)
            self._set_status('Unlocked {} file(s).'.format(len(paths)))

        self._async(do_unlock, on_done=on_done, title='Unlocking files')

    def _on_commit_push(self):
        repo_path = self._assert_repo()
        if not repo_path:
            return

        selected = self.file_table.get_selected_files()
        if not selected:
            show_error('No Selection',
                'Please select modified or deleted files to commit.')
            return

        to_commit = [f for f in selected if f['status'] in (
            'modified', 'new', 'deleted', 'locked_by_me_new', 'locked_by_me_modified')]
        if not to_commit:
            show_error('No Changes',
                'None of the selected files have changes to commit.')
            return

        dlg = CommitDialog(self.root, to_commit)
        msg = dlg.result
        if not msg:
            return

        paths = [f['path'] for f in to_commit]
        deleted_paths = [f['path'] for f in to_commit if f['status'] == 'deleted']

        def do_commit():
            install_lfs(repo_path)
            pull_repo(repo_path)
            commit_and_push(repo_path, paths, msg, deleted_paths=deleted_paths,
                            unlock_paths=[f['path'] for f in to_commit if f['status'].startswith('locked_by_me')])
            return get_file_statuses(repo_path)

        def on_done(statuses):
            self._populate(statuses)
            self._set_status(
                'Committed and pushed {} file(s).'.format(len(paths))
            )

        self._async(do_commit, on_done=on_done, title='Saving and pushing changes')

    def _on_restore(self):
        repo_path = self._assert_repo()
        if not repo_path:
            return

        selected = self.file_table.get_selected_files()
        if not selected:
            show_error('No Selection', 'Please select modified or deleted files to restore.')
            return

        modified = [f for f in selected if f['status'] in ('modified', 'deleted', 'locked_by_me_modified')]
        if not modified:
            show_error('No Changes',
                'None of the selected files have uncommitted changes to discard.')
            return

        if not show_confirm(
            'Discard Changes',
            'This will discard all uncommitted changes for the selected files.\n\n'
            'This cannot be undone. Continue?'
        ):
            return

        paths = [f['path'] for f in modified]

        def do_restore():
            restore_files(repo_path, paths)
            return get_file_statuses(repo_path)

        def on_done(statuses):
            self._populate(statuses)
            self._set_status('Restored {} file(s).'.format(len(paths)))

        self._async(do_restore, on_done=on_done, title='Restoring files')

    def _on_hard_reset(self):
        repo_path = self._assert_repo()
        if not repo_path:
            return

        if not show_confirm(
            'Hard Reset',
            'This will discard ALL local changes and reset the repository\n'
            'to match the remote branch.\n\n'
            'This cannot be undone. Continue?'
        ):
            return

        def do_reset():
            hard_reset_repo(repo_path)
            return get_file_statuses(repo_path)

        def on_done(statuses):
            self._populate(statuses)
            self._set_status('Hard reset complete.')

        self._async(do_reset, on_done=on_done, title='Resetting repository')

    def _show_settings(self):
        if self._busy:
            return
        dlg = tb.Toplevel(self.root)
        dlg.title('Settings')
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        _raise_on_top(dlg)

        frame = ttk.Frame(dlg, padding=s(20))
        frame.pack()

        ttk.Label(frame, text='Repository URL:').grid(
            row=0, column=0, sticky='w', pady=s(5))
        url_var = tk.StringVar(value=self.config.get('repo_url', ''))
        ttk.Entry(frame, textvariable=url_var, width=50).grid(
            row=0, column=1, padx=(s(5), 0), pady=s(5))

        ttk.Label(frame, text='Local Path:').grid(
            row=1, column=0, sticky='w', pady=s(5))
        path_var = tk.StringVar(value=self.config.get('local_path', ''))
        pf = ttk.Frame(frame)
        pf.grid(row=1, column=1, padx=(s(5), 0), pady=s(5), sticky='ew')
        ttk.Entry(pf, textvariable=path_var, width=40).pack(side='left')
        ttk.Button(
            pf, text='Browse...',
            command=lambda: path_var.set(
                filedialog.askdirectory(parent=dlg) or path_var.get())
        ).pack(side='right', padx=(s(5), 0))

        ttk.Label(frame, text='Branch:').grid(
            row=2, column=0, sticky='w', pady=s(5))
        branch_var = tk.StringVar(value=self.config.get('branch', ''))
        ttk.Entry(frame, textvariable=branch_var, width=50).grid(
            row=2, column=1, padx=(s(5), 0), pady=s(5))

        def save():
            new_path = path_var.get().strip()
            new_branch = branch_var.get().strip()

            git_dir = os.path.join(new_path, '.git')
            if new_path and not os.path.exists(git_dir):
                show_error('Invalid Path',
                    'The specified folder does not contain a .git directory.',
                    parent=dlg)
                return

            settings = dict(self.config, repo_url=url_var.get().strip(),
                            local_path=new_path, branch=new_branch)
            if not self._is_repo_path(new_path):
                show_error('Invalid Path', 'Choose an existing Git repository.', parent=dlg)
                return

            def apply_settings():
                if new_branch and new_branch != get_current_branch(new_path):
                    checkout_branch(new_path, new_branch)
                save_config(settings)
                report('Settings saved. Refreshing the selected repository…')
                return settings

            def done(settings):
                self.config = settings
                self.repo_label.configure(text=new_path)
                self.branch_label.configure(text='Loading repository…')
                self._populate([])
                self._set_status('Repository settings saved.')
                self.root.after(100, self._refresh)

            dlg.destroy()
            self._async(apply_settings, on_done=done, title='Applying repository settings')

        bf = ttk.Frame(frame)
        bf.grid(row=3, column=0, columnspan=2, pady=(s(15), 0))
        ttk.Button(bf, text='Save', command=save).pack(
            side='right', padx=(s(5), 0))
        ttk.Button(bf, text='Cancel', command=dlg.destroy).pack(side='right')

    @staticmethod
    def _resource_path(rel):
        try:
            base = sys._MEIPASS
        except AttributeError:
            base = os.path.dirname(__file__)
        return os.path.join(base, rel)

    def _set_app_icon(self):
        if sys.platform == 'win32':
            try:
                # Windows selects the appropriate size for the title bar,
                # taskbar, Alt+Tab, and any subsequently created dialogs.
                self.root.iconbitmap(default=self._resource_path(
                    os.path.join('resources', 'icon.ico')))
                return
            except tk.TclError:
                pass
        try:
            img = tk.PhotoImage(master=self.root, file=self._resource_path(
                os.path.join('resources', 'icon.png')))
            self.root.iconphoto(True, img)
            self._icon_img = img
        except tk.TclError:
            pass

    def _show_about(self):
        dlg = tb.Toplevel(self.root)
        dlg.title('About GCAD')
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        _raise_on_top(dlg)

        frame = ttk.Frame(dlg, padding=s(20))
        frame.pack()

        try:
            abt_img = tk.PhotoImage(
                file=self._resource_path(os.path.join('resources', 'icon-about.png')))
            lbl = ttk.Label(frame, image=abt_img)
            lbl.image = abt_img
            lbl.grid(row=0, column=0, rowspan=3, padx=(0, s(15)))
        except Exception:
            pass

        ttk.Label(frame, text='GCAD', font=('TkDefaultFont', s(16), 'bold')).grid(
            row=0, column=1, sticky='w')
        ttk.Label(frame, text='Git for CAD').grid(row=1, column=1, sticky='w')
        ttk.Label(frame, text='Manage CAD files with Git and Git LFS.').grid(
            row=2, column=1, sticky='w', pady=(s(4), 0))

        bf = ttk.Frame(dlg, padding=(s(20), 0, s(20), s(10)))
        bf.pack(fill='x')
        ttk.Button(bf, text='OK', command=dlg.destroy).pack(side='right')

    def run(self):
        # Let Tk map the main window before any startup work (including Git
        # checks) runs.  An idle callback may otherwise run first and leave a
        # windowed executable looking like it never launched.
        self.root.after(100, self._safe_start)
        self.root.mainloop()
