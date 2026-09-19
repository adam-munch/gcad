import subprocess
import json
import os
import re
import threading
import time
from contextvars import copy_context
from progress import report, is_reporting


class GitError(Exception):
    pass


def _subprocess_kwargs():
    kwargs = {}
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs['startupinfo'] = startupinfo
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    return kwargs


def _run_git(args, repo_path=None, timeout=120):
    transfer = args and args[0] in ('clone', 'pull', 'push', 'fetch') and is_reporting()
    if transfer:
        args = [args[0], '--progress'] + args[1:]
    cmd = ['git'] + args
    env = dict(os.environ)
    # The windowed executable has no terminal; credential helpers can still
    # open their browser/UI for HTTPS sign-in.
    env['GIT_TERMINAL_PROMPT'] = '0'
    # All GCAD Git/LFS operations use this override, including existing repos.
    # Keep it in child processes so Git settings outside GCAD are unaffected.
    env['GIT_SSL_NO_VERIFY'] = 'true'
    try:
        runner = _run_transfer if transfer else subprocess.run
        result = runner(
            cmd,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=repo_path,
            timeout=timeout,
            env=env,
            **_subprocess_kwargs(),
        )
    except FileNotFoundError:
        raise GitError(
            "Git not found.\n\n"
            "Please install Git for Windows from:\n"
            "https://git-scm.com/download/win\n\n"
            "Make sure 'Git from the command line' is selected during installation."
        )
    except subprocess.TimeoutExpired:
        raise GitError("Command timed out after {} seconds.".format(timeout))

    if result.returncode != 0:
        raise GitError(result.stderr.strip() or result.stdout.strip())

    return result.stdout.rstrip('\n')


def _run_transfer(cmd, timeout, **kwargs):
    """Drain both pipes while Git runs, retaining output for normal error handling."""
    kwargs.pop('capture_output')
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    output, errors = [], []

    def read_stdout():
        output.append(process.stdout.read())
        process.stdout.close()

    def read_stderr():
        last = 0
        for line in process.stderr:
            errors.append(line)
            # Git percentages describe individual transfer stages, not an ETA.
            if '%' in line and time.monotonic() - last >= 0.2:
                report(line.strip())
                last = time.monotonic()
        process.stderr.close()

    context = copy_context()
    readers = [threading.Thread(target=read_stdout, daemon=True),
               threading.Thread(target=lambda: context.run(read_stderr), daemon=True)]
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise
    finally:
        for reader in readers:
            reader.join(timeout=1)
    return subprocess.CompletedProcess(cmd, process.returncode, ''.join(output), ''.join(errors))


def _run_git_lfs(args, repo_path=None, timeout=120):
    return _run_git(['lfs'] + args, repo_path=repo_path, timeout=timeout)


def check_git():
    try:
        version = _run_git(['--version'], timeout=10)
        return True, version
    except GitError as e:
        return False, str(e)


def check_git_lfs():
    try:
        out = _run_git(['lfs', 'version'], timeout=10)
        return True, out
    except GitError as e:
        return False, str(e)


