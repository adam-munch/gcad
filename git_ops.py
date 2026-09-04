import subprocess
import json
import os
import re


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
    cmd = ['git', '-c', 'http.sslVerify=false'] + args
    env = dict(os.environ)
    env['GIT_SSL_NO_VERIFY'] = 'true'
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
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


def clone_repo(url, local_path):
    parent = os.path.dirname(local_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    _run_git(['clone', url, local_path], timeout=600)
    _run_git_lfs(['install'], repo_path=local_path, timeout=30)
    _run_git_lfs(['pull'], repo_path=local_path, timeout=300)


def pull_repo(repo_path):
    _run_git(['pull', '--rebase', '--autostash'], repo_path=repo_path, timeout=300)
    _run_git_lfs(['pull'], repo_path=repo_path, timeout=300)


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
    locks_ours = {}
    locks_theirs = {}
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
    except (GitError, json.JSONDecodeError):
        pass

    modified = set()
    deleted = set()
    untracked = set()
    conflicted = set()
    try:
        # Git normally condenses a wholly untracked directory into one entry
        # (for example, ``?? designs/new-part/``).  The UI displays files in
        # a hierarchy, so that entry would otherwise be rendered as a blank
        # file inside the new directory.  Ask Git to report every untracked
        # file so new folders and their contents build the same tree as
        # tracked folders.
        raw = _run_git(
            ['status', '--porcelain', '--untracked-files=all'],
            repo_path=repo_path,
        )
        for line in raw.splitlines():
            line = line.rstrip()
            if not line:
                continue
            flags = line[:2]
            path = line[3:]
            if ' -> ' in path:
                path = path.split(' -> ')[-1]
            path = path.replace('\\', '/')
            if 'U' in flags:
                conflicted.add(path)
            if 'D' in flags:
                deleted.add(path)
            if flags[1] in 'MACR' or flags[0] in 'MACR':
                modified.add(path)
            if flags == '??':
                untracked.add(path)
    except GitError:
        pass

    lfs_files = set()
    try:
        raw = _run_git_lfs(['ls-files', '--name-only'], repo_path=repo_path)
        for line in raw.splitlines():
            line = line.strip()
            if line:
                lfs_files.add(line.replace('\\', '/'))
    except GitError:
        pass

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
        })

    return result


def lock_files(repo_path, file_paths):
    if not file_paths:
        return
    for fp in file_paths:
        _run_git_lfs(['lock', fp], repo_path=repo_path, timeout=60)


def unlock_files(repo_path, file_paths, force=False):
    if not file_paths:
        return
    for fp in file_paths:
        args = ['unlock', '--force', fp] if force else ['unlock', fp]
        _run_git_lfs(args, repo_path=repo_path, timeout=60)


def restore_files(repo_path, file_paths):
    if not file_paths:
        return
    for fp in file_paths:
        _run_git(['restore', fp], repo_path=repo_path, timeout=60)


def install_lfs(repo_path):
    try:
        _run_git_lfs(['install'], repo_path=repo_path, timeout=30)
    except GitError:
        pass


def checkout_branch(repo_path, branch):
    _run_git(['checkout', branch], repo_path=repo_path, timeout=60)


def hard_reset_repo(repo_path):
    branch = get_current_branch(repo_path)
    if branch == 'HEAD':
        raise GitError(
            "Cannot hard reset: repository is in a detached HEAD state.\n\n"
            "Open File > Settings and set the correct branch, then try again."
        )
    _run_git(['fetch', 'origin'], repo_path=repo_path, timeout=120)
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


def commit_and_push(repo_path, file_paths, message, deleted_paths=None):
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

    _run_git(['commit', '-m', message], repo_path=repo_path, timeout=60)

    try:
        _run_git(['push'], repo_path=repo_path, timeout=300)
    except GitError as e:
        try:
            _run_git(['reset', 'HEAD~1'], repo_path=repo_path, timeout=30)
        except GitError:
            pass
        raise GitError(
            "Push failed. The commit was rolled back.\n\n"
            "Try Pulling to get the latest changes, then Push again.\n\n"
            "Details: " + str(e)
        )

    for fp in file_paths:
        try:
            _run_git_lfs(['unlock', fp], repo_path=repo_path, timeout=30)
        except GitError:
            pass



