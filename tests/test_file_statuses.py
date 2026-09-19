"""File identity regressions using local Git/LFS repositories."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from git_ops import _run_git, _run_git_lfs, get_file_statuses


class FileStatusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        environment = patch.dict(os.environ, {
            'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.git('init')
        self.git('config', 'user.name', 'Test Designer')
        self.git('config', 'user.email', 'designer@example.com')
        self.git('lfs', 'install', '--local')
        self.git('lfs', 'track', '*.step')
        self.paths = ['Chassis/front wing.step', 'Suspension/café.step',
                      'plain.step', ' Chassis/ bracket.step']
        for path in self.paths:
            self.write(path, 'original CAD data\n')
        self.git('add', '.')
        self.git('commit', '-m', 'Initial CAD files')

    def git(self, *args):
        return _run_git(list(args), repo_path=str(self.repo))

    def write(self, path, content):
        file = self.repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding='utf-8')

    def statuses(self, ours=()):
        # Only the server lookup is simulated; status and LFS inventory are real.
        def lfs(args, **kwargs):
            if args[0] == 'locks':
                return json.dumps({'ours': [
                    {'path': path, 'owner': {'name': 'Test Designer'}} for path in ours
                ]})
            return _run_git_lfs(args, **kwargs)

        with patch('git_ops._run_git_lfs', side_effect=lfs):
            rows = get_file_statuses(str(self.repo))
        self.assertEqual(len(rows), len({row['path'] for row in rows}))
        return {row['path']: row for row in rows}

    def test_modified_files_update_existing_entries_before_and_after_staging(self):
        self.assertEqual(set(self.statuses()), set(self.paths))
        for path in self.paths:
            self.write(path, 'edited CAD data\n')
        for staged in (False, True):
            with self.subTest(staged=staged):
                if staged:
                    self.git('add', '.')
                rows = self.statuses(ours=[self.paths[0]])
                self.assertEqual(set(rows), set(self.paths))
                for path, row in rows.items():
                    self.assertEqual(row['status'], 'locked_by_me_modified'
                                     if path == self.paths[0] else 'modified')
                    self.assertTrue(row['is_lfs'])

    def test_deleted_and_untracked_paths_keep_their_original_names(self):
        deleted = self.paths[0]
        (self.repo / deleted).unlink()
        added = 'New assembly/équerre plate.step'
        self.write(added, 'new CAD data\n')
        rows = self.statuses()
        self.assertEqual(set(rows), set(self.paths) | {added})
        self.assertEqual(rows[deleted]['status'], 'deleted')
        self.assertEqual(rows[added]['status'], 'new')

    def test_rename_uses_destination_and_does_not_consume_next_status(self):
        source = self.paths[0]
        destination = 'Chassis/renamed wing.step'
        self.git('mv', '--', source, destination)
        self.write('plain.step', 'edited CAD data\n')
        rows = self.statuses()
        self.assertEqual(set(rows), (set(self.paths) - {source}) | {destination})
        self.assertEqual(rows[destination]['status'], 'modified')
        self.assertTrue(rows[destination]['is_lfs'])
        self.assertEqual(rows['plain.step']['status'], 'modified')


if __name__ == '__main__':
    unittest.main()