def clone_repo(url, local_path, ssh_command=None):
    report('Downloading the repository. Complete Git’s sign-in window if prompted.')
    parent = os.path.dirname(local_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    options = ['--config', 'core.sshCommand=' + ssh_command] if ssh_command else []
    _run_git(['clone'] + options + ['--', url, local_path], timeout=600)
    report('Repository downloaded. Preparing large CAD files…')
    _run_git_lfs(['install', '--local'], repo_path=local_path, timeout=30)
    _run_git_lfs(['pull'], repo_path=local_path, timeout=300)


def pull_repo(repo_path):
    report('Syncing commits from the remote and reapplying your local changes…')
    _run_git(['pull', '--rebase', '--autostash'], repo_path=repo_path, timeout=300)
    report('Downloading large CAD files with Git LFS…')
    _run_git_lfs(['pull'], repo_path=repo_path, timeout=300)
    report('Download complete. Checking the updated repository…')


def get_current_branch(repo_path):
    return _run_git(['rev-parse', '--abbrev-ref', 'HEAD'], repo_path=repo_path)


def get_remote_url(repo_path):
    try:
        return _run_git(['remote', 'get-url', 'origin'], repo_path=repo_path)
    except GitError:
        return None


def get_repo_name(repo_path):
    url = get_remote_url(repo_path)
    if not url:
        return os.path.basename(repo_path)
    name = url.rstrip('/').split('/')[-1]
    if name.endswith('.git'):
        name = name[:-4]
    return name


def get_file_statuses(repo_path):
    report('Checking who has files locked on the server…')
    locks_ours = {}
    locks_theirs = {}
    locks_verified = True
    try:
        raw = _run_git_lfs(['locks', '--verify', '--json'], repo_path=repo_path)
        if raw:
            data = json.loads(raw)
            for lock in data.get('ours', []):
                path = lock['path'].replace('\\', '/')
                owner = lock.get('owner', {}).get('name', 'Unknown')
                locks_ours[path] = owner
            for lock in data.get('theirs', []):
                path = lock['path'].replace('\\', '/')
                owner = lock.get('owner', {}).get('name', 'Unknown')
                locks_theirs[path] = owner
    except (GitError, json.JSONDecodeError) as exc:
        locks_verified = False
        report('Lock information is unavailable; ownership has not been verified. ' + str(exc), level='warning')

    report('Scanning local files for changes, additions, and deletions…')
    modified = set()
    deleted = set()
    untracked = set()
    conflicted = set()
    renamed_sources = set()
    try:
        # Git normally condenses a wholly untracked directory into one entry
        # (for example, ``?? designs/new-part/``).  The UI displays files in
        # a hierarchy, so that entry would otherwise be rendered as a blank
        # file inside the new directory.  Ask Git to report every untracked
        # file so new folders and their contents build the same tree as
        # tracked folders.
        raw = _run_git(
            ['status', '--porcelain=v1', '-z', '--untracked-files=all'],
            repo_path=repo_path,
        )
        # NUL-separated records preserve literal names, including spaces and
        # Unicode. The line format quotes/escapes paths, creating duplicate
        # entries when those strings are combined with the LFS inventory.
        records = iter(raw.split('\0'))
        for record in records:
            if not record:
                continue
            flags = record[:2]
            path = record[3:]
            path = path.replace('\\', '/')
            # In -z format a rename/copy has destination first, then a
            # separate source record without status flags.
            if 'R' in flags or 'C' in flags:
                source = next(records).replace('\\', '/')
                if 'R' in flags:
                    renamed_sources.add(source)
            if 'U' in flags:
                conflicted.add(path)
            if 'D' in flags:
                deleted.add(path)
            if flags[1] in 'MACR' or flags[0] in 'MACR':
                modified.add(path)
            if flags == '??':
                untracked.add(path)
    except GitError:
        # A failed local scan must not look like a clean repository.
        raise

    report('Reading the large-file inventory…')
    lfs_files = set()
    try:
        # LFS also reads Git's diff output for staged changes. Disable Git's
        # Unicode quoting there so the JSON names match the status paths.
        raw = _run_git(['-c', 'core.quotepath=false', 'lfs', 'ls-files', '--json'],
                       repo_path=repo_path)
        for file in json.loads(raw).get('files') or []:
            lfs_files.add(file['name'].replace('\\', '/'))
    except GitError:
        raise

    # LFS can still list the HEAD path after a staged rename.
    lfs_files.difference_update(renamed_sources)

    all_paths = set()
    all_paths.update(lfs_files)
    all_paths.update(modified)
    all_paths.update(deleted)
    all_paths.update(untracked)
    all_paths.update(conflicted)

    result = []
    for path in sorted(all_paths):
        norm = path.replace('\\', '/')
        name = os.path.basename(norm)
        folder = os.path.dirname(norm)
        is_lfs = norm in lfs_files
        is_modified = norm in modified
        is_deleted = norm in deleted
        is_untracked = norm in untracked
        is_conflicted = norm in conflicted
        locked_by_me = norm in locks_ours
        lock_owner = locks_ours.get(norm) or locks_theirs.get(norm)

        if is_conflicted:
            status = 'conflicted'
        elif is_deleted:
            status = 'deleted'
        elif locked_by_me:
            if is_untracked:
                status = 'locked_by_me_new'
            elif is_modified:
                status = 'locked_by_me_modified'
            else:
                status = 'locked_by_me'
        elif lock_owner:
            if is_untracked:
                status = 'locked_by_other_new'
            elif is_modified:
                status = 'locked_by_other_modified'
            else:
                status = 'locked_by_other'
        elif is_untracked:
            status = 'new'
        elif is_modified:
            status = 'modified'
        else:
            status = 'unchanged'

        result.append({
            'path': norm,
            'name': name,
            'folder': folder,
            'status': status,
            'locked_by': lock_owner,
            'is_lfs': is_lfs,
            'locks_verified': locks_verified,
        })

    return result


def lock_files(repo_path, file_paths):
    if not file_paths:
        return
    for index, fp in enumerate(file_paths):
        report('Locking: ' + fp, index, len(file_paths))
        _run_git_lfs(['lock', fp], repo_path=repo_path, timeout=60)
        report('Locked: ' + fp, index + 1, len(file_paths))


def unlock_files(repo_path, file_paths, force=False):
    if not file_paths:
        return
    for index, fp in enumerate(file_paths):
        report('Unlocking: ' + fp, index, len(file_paths))
        args = ['unlock', '--force', fp] if force else ['unlock', fp]
        _run_git_lfs(args, repo_path=repo_path, timeout=60)
        report('Unlocked: ' + fp, index + 1, len(file_paths))


def restore_files(repo_path, file_paths):
    if not file_paths:
        return
    for index, fp in enumerate(file_paths):
        report('Restoring: ' + fp, index, len(file_paths))
        _run_git(['restore', fp], repo_path=repo_path, timeout=60)
        report('Restored: ' + fp, index + 1, len(file_paths))


def install_lfs(repo_path):
    report('Preparing Git LFS for this repository…')
    try:
        _run_git_lfs(['install', '--local'], repo_path=repo_path, timeout=30)
    except GitError as exc:
        report('Git LFS initialization needs attention: ' + str(exc), level='warning')


def checkout_branch(repo_path, branch):
    report('Switching to branch ' + branch + '…')
    _run_git(['checkout', branch], repo_path=repo_path, timeout=60)


def hard_reset_repo(repo_path):
    report('Checking the current branch…')
    branch = get_current_branch(repo_path)
    if branch == 'HEAD':
        raise GitError(
            "Cannot hard reset: repository is in a detached HEAD state.\n\n"
            "Open File > Settings and set the correct branch, then try again."
        )
    report('Fetching the latest remote commits…')
    _run_git(['fetch', 'origin'], repo_path=repo_path, timeout=120)
    report('Replacing local changes with origin/' + branch + '…')
    _run_git(['reset', '--hard', 'origin/' + branch], repo_path=repo_path, timeout=60)


def _restore_autostash(repo_path):
    """Reapply local changes the pull's autostash could not merge on its own.

    `git pull --rebase --autostash` leaves a stash behind when the autostash
    conflicts (e.g. a remote edit landed on a locally deleted file). Pop it so
    unrelated local changes are not lost, then unstage everything so the commit
    is built only from the paths explicitly passed in."""
    try:
        _run_git(['rev-parse', '--verify', 'refs/stash'], repo_path=repo_path, timeout=30)
    except GitError:
        return
    try:
        _run_git(['stash', 'pop'], repo_path=repo_path, timeout=60)
    except GitError:
        return
    _run_git(['reset', '-q'], repo_path=repo_path, timeout=30)


def _stage_deletions(repo_path, rm_paths):
    """Ensure selected deleted files are staged for deletion.

    The pull before the push can resurrect a user-deleted file when the remote
    also changed it (leaving a conflicted 'deleted by us/modified by them'
    state). Clear any conflict stages first, then force git rm so the deletion
    is pushed regardless of what the pull restored."""
    for fp in rm_paths:
        try:
            _run_git(['reset', '-q', '--', fp], repo_path=repo_path, timeout=30)
        except GitError:
            pass
    tracked = []
    for fp in rm_paths:
        try:
            if _run_git(['ls-files', '--cached', '--', fp], repo_path=repo_path, timeout=30):
                tracked.append(fp)
        except GitError:
            pass
    if tracked:
        _run_git(['rm', '-f', '--'] + tracked, repo_path=repo_path, timeout=60)


def commit_and_push(repo_path, file_paths, message, deleted_paths=None, unlock_paths=None):
    report('Preparing the selected changes for a commit…')
    if not file_paths:
        _restore_autostash(repo_path)
        _run_git(['add', '-A'], repo_path=repo_path, timeout=60)
    else:
        deleted_paths = set(deleted_paths or ())
        add_paths = []
        rm_paths = []
        for fp in file_paths:
            full = os.path.join(repo_path, fp)
            # deleted_paths records which files the user deleted before the
            # pre-push pull. Without it, a pull that resurrected one of those
            # files would turn the intended deletion into a plain re-add.
            if fp in deleted_paths or not os.path.exists(full):
                rm_paths.append(fp)
            else:
                add_paths.append(fp)
        # Clear any conflicted state left by the pre-push pull and stage the
        # deletions first, so the autostash merge below cannot resurrect files.
        if rm_paths:
            _stage_deletions(repo_path, rm_paths)
        # Reapply unrelated local changes the pull stashed, then unstage
        # everything so the commit below only contains the selected paths.
        _restore_autostash(repo_path)
        if rm_paths:
            _stage_deletions(repo_path, rm_paths)
        if add_paths:
            _run_git(['add', '--'] + add_paths, repo_path=repo_path, timeout=60)

    if not _run_git(['diff', '--cached', '--name-only'], repo_path=repo_path, timeout=30):
        raise GitError(
            "Nothing to commit.\n\n"
            "The selected changes are already up to date on the remote."
        )

    report('Creating your commit…')
    _run_git(['commit', '-m', message], repo_path=repo_path, timeout=60)

    try:
        report('Uploading commits and large CAD files to the remote…')
        _run_git(['push'], repo_path=repo_path, timeout=300)
    except GitError as e:
        report('Upload failed. Rolling back the local commit…', level='warning')
        try:
            _run_git(['reset', 'HEAD~1'], repo_path=repo_path, timeout=30)
        except GitError:
            pass
        raise GitError(
            "Push failed. The commit was rolled back.\n\n"
            "Try Pulling to get the latest changes, then Push again.\n\n"
            "Details: " + str(e)
        )

    report('Push succeeded. Releasing locks on the pushed files…')
    unlock_paths = file_paths if unlock_paths is None else unlock_paths
    for index, fp in enumerate(unlock_paths):
        report('Releasing lock: ' + fp, index, len(unlock_paths))
        try:
            _run_git_lfs(['unlock', fp], repo_path=repo_path, timeout=30)
        except GitError as exc:
            report('Changes were pushed, but no lock was released for {}: {}'.format(fp, exc), level='warning')
        report('Checked lock: ' + fp, index + 1, len(unlock_paths))



