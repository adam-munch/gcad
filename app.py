import tkinter as tk
from tkinter import ttk, filedialog
import os
import sys
import queue
import threading

import ttkbootstrap as tb

from dpi import s
from config import DEFAULT_CONFIG, load_config, save_config, config_exists
from git_ops import (
    check_git, check_git_lfs, pull_repo, get_file_statuses,
    lock_files, unlock_files, commit_and_push, restore_files,
    hard_reset_repo, install_lfs, checkout_branch,
    get_current_branch, get_repo_name, clone_repo,
    GitError,
)
from ui.file_table import FileTable
from ui.toolbar import Toolbar
from ui.dialogs import SetupWizard, CommitDialog, show_error, show_info, show_confirm, _raise_on_top


class App:
    def __init__(self, theme='flatly'):
        self.root = tb.Window(themename=theme)
        self.root.title('GCAD - Git for CAD')
        self.root.geometry('{}x{}'.format(s(900), s(600)))
        self.root.minsize(s(700), s(400))

        self.config = None
        self._busy = False
        self._op_queue = queue.Queue()

    def _start(self):
        git_ok, git_msg = check_git()
        if not git_ok:
            self._abort_startup('Git Not Found', git_msg)
            return

        lfs_ok, lfs_msg = check_git_lfs()
        if not lfs_ok:
            self._abort_startup('Git LFS Not Found', lfs_msg)
            return

        missing_repository = False
        if config_exists():
            self.config = load_config()
            if self.config and self.config.get('local_path'):
                repo_path = self.config['local_path']
                if not self._is_repo_path(repo_path):
                    # Do not leave the stale path in the config.  Open the
                    # normal New Repository flow after the main window loads.
                    self.config = dict(DEFAULT_CONFIG)
                    save_config(self.config)
                    missing_repository = True

        if (not missing_repository
                and (not self.config or not self.config.get('local_path'))):
            self.root.deiconify()
            SetupWizard(self.root, self._on_setup_complete)
            if not self.config or not self.config.get('local_path'):
                self.root.destroy()
                return

        self._build_ui()
        self._set_app_icon()
        self.root.deiconify()
        self.root.after(100, self._process_queue)
        if missing_repository:
            self._set_status('Select a repository to get started.')
            self.root.after_idle(self._on_clone_repo)
            return
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
        self.config = config
        save_config(self.config)

    def _on_clone_repo(self):
        if self._busy:
            return
        SetupWizard(self.root, self._on_clone_complete, allow_skip=False)

    def _on_clone_complete(self, config):
        self.config = config
        save_config(self.config)
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
        file_menu.add_command(label='Exit', command=self.root.quit)
        menubar.add_cascade(label='File', menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label='About GCAD', command=self._show_about)
        menubar.add_cascade(label='Help', menu=help_menu)

        self.toolbar = Toolbar(self.root)
        self.toolbar.pack(fill='x', padx=s(5), pady=(s(5), 0))

        self.toolbar.set_command('refresh', self._on_refresh)
        self.toolbar.set_command('pull', self._on_pull)
        self.toolbar.set_command('commit_push', self._on_commit_push)
        self.toolbar.set_command('restore', self._on_restore)
        self.toolbar.set_command('lock', self._on_lock)
        self.toolbar.set_command('unlock', self._on_unlock)

        self.file_table = FileTable(self.root)
        self.file_table.pack(fill='both', expand=True, padx=s(5), pady=s(5))

        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill='x', padx=s(5), pady=(0, s(5)))

        self.status_label = ttk.Label(status_frame, text='Ready')
        self.status_label.pack(side='left')

        self.branch_label = ttk.Label(status_frame, text='')
        self.branch_label.pack(side='right')

    def _update_title(self):
        repo_path = self.config.get('local_path', '')
        if self._is_repo_path(repo_path):
            try:
                branch = get_current_branch(repo_path)
                name = get_repo_name(repo_path)
                if branch == 'HEAD':
                    disp = '(detached)'
                else:
                    disp = branch
                self.root.title('GCAD - {} [{}]'.format(name, disp))
                self.branch_label.config(text='Branch: {}'.format(disp))
            except GitError:
                self.root.title('GCAD')
                self.branch_label.config(text='')
        else:
            self.root.title('GCAD')
            self.branch_label.config(text='')

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

    def _async(self, fn, on_done=None, on_error=None):
        def wrapper():
            try:
                result = fn()
                if on_done:
                    self._enqueue(lambda r=result: on_done(r))
            except GitError as e:
                err = str(e)
                if on_error:
                    self._enqueue(lambda e=e: on_error(e))
                else:
                    self._enqueue(lambda m=err: show_error('Error', m))
            except Exception as e:
                err = str(e)
                if on_error:
                    self._enqueue(lambda e=e: on_error(e))
                else:
                    self._enqueue(lambda m=err: show_error('Unexpected Error', m))
            finally:
                self._enqueue(lambda: self._set_busy(False))

        self._set_busy(True)
        t = threading.Thread(target=wrapper, daemon=True)
        t.start()

    def _set_busy(self, busy):
        self._busy = busy
        if busy:
            self.toolbar.set_all_enabled(False)
        else:
            self.toolbar.enable_defaults()

    def _set_status(self, text):
        self.status_label.config(text=text)

    def _repo_path(self):
        return self.config.get('local_path', '')

    def _assert_repo(self):
        repo_path = self._repo_path()
        if not self._is_repo_path(repo_path):
            show_error('No Repository',
                'No repository is configured.\n\n'
                'Go to File > Settings to configure one.')
            return None
        return repo_path

    def _initial_pull(self):
        repo_path = self._repo_path()
        if self._is_repo_path(repo_path):
            self._on_pull()

    def _on_refresh(self):
        self._refresh()

    def _refresh(self):
        repo_path = self._assert_repo()
        if not repo_path:
            return

        def do_refresh():
            install_lfs(repo_path)
            return get_file_statuses(repo_path)

        def on_done(statuses):
            self.file_table.populate(statuses)
            total = len(statuses)
            locked = sum(1 for s in statuses if 'locked' in s['status'])
            modified = sum(1 for s in statuses if 'modified' in s['status'])
            deleted = sum(1 for s in statuses if s['status'] == 'deleted')
            file_new = sum(1 for s in statuses if s['status'] == 'new')
            conflicted = sum(1 for s in statuses if s['status'] == 'conflicted')
            ready = total - locked - modified - deleted - file_new - conflicted
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
            self._set_status(' \u2014 '.join(parts))
            self._update_title()

        self._async(do_refresh, on_done=on_done)

    def _on_pull(self):
        repo_path = self._assert_repo()
        if not repo_path:
            return

        def do_pull():
            self._enqueue(lambda: self._set_status('Pulling latest changes...'))
            install_lfs(repo_path)
            pull_repo(repo_path)
            return get_file_statuses(repo_path)

        def on_done(statuses):
            self.file_table.populate(statuses)
            self._set_status('Pull complete.')
            self._update_title()

        self._async(do_pull, on_done=on_done)

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
            self.file_table.populate(statuses)
            self._set_status('Locked {} file(s).'.format(len(paths)))

        self._async(do_lock, on_done=on_done)

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
            self.file_table.populate(statuses)
            self._set_status('Unlocked {} file(s).'.format(len(paths)))

        self._async(do_unlock, on_done=on_done)

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
            self._enqueue(lambda: self._set_status('Pulling latest changes...'))
            install_lfs(repo_path)
            pull_repo(repo_path)
            self._enqueue(lambda: self._set_status('Committing and pushing...'))
            commit_and_push(repo_path, paths, msg, deleted_paths=deleted_paths)
            return get_file_statuses(repo_path)

        def on_done(statuses):
            self.file_table.populate(statuses)
            self._set_status(
                'Committed and pushed {} file(s).'.format(len(paths))
            )
            self._update_title()

        self._async(do_commit, on_done=on_done)

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
            self.file_table.populate(statuses)
            self._set_status('Restored {} file(s).'.format(len(paths)))
            self._update_title()

        self._async(do_restore, on_done=on_done)

    def _on_hard_reset(self):
        repo_path = self._assert_repo()
        if not repo_path:
            return

        try:
            branch = get_current_branch(repo_path)
            if branch == 'HEAD':
                show_error('Cannot Reset',
                    'The repository is in a detached HEAD state.\n'
                    'Open File > Settings and set the correct branch,\n'
                    'then try again.')
                return
        except GitError:
            pass

        if not show_confirm(
            'Hard Reset',
            'This will discard ALL local changes and reset the repository\n'
            'to match the remote branch.\n\n'
            'This cannot be undone. Continue?'
        ):
            return

        def do_reset():
            self._enqueue(lambda: self._set_status('Hard resetting to origin...'))
            hard_reset_repo(repo_path)
            return get_file_statuses(repo_path)

        def on_done(statuses):
            self.file_table.populate(statuses)
            self._set_status('Hard reset complete.')
            self._update_title()

        self._async(do_reset, on_done=on_done)

    def _show_settings(self):
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

            if new_branch and new_path:
                try:
                    current_branch = get_current_branch(new_path)
                    if new_branch != current_branch:
                        checkout_branch(new_path, new_branch)
                except GitError as e:
                    if not show_confirm('Branch Checkout Failed',
                        'Could not switch to branch "{}".\n\n'
                        '{}\n\nSave anyway?'.format(new_branch, str(e)),
                        parent=dlg
                    ):
                        return

            self.config['repo_url'] = url_var.get().strip()
            self.config['local_path'] = new_path
            self.config['branch'] = new_branch
            save_config(self.config)
            dlg.destroy()
            self._refresh()

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
        try:
            img = tk.PhotoImage(file=self._resource_path(os.path.join('resources', 'icon.png')))
            self.root.iconphoto(True, img)
            self._icon_img = img
        except Exception:
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
