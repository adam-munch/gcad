import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from git_ops import GitError, _run_transfer, get_file_statuses, lock_files, pull_repo
from progress import operation_progress, report, is_reporting


class ProgressTests(unittest.TestCase):
    def test_observer_is_scoped_and_not_shared_with_other_workers(self):
        events = []
        with operation_progress(lambda *event: events.append(event)):
            report('Here')
            thread = threading.Thread(target=lambda: report('Other worker'))
            thread.start()
            thread.join()
        self.assertFalse(is_reporting())
        self.assertEqual([event[0] for event in events], ['Here'])

    def test_batch_progress_counts_only_successful_files(self):
        events = []
        with operation_progress(lambda *event: events.append(event)), \
             patch('git_ops._run_git_lfs', side_effect=[None, GitError('Denied')]):
            with self.assertRaises(GitError):
                lock_files('repo', ['a.step', 'b.step', 'c.step'])
        self.assertEqual([(e[1], e[2]) for e in events], [(0, 3), (1, 3), (1, 3)])
        self.assertIn('b.step', events[-1][0])

    def test_pull_reports_network_and_large_file_stages(self):
        events = []
        with operation_progress(lambda *event: events.append(event)), patch('git_ops._run_git'):
            pull_repo('repo')
        self.assertIn('Syncing', events[0][0])
        self.assertIn('Git LFS', events[1][0])

    def test_lock_lookup_failure_is_visible_but_local_scan_failure_is_fatal(self):
        events = []
        with operation_progress(lambda *event: events.append(event)), \
             patch('git_ops._run_git_lfs', side_effect=GitError('Offline')), \
             patch('git_ops._run_git', side_effect=[
                 '', '{"files": [{"name": "part.step"}]}']):
            self.assertEqual(len(get_file_statuses('repo')), 1)
        self.assertTrue(any(e[3] == 'warning' for e in events))
        with patch('git_ops._run_git_lfs', return_value='{}'), \
             patch('git_ops._run_git', side_effect=GitError('Unreadable')):
            with self.assertRaises(GitError):
                get_file_statuses('repo')

    def test_transfer_progress_arrives_before_exit_and_preserves_output(self):
        events = []
        start = time.monotonic()
        command = [sys.executable, '-u', '-c',
                   "import sys,time; print('Receiving objects: 25%',file=sys.stderr,flush=True); "
                   "time.sleep(0.5); print('result'); print('done',file=sys.stderr)"]
        with operation_progress(lambda *event: events.append((time.monotonic(), event))):
            result = _run_transfer(command, timeout=5, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), 'result')
        self.assertIn('done', result.stderr)
        self.assertTrue(events)
        self.assertLess(events[0][0] - start, 0.5)

    def test_transfer_timeout_stops_process(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            _run_transfer([sys.executable, '-c', 'import time; time.sleep(10)'],
                          timeout=0.1, capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
