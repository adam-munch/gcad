"""SSH onboarding with explicit confirmation before replacing keys."""
import base64
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit

from git_ops import GitError, _run_git, _subprocess_kwargs


def parse_ssh_url(url):
    if url.startswith('ssh://'):
        try:
            parsed = urlsplit(url)
            host, port = parsed.hostname, parsed.port or 22
            user = parsed.username or 'git'
            valid = parsed.path.strip('/') and not parsed.password
        except ValueError as exc:
            raise GitError('Check the SSH repository link and port.') from exc
    else:
        match = re.fullmatch(r'([\w.-]+)@([\w.-]+):([^\s]+)', url)
        host, port, user, valid = (match[2], 22, match[1], True) if match else ('', 22, '', False)
    if (not valid or not host or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', host)
            or not re.fullmatch(r'[\w.-]+', user) or user.startswith('-')
            or any(c.isspace() for c in url) or not 1 <= port <= 65535):
        raise GitError('Paste your repository’s SSH clone link, such as '
                       'git@github.com:team/cad.git or ssh://git@host:2222/team/cad.git. '
                       'Use the real server hostname for guided setup, not an SSH alias.')
    return host.lower(), port


def _ssh_tool_directories():
    candidates = []
    if os.name == 'nt':
        candidates.append(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/OpenSSH')
    installed = shutil.which('ssh')
    if installed:
        candidates.append(Path(installed).parent)
    git = shutil.which('git')
    if git:
        candidates.append(Path(git).parent.parent / 'usr/bin')
    return candidates


def ssh_tools():
    # Prefer Windows OpenSSH, whose agent is shared by desktop applications.
    # Key scanning may fall back independently; it does not use the SSH agent.
    suffix = '.exe' if os.name == 'nt' else ''
    for directory in _ssh_tool_directories():
        tools = {name: str(directory / (name + suffix))
                 for name in ('ssh', 'ssh-keygen', 'ssh-keyscan', 'ssh-add')}
        if all(Path(path).is_file() for path in tools.values()):
            return tools
    raise GitError('OpenSSH tools were not found. Install Git for Windows with its '
                   'bundled OpenSSH option, or enable OpenSSH Client in Windows Optional Features, '
                   'then reopen SSH setup.')


def _run(args, timeout=30):
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=timeout,
                                **_subprocess_kwargs())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError('SSH could not complete the operation. Check your connection and '
                       'OpenSSH installation, then retry.\n\n' + str(exc)) from exc
    if result.returncode:
        raise GitError(result.stderr.strip() or 'SSH operation failed.')
    return result.stdout


def key_paths():
    key = Path.home() / '.ssh' / 'id_ed25519'
    return key, key.with_name(key.name + '.pub')


def create_key(email, overwrite=False):
    key, public = key_paths()

    def check_existing():
        if not overwrite and any(os.path.lexists(path) for path in (key, public)):
            raise GitError('SSH key files already exist. Confirm replacement before creating a new key.')

    check_existing()
    tools = ssh_tools()
    directory = key.parent
    directory.mkdir(mode=0o700, exist_ok=True)
    # Finish generating and validating the pair before replacing existing files.
    with tempfile.TemporaryDirectory(prefix='gcad-', dir=directory) as temporary:
        staged_key = Path(temporary) / key.name
        _run([tools['ssh-keygen'], '-q', '-t', 'ed25519', '-N', '',
              '-C', email, '-f', str(staged_key)])
        value = public_key(str(staged_key))
        check_existing()
        staged_key.replace(key)
        Path(str(staged_key) + '.pub').replace(public)
    return str(key), value


def public_key(key_path):
    key = Path(key_path).expanduser().resolve()
    if not key.is_file() or key.name.endswith('.pub'):
        raise GitError('Select the private key file (the file without .pub). '
                       'GCAD will display only its public key.')
    public = Path(str(key) + '.pub')
    if public.is_file():
        value = public.read_text(encoding='utf-8').strip()
    else:
        try:
            value = _run([ssh_tools()['ssh-keygen'], '-y', '-P', '', '-f', str(key)]).strip()
        except GitError as exc:
            raise GitError('Could not read the public key. For an encrypted key, select a key '
                           'with its matching .pub file alongside it. Ask your administrator '
                           'to recover the public key if that file is missing.') from exc
    fields = value.split()
    if len(fields) < 2 or not fields[0].startswith(('ssh-', 'ecdsa-', 'sk-')) or '\n' in value:
        raise GitError('The public key file is not a single OpenSSH public key.')
    fingerprint(fields[1])
    return value


def fingerprint(encoded):
    try:
        key = base64.b64decode(encoded, validate=True)
        if not key:
            raise ValueError('Empty key')
    except ValueError as exc:
        raise GitError('SSH returned an invalid public key.') from exc
    return 'SHA256:' + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip('=')


