import json
import time
from uuid import uuid4
from agent.memory import now


class GoalManager:
    def __init__(self, memory, max_active=8, max_questions=128, cooldown=60):
        self.m = memory
        self.max_active = max_active
        self.max_questions = max_questions
        self.cooldown = cooldown

    def question(self, s, subject, text, source=None):
        rows = self.m.rows('SELECT id FROM Questions WHERE world=? AND subject=?', (s.world, subject))
        if rows:
            return rows[0]['id']
        if self.m.rows("SELECT count(*) AS n FROM Questions WHERE world=? AND status='open'", (s.world,))[0]['n'] >= self.max_questions:
            return None
        qid = str(uuid4())
        eid = self.m.event(s.world, str(s.session), s.day, 'question', 'Tenho uma nova pergunta: ' + text,
                           True, {'subject': subject, 'source_event': source}, 'question-v2:' + subject)
        self.m.db.execute('INSERT INTO Questions VALUES(?,?,?,?,?,?,?)',
                          (qid, s.world, subject, text, 'open', eid, now()))
        return qid

    def ensure(self, s, subject, description, reason, priority, kind, params, skill, category='SHORT_TERM', blocked=False):
        existing = self.m.rows('SELECT p.*,g.status FROM GoalPlans p JOIN Goals g ON g.id=p.goal_id '
                               'WHERE p.world=? AND p.subject=?', (s.world, subject))
        if existing:
            row = existing[0]
            if not blocked and row['status'] in ('pending', 'suspended', 'deferred', 'blocked') and row['attempts'] < 2 and row['cooldown'] <= time.time():
                active = self.m.rows("SELECT count(*) n FROM Goals WHERE world=? AND status IN ('pending','running')", (s.world,))[0]['n']
                if row['status'] != 'pending' and active >= self.max_active:
                    return row['goal_id']
                self.m.db.execute('UPDATE GoalPlans SET params=? WHERE goal_id=?', (json.dumps(params), row['goal_id']))
                self.m.db.execute("UPDATE Goals SET status='pending',priority=?,reason=? WHERE id=?", (priority, reason, row['goal_id']))
            return row['goal_id']
        statuses = ('blocked',) if blocked else ('pending', 'running')
        count = self.m.rows('SELECT count(*) AS n FROM Goals WHERE world=? AND status IN (' + ','.join('?' for _ in statuses) + ')',
                            (s.world, *statuses))[0]['n']
        if count >= (4 if blocked else self.max_active):
            return None
        gid = str(uuid4())
        self.m.db.execute('INSERT INTO Goals VALUES(?,?,?,?,?,?)',
                          (gid, s.world, description, reason, int(priority), 'blocked' if blocked else 'pending'))
        self.m.db.execute('INSERT INTO GoalPlans(goal_id,world,subject,category,kind,params,skill,created,last_error) '
                          'VALUES(?,?,?,?,?,?,?,?,?)', (gid, s.world, subject, category, kind, json.dumps(params), skill, now(),
                                                      reason if blocked else ''))
        self.m.event(s.world, str(s.session), s.day, 'goal',
                     ('Quero ' + description[0].lower() + description[1:] + '. ' + reason),
                     True, {'goal': gid, 'category': category, 'blocked': blocked}, 'goal:' + gid)
        return gid

    def rows(self, world):
        return self.m.rows('SELECT g.*,p.subject,p.category,p.kind,p.params,p.skill,p.attempts,p.cooldown,p.last_error '
                           "FROM Goals g JOIN GoalPlans p ON p.goal_id=g.id WHERE g.world=? AND g.status IN ('pending','running','suspended','blocked') ORDER BY g.priority DESC,g.rowid LIMIT 64", (world,))

    def failure(self, gid, reason, cancelled=False):
        rows = self.m.rows('SELECT * FROM GoalPlans WHERE goal_id=?', (gid,))
        if not rows:
            return
        row = rows[0]
        attempts = row['attempts'] + int(not cancelled)
        status = 'abandoned' if attempts >= 2 else 'suspended'
        self.m.db.execute('UPDATE GoalPlans SET attempts=?,cooldown=?,last_error=? WHERE goal_id=?',
                          (attempts, time.time() + (2 if cancelled else self.cooldown), reason, gid))
        self.m.db.execute('UPDATE Goals SET status=? WHERE id=?', (status, gid))

    def supersede(self, world, subject):
        self.m.db.execute("UPDATE Goals SET status='completed' WHERE id IN (SELECT goal_id FROM GoalPlans "
                          "WHERE world=? AND subject=?) AND status IN ('pending','suspended','blocked','deferred')", (world, subject))
        self.m.db.execute("UPDATE Questions SET status='answered' WHERE world=? AND subject=?", (world, subject))
