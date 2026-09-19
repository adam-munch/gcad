import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import app
import config
import setup_ops
from git_ops import GitError, _run_git, _run_git_lfs, clone_repo
from progress import operation_progress


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / '.gcad'
        for name, value in (('CONFIG_DIR', str(self.directory)),
                            ('CONFIG_PATH', str(self.directory / 'config.json'))):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_first_launch_save_and_deleted_folder(self):
        self.assertIsNone(config.load_config())
        self.assertFalse(self.directory.exists())
        settings = dict(config.DEFAULT_CONFIG, local_path='C:/CAD/équipe')
        config.save_config(settings)
        self.assertEqual(config.load_config(), settings)
        (self.directory / 'config.json').unlink()
        self.directory.rmdir()
        self.assertIsNone(config.load_config())

    def test_failed_save_preserves_config_and_cleans_temporary_file(self):
        config.save_config(config.DEFAULT_CONFIG)
        with patch('config.os.replace', side_effect=PermissionError('Read only')):
            with self.assertRaises(PermissionError):
                config.save_config({'local_path': 'new'})
        self.assertEqual(config.load_config(), config.DEFAULT_CONFIG)
        self.assertEqual([p.name for p in self.directory.iterdir()], ['config.json'])

    def test_corrupt_and_non_object_config_need_setup(self):
        self.directory.mkdir()
        for content in ('{', '[]', 'null', '"invalid"'):
            with self.subTest(content=content):
                (self.directory / 'config.json').write_text(content)
                self.assertIsNone(config.load_config())

    def test_theme_defaults_and_round_trip(self):
        for value in (None, 'invalid', 42, [], 'light', 'dark', 'system'):
            config.save_config({'local_path': 'C:/CAD', 'theme': value})
            self.assertEqual(config.load_config()['theme'],
                             value if value in ('light', 'dark', 'system') else 'system')
        config.save_config({'local_path': 'C:/CAD'})
        self.assertEqual(config.load_config()['theme'], 'system')


class StartupTests(unittest.TestCase):
    def make_app(self):
        instance = app.App.__new__(app.App)
        instance.root = Mock()
        instance.theme = Mock(preference='system')
        for name in ('_build_ui', '_set_app_icon', '_refresh', '_initial_pull'):
            setattr(instance, name, Mock())
        return instance

    def test_missing_or_stale_config_opens_wizard_before_git_checks(self):
        for settings in (None, {}, {'local_path': 'missing'}):
            with self.subTest(settings=settings):
                instance = self.make_app()
                with patch('app.load_config', return_value=settings), \
                     patch.object(instance, '_is_repo_path', return_value=False), \
                     patch('app.SetupWizard') as wizard, patch('app.check_git') as check:
                    instance._start()
                wizard.assert_called_once()
                check.assert_not_called()
                instance.root.destroy.assert_called_once()
                instance._build_ui.assert_not_called()

    def test_setup_completion_enters_main_app(self):
        instance = self.make_app()
        settings = dict(config.DEFAULT_CONFIG, local_path='CAD')
        with patch('app.load_config', return_value=None), patch('app.save_config') as save, \
             patch('app.SetupWizard', side_effect=lambda root, done: done(settings)):
            instance._start()
        save.assert_called_once_with(settings)
        instance._build_ui.assert_called_once()
        instance._refresh.assert_called_once()

    def test_existing_valid_config_skips_wizard(self):
        instance = self.make_app()
        with patch('app.load_config', return_value={'local_path': 'CAD'}), \
             patch.object(instance, '_is_repo_path', return_value=True), \
             patch('app.refresh_tool_path'), patch('app.check_git', return_value=(True, 'Git')), \
             patch('app.check_git_lfs', return_value=(True, 'LFS')), patch('app.SetupWizard') as wizard:
            instance._start()
        wizard.assert_not_called()
        instance._build_ui.assert_called_once()

    def test_save_failure_does_not_complete_setup(self):
        instance = self.make_app()
        instance.config = None
        with patch('app.save_config', side_effect=OSError('Read only')):
            with self.assertRaises(OSError):
                instance._on_setup_complete({'local_path': 'CAD'})
        self.assertIsNone(instance.config)


