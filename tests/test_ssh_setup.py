import base64
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from git_ops import GitError, _run_git, clone_repo
import ssh_setup as ssh


class SSHOperationsTests(unittest.TestCase):
    def test_ssh_urls_and_custom_ports(self):
        self.assertEqual(ssh.parse_ssh_url('git@github.com:team/cad.git'), ('github.com', 22))
        self.assertEqual(ssh.parse_ssh_url('ssh://git@cad.example.com:2222/team/cad.git'),
                         ('cad.example.com', 2222))
        for url in ('https://host/team/cad', '-oProxyCommand=bad', 'ssh://-host/team',
                    'ssh://git@host:70000/team', 'ssh://git:secret@host/team', 'git@host:bad link'):
            with self.subTest(url=url), self.assertRaises(GitError):
                ssh.parse_ssh_url(url)

    def test_real_key_generation_uses_ssh_root_and_displays_only_public_key(self):
        with tempfile.TemporaryDirectory() as directory, patch('ssh_setup.Path.home', return_value=Path(directory)):
            first, public = ssh.create_key('designer@example.com')
            self.assertEqual(Path(first), Path(directory) / '.ssh' / 'id_ed25519')
            self.assertEqual({path.name for path in Path(first).parent.iterdir()},
                             {'id_ed25519', 'id_ed25519.pub'})
            self.assertTrue(Path(first).is_file())
            self.assertTrue(public.startswith('ssh-ed25519 '))
            self.assertNotIn('PRIVATE KEY', public)
            actual = ssh._run([ssh.ssh_tools()['ssh-keygen'], '-l', '-f', first + '.pub'])
            self.assertIn(ssh.fingerprint(public.split()[1]), actual)
            Path(first + '.pub').unlink()
            self.assertEqual(ssh.public_key(first).split()[:2], public.split()[:2])
            with self.assertRaises(GitError):
                ssh.public_key(first + '.pub')

    def test_existing_private_or_public_key_requires_explicit_replacement(self):
        for names in (('id_ed25519',), ('id_ed25519.pub',), ('id_ed25519', 'id_ed25519.pub')):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as directory, \
                 patch('ssh_setup.Path.home', return_value=Path(directory)), patch('ssh_setup._run') as run:
                ssh_directory = Path(directory) / '.ssh'
                ssh_directory.mkdir()
                for name in names:
                    (ssh_directory / name).write_text('original')
                with self.assertRaisesRegex(GitError, 'Confirm replacement'):
                    ssh.create_key('designer@example.com')
                run.assert_not_called()
                self.assertEqual({path.name: path.read_text() for path in ssh_directory.iterdir()},
                                 {name: 'original' for name in names})

    def test_confirmed_replacement_generates_matching_new_pair(self):
        with tempfile.TemporaryDirectory() as directory, patch('ssh_setup.Path.home', return_value=Path(directory)):
            first, old_public = ssh.create_key('designer@example.com')
            old_private = Path(first).read_bytes()
            second, new_public = ssh.create_key('designer@example.com', overwrite=True)
            self.assertEqual(first, second)
            self.assertNotEqual(old_private, Path(second).read_bytes())
            self.assertNotEqual(old_public, new_public)
            self.assertEqual(Path(second + '.pub').read_text().strip(), new_public)
            derived = ssh._run([ssh.ssh_tools()['ssh-keygen'], '-y', '-P', '', '-f', second])
            self.assertEqual(derived.split()[:2], new_public.split()[:2])
            self.assertEqual(len(list(Path(second).parent.iterdir())), 2)

    def test_failed_generation_preserves_existing_pair_and_cleans_temporary_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch('ssh_setup.Path.home', return_value=Path(directory)):
            key, _ = ssh.create_key('designer@example.com')
            ssh_directory = Path(key).parent
            original = {path.name: path.read_bytes() for path in ssh_directory.iterdir()}
            with patch('ssh_setup._run', side_effect=GitError('Generation failed')):
                with self.assertRaisesRegex(GitError, 'Generation failed'):
                    ssh.create_key('designer@example.com', overwrite=True)
            self.assertEqual({path.name: path.read_bytes() for path in ssh_directory.iterdir()}, original)

    def test_encrypted_key_with_public_file_does_not_prompt_for_passphrase(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / 'encrypted_key'
            key.write_text('placeholder encrypted private key')
            public = 'ssh-ed25519 ' + base64.b64encode(b'test public key').decode()
            Path(str(key) + '.pub').write_text(public)
            with patch('ssh_setup._run') as run:
                self.assertEqual(ssh.public_key(str(key)), public)
                run.assert_not_called()

    def test_scan_does_not_trust_and_custom_port_is_preserved(self):
        public = base64.b64encode(b'server key').decode()
        with tempfile.TemporaryDirectory() as directory, patch('ssh_setup.Path.home', return_value=Path(directory)), \
             patch('ssh_setup._run', return_value='[host]:2222 ssh-ed25519 ' + public) as run:
            candidate = ssh.scan_host('ssh://git@host:2222/team/cad.git')
            self.assertEqual(candidate['port'], 2222)
            self.assertIn('2222', run.call_args.args[0])
            self.assertFalse((Path(directory) / '.ssh').exists())

    def test_scan_retries_unsupported_kex_with_another_scanner_without_trusting(self):
        public = base64.b64encode(b'server key').decode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary, fallback = root / 'windows', root / 'git'
            suffix = '.exe' if ssh.os.name == 'nt' else ''
            for folder in (primary, fallback):
                folder.mkdir()
                (folder / ('ssh-keyscan' + suffix)).touch()
            first = str(primary / ('ssh-keyscan' + suffix))
            second = str(fallback / ('ssh-keyscan' + suffix))
            with patch('ssh_setup.Path.home', return_value=root), \
                 patch('ssh_setup.ssh_tools', return_value={'ssh-keyscan': first}), \
                 patch('ssh_setup._ssh_tool_directories', return_value=[primary, primary, fallback]), \
                 patch('ssh_setup._run', side_effect=[
                     GitError('choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com'),
                     '# server banner\n[host]:2222 ssh-ed25519 ' + public]) as run:
                candidate = ssh.scan_host('ssh://git@host:2222/team/cad.git')
            self.assertEqual(run.call_count, 2)
            args = ['-T', '10', '-p', '2222', '-t', 'ed25519,ecdsa,rsa', 'host']
            self.assertEqual(run.call_args_list[0].args[0], [first] + args)
            self.assertEqual(run.call_args_list[1].args[0], [second] + args)
            self.assertEqual(candidate['line'], '[host]:2222 ssh-ed25519 ' + public)
            self.assertEqual(candidate['fingerprint'], ssh.fingerprint(public))
            self.assertFalse((root / '.ssh').exists())

    def test_scan_does_not_retry_unrelated_errors(self):
        with patch('ssh_setup.ssh_tools', return_value={'ssh-keyscan': 'scanner'}), \
             patch('ssh_setup._ssh_tool_directories') as directories, \
             patch('ssh_setup._run', side_effect=GitError('Connection refused')) as run:
            with self.assertRaisesRegex(GitError, 'Connection refused'):
                ssh.scan_host('git@host:team/cad.git')
        directories.assert_not_called()
        run.assert_called_once()

    def test_scan_without_compatible_scanner_explains_recovery(self):
        with patch('ssh_setup.ssh_tools', return_value={'ssh-keyscan': 'scanner'}), \
             patch('ssh_setup._ssh_tool_directories', return_value=[]), \
             patch('ssh_setup._run', side_effect=GitError('choose_kex: unsupported KEX method example')):
            with self.assertRaisesRegex(GitError, 'Update Windows OpenSSH.*Git for Windows'):
                ssh.scan_host('git@host:team/cad.git')

    def test_trust_deduplicates_and_rejects_changed_key(self):
        candidate = {'line': 'host ssh-ed25519 ' + base64.b64encode(b'original').decode()}
        with tempfile.TemporaryDirectory() as directory, patch('ssh_setup.Path.home', return_value=Path(directory)):
            known = Path(ssh.trust_host(candidate))
            ssh.trust_host(candidate)
            self.assertEqual(len(known.read_text().splitlines()), 1)
            changed = {'line': 'host ssh-ed25519 ' + base64.b64encode(b'changed').decode()}
            with self.assertRaisesRegex(GitError, 'changed'):
                ssh.trust_host(changed)
            self.assertEqual(known.read_text().strip(), candidate['line'])

    def test_command_quotes_paths_and_requires_verified_host(self):
        with tempfile.TemporaryDirectory(prefix='GCAD space ') as directory:
            key = str(Path(directory) / "designer's key")
            known = str(Path(directory) / 'known hosts')
            command = ssh.ssh_command(key, known)
            args = shlex.split(command)
            self.assertIn(key.replace('\\', '/'), args)
            self.assertIn('StrictHostKeyChecking=yes', args)
            self.assertIn('BatchMode=yes', args)
            # Ask OpenSSH to parse configuration without connecting to a host.
            parsed = ssh._run(args + ['-G', 'git@example.com'])
            self.assertIn('batchmode yes', parsed)
            self.assertIn('stricthostkeychecking true', parsed)
            self.assertIn(known.replace('\\', '/'), parsed)

    def test_repository_access_error_has_manual_recovery_steps(self):
        with patch('ssh_setup._run_git', side_effect=GitError('Permission denied (publickey)')):
            with self.assertRaisesRegex(GitError, 'SSO'):
                ssh.test_repository('git@host:team/cad.git', 'ssh')

    def test_repository_test_uses_specific_key_command(self):
        with patch('ssh_setup._run_git', return_value='') as run:
            self.assertEqual(ssh.test_repository('git@host:team/cad.git', 'ssh -i key'), 'ssh -i key')
        self.assertEqual(run.call_args.args[0],
                         ['-c', 'core.sshCommand=ssh -i key', 'ls-remote', '--', 'git@host:team/cad.git'])

    def test_clone_persists_ssh_settings_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / 'source', Path(directory) / 'clone'
            _run_git(['init', str(source)])
            _run_git(['-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                      'commit', '--allow-empty', '-m', 'Initial'], repo_path=str(source))
            command = 'ssh -i example-key -o StrictHostKeyChecking=yes'
            clone_repo(str(source), str(destination), ssh_command=command)
            self.assertEqual(_run_git(['config', '--local', '--get', 'core.sshCommand'],
                                      repo_path=str(destination)), command)

    def test_self_hosted_guidance_does_not_invent_account_settings_url(self):
        settings, fingerprints, instructions = ssh.host_guidance('git@cad.example.com:team/cad.git')
        self.assertIsNone(settings)
        self.assertIsNone(fingerprints)
        self.assertIn('administrator', instructions)


if __name__ == '__main__':
    unittest.main()
