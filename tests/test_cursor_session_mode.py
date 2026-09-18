import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import MagicMock, patch

from agents.cursor import CursorAgent


class CursorSessionModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / '项目'
        self.work.mkdir()
        self.config = self.root / 'cursor-config'
        self.session = 'saved-session'
        digest = hashlib.md5(os.path.abspath(self.work).encode()).hexdigest()
        self.db_path = self.config / 'chats' / digest / self.session / 'store.db'
        env = patch.dict(os.environ, {'CURSOR_CONFIG_DIR': str(self.config), 'XDG_CONFIG_HOME': ''})
        env.start()
        self.addCleanup(env.stop)
        base = patch('agents.cursor.build_cursor_base_cmd', return_value=['agent', '-p', '--force'])
        base.start()
        self.addCleanup(base.stop)
        self.process = MagicMock()
        self.process.stdout.readline.return_value = ''
        self.process.poll.return_value = 0
        self.process.returncode = 0

    def seed(self, mode):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        meta = dict(agentId=self.session, mode=mode, name='existing task',
                    latestRootBlobId=[1, 2], blobEncryptionKey=[3, 4], isRunEverything=True)
        raw = json.dumps(meta, ensure_ascii=False).encode().hex()
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS blobs (id TEXT PRIMARY KEY, data BLOB)')
            db.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)', ('0', raw))
            db.execute('INSERT OR REPLACE INTO blobs VALUES (?, ?)', ('history', b'original conversation'))
        return meta, raw

    def read(self):
        with closing(sqlite3.connect(self.db_path)) as db, db:
            raw = db.execute('SELECT value FROM meta WHERE key="0"').fetchone()[0]
            blobs = db.execute('SELECT * FROM blobs').fetchall()
        return json.loads(bytes.fromhex(raw)), raw, blobs

    def test_readonly_mode_is_reset_before_resuming_same_conversation(self):
        for mode in ('search', 'ask', 'chat', 'plan', 'architect'):
            with self.subTest(mode=mode):
                original, _ = self.seed(mode)
                def spawn(cmd, **kwargs):
                    meta, _, blobs = self.read()
                    self.assertEqual(meta, {**original, 'mode': 'default'})
                    self.assertEqual(blobs, [('history', b'original conversation')])
                    self.assertEqual(cmd[cmd.index('--resume') + 1], self.session)
                    self.assertNotIn('--mode', cmd)
                    return self.process
                with patch('agents.cursor.subprocess.Popen', side_effect=spawn):
                    result = CursorAgent()._run_once(str(self.work), 'write report', None, self.session, None)
                self.assertEqual(result.returncode, 0, result.error)

    def test_writable_mode_does_not_rewrite_metadata(self):
        for mode in ('default', 'agent', 'code', 'debug'):
            with self.subTest(mode=mode):
                _, raw = self.seed(mode)
                with patch('agents.cursor.subprocess.Popen', return_value=self.process):
                    result = CursorAgent()._run_once(str(self.work), 'task', None, self.session, None)
                self.assertEqual(result.returncode, 0, result.error)
                self.assertEqual(self.read()[1], raw)

    def test_fresh_session_does_not_touch_existing_readonly_session(self):
        _, raw = self.seed('search')
        with patch('agents.cursor.subprocess.Popen', return_value=self.process) as spawn:
            result = CursorAgent()._run_once(str(self.work), 'task', None, None, None)
        self.assertEqual(result.returncode, 0, result.error)
        self.assertNotIn('--resume', spawn.call_args.args[0])
        self.assertEqual(self.read()[1], raw)

    def test_missing_store_is_not_created_and_normal_cli_recovery_remains_available(self):
        with patch('agents.cursor.subprocess.Popen', return_value=self.process) as spawn:
            result = CursorAgent()._run_once(str(self.work), 'task', None, self.session, None)
        self.assertEqual(result.returncode, 0, result.error)
        self.assertIn('--resume', spawn.call_args.args[0])
        self.assertFalse(self.db_path.exists())

    def test_unknown_or_corrupt_metadata_uses_fresh_session_without_overwriting_store(self):
        for kind in ('unknown-mode', 'bad-encoding', 'wrong-agent'):
            with self.subTest(kind=kind):
                meta, _ = self.seed('future-mode')
                raw = 'not-supported'
                if kind == 'unknown-mode': raw = json.dumps(meta).encode().hex()
                if kind == 'wrong-agent': raw = json.dumps({**meta, 'agentId': 'another-agent'}).encode().hex()
                with closing(sqlite3.connect(self.db_path)) as db, db:
                    db.execute('UPDATE meta SET value=? WHERE key="0"', (raw,))
                adapter = CursorAgent()
                events = []
                adapter.session_invalidation_callback = lambda: events.append('invalidate')
                def spawn(cmd, **kwargs):
                    self.assertEqual(events, ['invalidate'])
                    self.assertNotIn('--resume', cmd)
                    self.assertIn('/dependency', cmd[-1])
                    return self.process
                with patch('agents.cursor.subprocess.Popen', side_effect=spawn):
                    result = adapter._run_once(str(self.work), 'task', None, self.session, ['/dependency'])
                self.assertEqual(result.returncode, 0, result.error)
                self.assertIsNone(result.session_id)
                with closing(sqlite3.connect(self.db_path)) as db, db:
                    self.assertEqual(db.execute('SELECT value FROM meta WHERE key="0"').fetchone()[0], raw)

    def test_relative_config_root_is_resolved_against_cursor_work_dir(self):
        self.config = self.work / 'relative-config'
        digest = hashlib.md5(os.path.abspath(self.work).encode()).hexdigest()
        self.db_path = self.config / 'chats' / digest / self.session / 'store.db'
        self.seed('search')
        with patch.dict(os.environ, {'CURSOR_CONFIG_DIR': 'relative-config'}), \
                patch('agents.cursor.subprocess.Popen', return_value=self.process):
            result = CursorAgent()._run_once(str(self.work), 'task', None, self.session, None)
        self.assertEqual(result.returncode, 0, result.error)
        self.assertEqual(self.read()[0]['mode'], 'default')

    def test_xdg_config_root_matches_cursor_layout(self):
        self.config = self.root / 'xdg' / 'cursor'
        digest = hashlib.md5(os.path.abspath(self.work).encode()).hexdigest()
        self.db_path = self.config / 'chats' / digest / self.session / 'store.db'
        self.seed('plan')
        with patch.dict(os.environ, {'CURSOR_CONFIG_DIR': '', 'XDG_CONFIG_HOME': str(self.root / 'xdg')}), \
                patch('agents.cursor.subprocess.Popen', return_value=self.process):
            result = CursorAgent()._run_once(str(self.work), 'task', None, self.session, None)
        self.assertEqual(result.returncode, 0, result.error)
        self.assertEqual(self.read()[0]['mode'], 'default')

    def test_failed_mode_update_detaches_durably_before_starting_fresh(self):
        self.seed('search')
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("CREATE TRIGGER deny_mode_update BEFORE UPDATE ON meta "
                       "BEGIN SELECT RAISE(ABORT, 'read only'); END")
        adapter = CursorAgent()
        detached = []
        adapter.session_invalidation_callback = lambda: detached.append(True)
        def spawn(cmd, **kwargs):
            self.assertEqual(detached, [True])
            self.assertNotIn('--resume', cmd)
            return self.process
        with patch('agents.cursor.subprocess.Popen', side_effect=spawn):
            result = adapter._run_once(str(self.work), 'task', None, self.session, None)
        self.assertEqual(result.returncode, 0, result.error)
        self.assertEqual(self.read()[0]['mode'], 'search')

    def test_failed_durable_detachment_does_not_start_cursor(self):
        self.seed('unknown-mode')
        adapter = CursorAgent()
        adapter.session_invalidation_callback = MagicMock(side_effect=RuntimeError('persistence failed'))
        with patch('agents.cursor.subprocess.Popen') as spawn:
            result = adapter._run_once(str(self.work), 'task', None, self.session, None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('persistence failed', result.error)
        spawn.assert_not_called()
