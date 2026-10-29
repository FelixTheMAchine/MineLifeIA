from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from agent.memory import MemoryManager


class MigrationTest(unittest.TestCase):
    def test_backup_and_idempotent_migration_preserve_verified_knowledge(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'memory.sqlite3'
            m=MemoryManager(path)
            eid=m.event('a'*64,'session',1,'collected','Coleta fixture verificada.',True,{'fixture':True},'real-style-event')
            m.db.execute("INSERT INTO Knowledge VALUES(?,?,'confirmed',?)",('a'*64,'minecraft:birch_log','["'+eid+'"]'))
            m.db.execute('PRAGMA user_version=0')
            m.close()
            for _ in range(2):
                m=MemoryManager(path)
                self.assertEqual(m.rows('SELECT status FROM Knowledge')[0]['status'],'confirmed')
                self.assertEqual(m.rows('SELECT id FROM Events')[0]['id'],eid)
                m.close()
            backups=list((Path(td)/'backups').glob('*.sqlite3'))
            self.assertEqual(len(backups),1)
            with closing(sqlite3.connect(backups[0])) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(db.execute('SELECT id FROM Events').fetchone()[0],eid)