def _scan_host_keys(host, port):
    scanner = ssh_tools()['ssh-keyscan']
    args = ['-T', '10', '-p', str(port), '-t', 'ed25519,ecdsa,rsa', host]
    try:
        return _run([scanner] + args, timeout=40)
    except GitError as exc:
        if 'choose_kex: unsupported KEX method' not in str(exc):
            raise
        errors = [str(exc)]

    # Some Windows builds advertise KEX algorithms their scanner cannot use
    # (Win32-OpenSSH issue #2140). Try another installed scanner, without
    # changing authentication tools or trusting the returned key automatically.
    tried = {Path(scanner).resolve()}
    suffix = '.exe' if os.name == 'nt' else ''
    for directory in _ssh_tool_directories():
        alternative = (directory / ('ssh-keyscan' + suffix)).resolve()
        if alternative in tried or not alternative.is_file():
            continue
        tried.add(alternative)
        try:
            return _run([str(alternative)] + args, timeout=40)
        except GitError as exc:
            errors.append(str(exc))
    raise GitError('The SSH fingerprint scanner could not negotiate a supported key exchange. '
                   'Update Windows OpenSSH or install/update Git for Windows with its bundled '
                   'OpenSSH tools, then fetch the fingerprint again.\n\n' + '\n\n'.join(errors))


def scan_host(url):
    host, port = parse_ssh_url(url)
    output = _scan_host_keys(host, port)
    token = host if port == 22 else '[{}]:{}'.format(host, port)
    keys = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == token and fields[1] in (
                'ssh-ed25519', 'ecdsa-sha2-nistp256', 'ssh-rsa'):
            keys.append((fields[1], ' '.join(fields), fingerprint(fields[2])))
    if not keys:
        raise GitError('No server key was returned. Check the hostname, VPN and firewall. '
                       'Ask your team which SSH hostname and port to use.')
    keys.sort(key=lambda item: item[0] != 'ssh-ed25519')
    kind, line, digest = keys[0]
    return {'host': host, 'port': port, 'line': line, 'fingerprint': digest, 'kind': kind}


def trust_host(candidate):
    """Called only after the user compares and confirms the displayed fingerprint."""
    directory = Path.home() / '.ssh'
    directory.mkdir(mode=0o700, exist_ok=True)
    known = directory / 'gcad_known_hosts'
    line = candidate['line']
    token, kind, _ = line.split()
    # Never replace a previously trusted key silently.
    with known.open('a+', encoding='utf-8') as file:
        file.seek(0)
        content = file.read()
        for entry in content.splitlines():
            fields = entry.split()
            if len(fields) >= 3 and fields[:2] == [token, kind]:
                if ' '.join(fields[:3]) != line:
                    raise GitError('This server’s key has changed. Stop and ask your team '
                                   'administrator to verify the change and update ' + str(known))
                return str(known)
        file.write(('\n' if content and not content.endswith('\n') else '') + line + '\n')
    return str(known)


def ssh_command(key_path, known_hosts):
    def path(value):
        return str(Path(value).resolve()).replace('\\', '/')
    # core.sshCommand is interpreted by Git's shell. Quote every argument;
    # SSH also parses the path inside the UserKnownHostsFile option itself.
    return shlex.join([path(ssh_tools()['ssh']), '-i', path(key_path),
                       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                       '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
                       '-o', 'UserKnownHostsFile="{}"'.format(path(known_hosts))])


def test_repository(url, command):
    parse_ssh_url(url)
    try:
        _run_git(['-c', 'core.sshCommand=' + command, 'ls-remote', '--', url], timeout=60)
    except GitError as exc:
        raise GitError('SSH repository access failed. Check that the public key is saved '
                       'in the correct account, accept your team’s repository invitation, and '
                       'authorize the key for organization SSO if required. Encrypted keys must '
                       'be unlocked in the SSH agent. Also check your VPN/firewall.\n\n' + str(exc)) from exc
    return command


def host_guidance(url):
    host, _ = parse_ssh_url(url)
    if host == 'github.com':
        return ('https://github.com/settings/ssh/new',
                'https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints',
                'GitHub: Settings → SSH and GPG keys → New SSH key. Choose Authentication Key, '
                'paste the public key, name it GCAD, and save. If your organization uses SSO, '
                'use Configure SSO beside the key and authorize the organization.')
    if host == 'gitlab.com':
        return ('https://gitlab.com/-/user_settings/ssh_keys',
                'https://docs.gitlab.com/user/gitlab_com/#ssh-host-keys-fingerprints',
                'GitLab: Edit profile → Access → SSH keys → Add new key. Paste the public key, '
                'name it GCAD, enable authentication, and save. Follow your team’s expiry policy.')
    return (None, None,
            'In your Git host’s website, open your account settings and find SSH keys. '
            'Add the public key as an authentication key and name it GCAD. Ask your team '
            'administrator for the correct account page and the server’s SHA256 fingerprint.')
