from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from agent.memory import MemoryManager
from scripts.verify_memory_upgrade import fingerprint


class MigrationTest(unittest.TestCase):
    def test_v3_to_v4_preserves_all_old_tables_and_creates_one_verified_backup(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'memory.sqlite3'
            m=MemoryManager(path)
            m.event('a'*64,'session',1,'collected','Fixture histórica.',True,{'fixture':True},'legacy')
            m.db.execute('DROP TABLE ConstructionSteps');m.db.execute('DROP TABLE ConstructionProjects')
            m.db.execute('PRAGMA user_version=3');m.close()
            before=fingerprint(path)
            for _ in range(2):
                m=MemoryManager(path)
                self.assertEqual(m.db.execute('PRAGMA user_version').fetchone()[0],4)
                self.assertEqual(m.rows('SELECT * FROM ConstructionProjects'),[])
                m.close()
            self.assertEqual(before,fingerprint(path,before))
            backups=list((path.parent/'backups').glob('*.sqlite3'))
            self.assertEqual(len(backups),1)
            self.assertEqual(before,fingerprint(backups[0],before))

    def test_newer_schema_is_not_silently_downgraded(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'memory.sqlite3';m=MemoryManager(path)
            m.db.execute('PRAGMA user_version=99');m.close()
            with self.assertRaises(ValueError):MemoryManager(path)
            with closing(sqlite3.connect(path)) as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],99)

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
