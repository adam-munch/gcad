"""Setup operations, kept separate from Tk so slow work can run in a worker."""
import os
import re
import shutil
import subprocess
from urllib.parse import urlsplit

from config import DEFAULT_CONFIG
from git_ops import (
    GitError, _run_git, _subprocess_kwargs, check_git, check_git_lfs,
    clone_repo, get_current_branch, get_remote_url,
)


def refresh_tool_path():
    """Discover a new Windows install without requiring GCAD to restart."""
    if os.name != 'nt':
        return
    import winreg

    paths = os.environ.get('PATH', '').split(os.pathsep)
    for hive, key_name in (
        (winreg.HKEY_LOCAL_MACHINE,
         r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),
        (winreg.HKEY_CURRENT_USER, r'Environment'),
    ):
        try:
            with winreg.OpenKey(hive, key_name) as key:
                value, _ = winreg.QueryValueEx(key, 'Path')
                paths.extend(os.path.expandvars(value).split(os.pathsep))
        except OSError:
            pass
    for variable in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        base = os.environ.get(variable)
        if base:
            paths.extend(os.path.join(base, suffix) for suffix in (
                'Git/cmd', 'Programs/Git/cmd', 'Git LFS', 'Programs/Git LFS'))
    os.environ['PATH'] = os.pathsep.join(dict.fromkeys(p for p in paths if p))


def check_requirements():
    refresh_tool_path()
    git_ok, git_message = check_git()
    lfs_ok, lfs_message = check_git_lfs() if git_ok else (False, 'Requires Git')
    return {'git': git_ok, 'lfs': lfs_ok,
            'git_message': git_message, 'lfs_message': lfs_message}


def install_requirements():
    """Install only missing packages using the Windows package manager."""
    requirements = check_requirements()
    if requirements['git'] and requirements['lfs']:
        return requirements
    winget = shutil.which('winget') if os.name == 'nt' else None
    if not winget:
        raise GitError('Automatic installation needs Windows App Installer (winget). '
                       'Use the download buttons, finish installing, then click Check again.')
    for tool, package in (('git', 'Git.Git'), ('lfs', 'GitHub.GitLFS')):
        if requirements[tool]:
            continue
        try:
            result = subprocess.run(
                [winget, 'install', '--id', package, '--exact', '--source', 'winget',
                 '--silent', '--accept-package-agreements', '--accept-source-agreements',
                 '--disable-interactivity'],
                capture_output=True, stdin=subprocess.DEVNULL, text=True,
                encoding='utf-8', errors='replace', timeout=900,
                **_subprocess_kwargs(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitError('Installation did not finish. Use Check again or the download '
                           'buttons to continue.\n\n{}'.format(exc)) from exc
        requirements = check_requirements()
        if not requirements[tool]:
            detail = (result.stderr.strip() or result.stdout.strip())[-2000:]
            raise GitError('Could not install {}. Use the download buttons and then '
                           'Check again.\n\n{}'.format(package, detail))
    return requirements


def get_identity(repo_path=None):
    values = []
    for key in ('user.name', 'user.email'):
        try:
            args = ['config'] + ([] if repo_path else ['--global']) + ['--get', key]
            values.append(_run_git(args, repo_path=repo_path, timeout=10))
        except GitError:
            values.append('')
    return tuple(values)


def validate_identity(name, email):
    if not name.strip() or any(char in name for char in '\r\n<>'):
        raise GitError('Enter your name as you want it to appear beside your saved changes.')
    if not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+', email):
        raise GitError('Enter a valid email address. You can use your Git host\'s private email address.')


def validate_repository(url, path, existing=False):
    if not path.strip():
        raise GitError('Choose a folder for your CAD files.')
    path = os.path.abspath(os.path.expanduser(path))
    if existing:
        if not os.path.isdir(path) or not os.path.exists(os.path.join(path, '.git')):
            raise GitError('Choose an existing Git repository folder, or select Download a repository.')
    else:
        # Only accept repository transports, never command-line options or helper commands.
        parsed = urlsplit(url)
        https = parsed.scheme == 'https' and parsed.hostname and parsed.path.strip('/')
        ssh = ((parsed.scheme == 'ssh' and parsed.hostname and parsed.path.strip('/'))
               or re.fullmatch(r'[^\s@]+@[^\s:]+:.+', url))
        if not (https or ssh) or any(char.isspace() for char in url):
            raise GitError('Paste the HTTPS clone link from your team\'s repository page '
                           '(for example, https://github.com/team/cad.git). '
                           'For an SSH link, use Set up SSH access in the wizard.')
        if parsed.password or (https and parsed.username):
            raise GitError('Use a repository link without a password or token. '
                           'Git will handle sign-in separately.')
        if os.path.exists(path) and (not os.path.isdir(path) or os.listdir(path)):
            raise GitError('Choose a new or empty folder. To use a repository already '
                           'downloaded here, select Use an existing folder.')
    return path


def prepare_repository(url, path, name, email, existing=False, ssh_command=None):
    validate_identity(name, email)
    path = validate_repository(url, path, existing)
    if existing:
        if _run_git(['rev-parse', '--is-inside-work-tree'], repo_path=path) != 'true':
            raise GitError('This folder is not a working Git repository.')
        if ssh_command:
            _run_git(['config', '--local', 'core.sshCommand', ssh_command], repo_path=path)
    else:
        clone_repo(url, path, ssh_command=ssh_command)
    # Keep the user's identity and LFS setup local to this repository.
    _run_git(['lfs', 'install', '--local'], repo_path=path, timeout=30)
    if existing:
        _run_git(['lfs', 'pull'], repo_path=path, timeout=300)
    _run_git(['config', '--local', 'user.name', name], repo_path=path)
    _run_git(['config', '--local', 'user.email', email], repo_path=path)
    config = dict(DEFAULT_CONFIG)
    config.update(repo_url=get_remote_url(path) or '', local_path=path,
                  branch=get_current_branch(path))
    return config
