import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class MemoryManager:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if Path(path).exists():
            with closing(sqlite3.connect(path)) as existing:
                version = existing.execute('PRAGMA user_version').fetchone()[0]
            if version < 3:
                from scripts.backup_memory import backup
                backup(path)
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
          CREATE TABLE IF NOT EXISTS Questions(id TEXT PRIMARY KEY, world TEXT NOT NULL,
            subject TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL,
            source_event TEXT, created TEXT NOT NULL, UNIQUE(world,subject));
          CREATE TABLE IF NOT EXISTS GoalPlans(goal_id TEXT PRIMARY KEY, world TEXT NOT NULL,
            subject TEXT NOT NULL, category TEXT NOT NULL, kind TEXT NOT NULL,
            params TEXT NOT NULL, skill TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            cooldown REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL, UNIQUE(world,subject));
          CREATE TABLE IF NOT EXISTS SpatialRegions(world TEXT NOT NULL, dimension TEXT NOT NULL,
            rx INTEGER NOT NULL, ry INTEGER NOT NULL, rz INTEGER NOT NULL,
            visits INTEGER NOT NULL, biome TEXT NOT NULL, resources TEXT NOT NULL,
            dangers TEXT NOT NULL, unknowns TEXT NOT NULL, interests TEXT NOT NULL, last_visit TEXT NOT NULL,
            PRIMARY KEY(world,dimension,rx,ry,rz));
          CREATE TABLE IF NOT EXISTS Interests(world TEXT NOT NULL, topic TEXT NOT NULL,
            intensity REAL NOT NULL, origin TEXT NOT NULL, evidence_ids TEXT NOT NULL,
            positive INTEGER NOT NULL, negative INTEGER NOT NULL, goals TEXT NOT NULL,
            PRIMARY KEY(world,topic));
          CREATE TABLE IF NOT EXISTS InterestUpdates(world TEXT NOT NULL, topic TEXT NOT NULL,
            source TEXT NOT NULL, PRIMARY KEY(world,topic,source));
          CREATE TABLE IF NOT EXISTS Motivations(world TEXT NOT NULL, name TEXT NOT NULL,
            score REAL NOT NULL, reason TEXT NOT NULL, updated TEXT NOT NULL,
            PRIMARY KEY(world,name));
          CREATE TABLE IF NOT EXISTS SkillProgress(world TEXT NOT NULL, name TEXT NOT NULL,
            successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(world,name));
          CREATE TABLE IF NOT EXISTS Reflections(id TEXT PRIMARY KEY, world TEXT NOT NULL,
            experiment TEXT NOT NULL UNIQUE, outcome TEXT NOT NULL, confidence REAL NOT NULL,
            evidence_ids TEXT NOT NULL, next_step TEXT NOT NULL, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS CognitiveState(world TEXT PRIMARY KEY, state TEXT NOT NULL,
            reason TEXT NOT NULL, motivation TEXT NOT NULL, updated TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS AgentMigrations(world TEXT NOT NULL, version INTEGER NOT NULL,
            PRIMARY KEY(world,version));
          CREATE TABLE IF NOT EXISTS ExperimentGoals(experiment TEXT PRIMARY KEY, goal_id TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS PersonalityChanges(id TEXT PRIMARY KEY, world TEXT NOT NULL,
            trait TEXT NOT NULL, old_value REAL NOT NULL, new_value REAL NOT NULL,
            reason TEXT NOT NULL, source_event TEXT NOT NULL, created TEXT NOT NULL,
            UNIQUE(world,trait,source_event));
          CREATE TABLE IF NOT EXISTS LifeMemories(id TEXT PRIMARY KEY,world TEXT NOT NULL,
            source_event TEXT NOT NULL,theme TEXT NOT NULL,summary TEXT NOT NULL,importance REAL NOT NULL,
            novelty REAL NOT NULL,context TEXT NOT NULL,created TEXT NOT NULL,UNIQUE(world,source_event,theme));
          CREATE INDEX IF NOT EXISTS life_memories_recall ON LifeMemories(world,theme,importance);
          CREATE TABLE IF NOT EXISTS PhilosophicalQuestions(id TEXT PRIMARY KEY,world TEXT NOT NULL,
            theme TEXT NOT NULL,question TEXT NOT NULL,origin_event TEXT NOT NULL,
            interpretation TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL,
            UNIQUE(world,theme,origin_event));
          CREATE TABLE IF NOT EXISTS PhilosophicalRevisions(id TEXT PRIMARY KEY,world TEXT NOT NULL,
            theme TEXT NOT NULL,origin_event TEXT NOT NULL,previous TEXT NOT NULL,current TEXT NOT NULL,
            evidence_ids TEXT NOT NULL,change_reason TEXT NOT NULL,confidence REAL NOT NULL,created TEXT NOT NULL,
            UNIQUE(world,theme,origin_event));
          CREATE TABLE IF NOT EXISTS JournalProvenance(entry_id TEXT PRIMARY KEY,renderer INTEGER NOT NULL,
            manifest TEXT NOT NULL,manifest_hash TEXT NOT NULL,text_hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS CognitiveSuggestions(id TEXT PRIMARY KEY,world TEXT NOT NULL,
            purpose TEXT NOT NULL,preferred_subject TEXT,question TEXT NOT NULL,hypothesis TEXT NOT NULL,
            interpretation TEXT NOT NULL,journal_draft TEXT NOT NULL,social_interpretation TEXT NOT NULL,
            source_event_ids TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL,UNIQUE(world,id));
          CREATE INDEX IF NOT EXISTS commands_pending ON Commands(session,status);
          CREATE INDEX IF NOT EXISTS experiments_active ON Experiments(world,session,status);
          CREATE INDEX IF NOT EXISTS goals_world_status ON Goals(world,status);
        ''')
        # Migration v3 is additive; v0.1/v0.2 memory and journal rows remain intact.
        self.db.execute('PRAGMA user_version=3')
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