class SetupOperationsTests(unittest.TestCase):
    def test_setup_and_later_transfers_skip_ssl_without_changing_parent_environment(self):
        for existing in (False, True):
            for ssh_command in (None, 'ssh -i team-key -o StrictHostKeyChecking=yes'):
                with self.subTest(existing=existing, ssh_command=ssh_command), \
                     tempfile.TemporaryDirectory() as path, \
                     patch.dict(os.environ, {'GIT_SSL_NO_VERIFY': 'false'}), \
                     patch('setup_ops.validate_repository', return_value=path), \
                     patch('git_ops.subprocess.run', return_value=Mock(
                         returncode=0, stdout='true\n', stderr='')) as run, \
                     patch('git_ops._run_transfer', return_value=Mock(
                         returncode=0, stdout='', stderr='')) as transfer, \
                     operation_progress(lambda *event: None):
                    setup_ops.prepare_repository('https://example.com/team/cad.git', path,
                                                 'Designer', 'designer@example.com',
                                                 existing=existing, ssh_command=ssh_command)
                    if existing:
                        transfer.assert_not_called()
                    else:
                        transfer.assert_called_once()
                        self.assertEqual(transfer.call_args.kwargs['env']['GIT_SSL_NO_VERIFY'],
                                         'true')
                        self.assertIn('--progress', transfer.call_args.args[0])
                        if ssh_command:
                            self.assertIn('core.sshCommand=' + ssh_command,
                                          transfer.call_args.args[0])
                    lfs_pulls = [call for call in run.call_args_list
                                 if call.args[0] == ['git', 'lfs', 'pull']]
                    self.assertEqual(len(lfs_pulls), 1)
                    self.assertEqual(lfs_pulls[0].kwargs['env']['GIT_SSL_NO_VERIFY'], 'true')
                    self.assertEqual(os.environ['GIT_SSL_NO_VERIFY'], 'false')
                    _run_git(['fetch'], repo_path=path)
                    self.assertEqual(transfer.call_args.kwargs['env']['GIT_SSL_NO_VERIFY'],
                                     'true')

    def test_existing_repository_operations_skip_ssl_with_and_without_progress(self):
        for reporting in (False, True):
            with self.subTest(reporting=reporting), \
                 patch.dict(os.environ, {'GIT_SSL_NO_VERIFY': 'false'}), \
                 patch('git_ops.is_reporting', return_value=reporting), \
                 patch('git_ops.subprocess.run', return_value=Mock(
                     returncode=0, stdout='', stderr='')) as run, \
                 patch('git_ops._run_transfer', return_value=Mock(
                     returncode=0, stdout='', stderr='')) as transfer:
                for command in ('pull', 'push', 'fetch'):
                    _run_git([command], repo_path='existing-repo')
                for args in (['pull'], ['push', 'origin'], ['locks', '--verify', '--json'],
                             ['lock', 'part.step'], ['unlock', 'part.step']):
                    _run_git_lfs(args, repo_path='existing-repo')
                self.assertEqual(transfer.call_count, 3 if reporting else 0)
                self.assertEqual(run.call_count, 5 if reporting else 8)
                for call in run.call_args_list + transfer.call_args_list:
                    self.assertEqual(call.kwargs['env']['GIT_SSL_NO_VERIFY'], 'true')
                    self.assertEqual(call.kwargs['cwd'], 'existing-repo')
                self.assertEqual(os.environ['GIT_SSL_NO_VERIFY'], 'false')

    def test_failed_setup_transfer_does_not_leak_ssl_override(self):
        for failure in (Mock(returncode=1, stdout='', stderr='Download failed'),
                        subprocess.TimeoutExpired('git', 600)):
            with self.subTest(failure=failure), \
                 patch.dict(os.environ, {'GIT_SSL_NO_VERIFY': 'false'}), \
                 patch('git_ops.subprocess.run', **(
                     {'side_effect': failure} if isinstance(failure, Exception)
                     else {'return_value': failure})) as run:
                with self.assertRaises(GitError):
                    _run_git(['clone', '--', 'https://example.com/team/cad.git', 'CAD'])
                self.assertEqual(run.call_args.kwargs['env']['GIT_SSL_NO_VERIFY'], 'true')
                self.assertEqual(os.environ['GIT_SSL_NO_VERIFY'], 'false')
                run.side_effect = None
                run.return_value = Mock(returncode=0, stdout='', stderr='')
                _run_git(['fetch'])
                self.assertEqual(run.call_args.kwargs['env']['GIT_SSL_NO_VERIFY'], 'true')

    def test_repository_validation_protects_existing_files(self):
        with tempfile.TemporaryDirectory() as path:
            file = Path(path) / 'design.step'
            file.write_text('CAD data')
            with self.assertRaisesRegex(GitError, 'new or empty'):
                setup_ops.validate_repository('https://github.com/team/cad.git', path)
            self.assertEqual(file.read_text(), 'CAD data')

    def test_rejects_options_credentials_and_non_repository_links(self):
        for url in ('--upload-pack=bad', 'ext::bad', 'http://host/repo',
                    'https://host', 'https://user:token@host/repo', 'https://token@host/repo'):
            with self.subTest(url=url), self.assertRaises(GitError):
                setup_ops.validate_repository(url, 'new-repo')

    def test_https_and_preconfigured_ssh_links_are_accepted(self):
        with tempfile.TemporaryDirectory() as path:
            for url in ('https://github.com/team/cad.git', 'git@github.com:team/cad.git',
                        'ssh://git@host/team/cad.git'):
                with self.subTest(url=url):
                    self.assertEqual(setup_ops.validate_repository(url, path), os.path.abspath(path))

    def test_identity_validation(self):
        setup_ops.validate_identity('CAD Designer', 'designer@example.com')
        for name, email in (('', 'a@b'), ('Name', 'no email'), ('Name\nOther', 'a@b')):
            with self.assertRaises(GitError):
                setup_ops.validate_identity(name, email)

    def test_install_skips_ready_tools(self):
        ready = {'git': True, 'lfs': True}
        with patch('setup_ops.check_requirements', return_value=ready), \
             patch('setup_ops.subprocess.run') as run:
            self.assertEqual(setup_ops.install_requirements(), ready)
        run.assert_not_called()

    def test_git_install_that_bundles_lfs_needs_only_one_package(self):
        with patch('setup_ops.check_requirements', side_effect=[
                {'git': False, 'lfs': False}, {'git': True, 'lfs': True}]), \
             patch('setup_ops.os.name', 'nt'), patch('setup_ops.shutil.which', return_value='winget'), \
             patch('setup_ops.subprocess.run', return_value=Mock(returncode=0)) as run:
            self.assertTrue(setup_ops.install_requirements()['lfs'])
        run.assert_called_once()
        self.assertIn('Git.Git', run.call_args.args[0])

    def test_lfs_only_install(self):
        with patch('setup_ops.check_requirements', side_effect=[
                {'git': True, 'lfs': False}, {'git': True, 'lfs': True}]), \
             patch('setup_ops.os.name', 'nt'), patch('setup_ops.shutil.which', return_value='winget'), \
             patch('setup_ops.subprocess.run', return_value=Mock(returncode=0)) as run:
            setup_ops.install_requirements()
        self.assertIn('GitHub.GitLFS', run.call_args.args[0])

    def test_missing_winget_has_manual_fallback(self):
        with patch('setup_ops.check_requirements', return_value={'git': False, 'lfs': False}), \
             patch('setup_ops.shutil.which', return_value=None):
            with self.assertRaisesRegex(GitError, 'download buttons'):
                setup_ops.install_requirements()

    def test_installer_failure_and_timeout_are_retryable(self):
        for result in (Mock(returncode=1, stderr='Installation denied', stdout=''),
                       subprocess.TimeoutExpired('winget', 900)):
            with patch('setup_ops.check_requirements', return_value={'git': False, 'lfs': False}), \
                 patch('setup_ops.os.name', 'nt'), patch('setup_ops.shutil.which', return_value='winget'), \
                 patch('setup_ops.subprocess.run', **(
                     {'side_effect': result} if isinstance(result, Exception) else {'return_value': result})):
                with self.assertRaisesRegex(GitError, 'download buttons'):
                    setup_ops.install_requirements()

    def test_real_repository_setup_and_local_identity(self):
        # Local repositories only: no account/network or user Git config changes.
        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}):
            source = Path(temporary) / 'source'
            source.mkdir()
            _run_git(['init', str(source)])
            _run_git(['-c', 'user.name=Original', '-c', 'user.email=original@example.com',
                      'commit', '--allow-empty', '-m', 'Initial'], repo_path=str(source))
            destination = str(Path(temporary) / 'CAD')
            clone_repo(str(source), destination)
            settings = setup_ops.prepare_repository('', destination, 'Designer',
                                                    'designer@example.com', existing=True)
            self.assertEqual(settings['local_path'], destination)
            self.assertEqual(setup_ops.get_identity(destination), ('Designer', 'designer@example.com'))
            self.assertEqual(setup_ops.get_identity(), ('', ''))
            self.assertTrue((Path(destination) / '.git/hooks/pre-push').exists())
            # The download path runs the same real clone operation with a local test remote.
            other = str(Path(temporary) / 'Other CAD')
            with patch('setup_ops.clone_repo', side_effect=lambda url, path, **kwargs:
                       clone_repo(str(source), path, **kwargs)):
                downloaded = setup_ops.prepare_repository('https://example.com/team/cad.git', other,
                                                          'Designer', 'designer@example.com')
            self.assertEqual(downloaded['local_path'], other)
            for repository in (destination, other):
                with self.assertRaises(GitError):
                    _run_git(['config', '--local', '--get', 'http.sslVerify'],
                             repo_path=repository)


if __name__ == '__main__':
    unittest.main()
