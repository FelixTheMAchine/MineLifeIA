import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class MemoryManager:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS Worlds(id TEXT PRIMARY KEY, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS Events(id TEXT PRIMARY KEY, world TEXT NOT NULL,
            session TEXT NOT NULL, day INTEGER NOT NULL, timestamp TEXT NOT NULL,
            type TEXT NOT NULL, description TEXT NOT NULL, verified INTEGER NOT NULL,
            evidence TEXT NOT NULL, dedup TEXT NOT NULL, UNIQUE(world,dedup));
          CREATE TABLE IF NOT EXISTS Observations(id TEXT PRIMARY KEY, world TEXT NOT NULL,
            session TEXT NOT NULL, day INTEGER NOT NULL, timestamp TEXT NOT NULL,
            seq INTEGER NOT NULL, payload TEXT NOT NULL, UNIQUE(session,seq));
          CREATE TABLE IF NOT EXISTS Knowledge(world TEXT NOT NULL, subject TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('unknown','hypothesis','partial','confirmed','contradicted')),
            evidence_ids TEXT NOT NULL, PRIMARY KEY(world,subject));
          CREATE TABLE IF NOT EXISTS Hypotheses(id TEXT PRIMARY KEY, world TEXT NOT NULL,
            question TEXT NOT NULL, statement TEXT NOT NULL, status TEXT NOT NULL,
            evidence_ids TEXT NOT NULL, UNIQUE(world,question));
          CREATE TABLE IF NOT EXISTS Experiments(id TEXT PRIMARY KEY, world TEXT NOT NULL,
            session TEXT NOT NULL, hypothesis TEXT NOT NULL, target TEXT NOT NULL,
            phase TEXT NOT NULL, status TEXT NOT NULL, evidence_ids TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS Goals(id TEXT PRIMARY KEY, world TEXT NOT NULL,
            description TEXT NOT NULL, reason TEXT NOT NULL, priority INTEGER NOT NULL, status TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS Commands(id TEXT PRIMARY KEY, world TEXT NOT NULL,
            session TEXT NOT NULL, experiment TEXT NOT NULL, payload TEXT NOT NULL,
            status TEXT NOT NULL, result TEXT, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS JournalEntries(id TEXT PRIMARY KEY, world TEXT NOT NULL,
            day INTEGER NOT NULL, kind TEXT NOT NULL, source_key TEXT NOT NULL,
            text TEXT NOT NULL, evidence_ids TEXT NOT NULL, timestamp TEXT NOT NULL,
            UNIQUE(world,kind,source_key));
          CREATE TABLE IF NOT EXISTS PublicationQueue(world TEXT NOT NULL, entry TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending', error TEXT);
          CREATE TABLE IF NOT EXISTS Personality(world TEXT PRIMARY KEY, values_json TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS events_world_day ON Events(world,day);
        ''')
        self.db.commit()

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def event(self, world, session, day, kind, description, verified, evidence, dedup):
        event_id = str(uuid4())
        self.db.execute('INSERT OR IGNORE INTO Events VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (event_id, world, session, day, now(), kind, description,
                         int(verified), json.dumps(evidence, ensure_ascii=False), dedup))
        return self.db.execute('SELECT id FROM Events WHERE world=? AND dedup=?',
                               (world, dedup)).fetchone()[0]

    def close(self):
        self.db.commit()
        self.db.close()
