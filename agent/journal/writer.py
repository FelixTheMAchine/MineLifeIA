import hashlib
import json
from pathlib import Path
from uuid import uuid4
from agent.memory import now

README = '''# MineLife AI — Diário

Esta experiência acompanha um agente artificial controlando o personagem local
no Minecraft Survival. As narrativas em primeira pessoa representam uma
personalidade simulada, não consciência ou sentimentos reais.

Entradas são produzidas a partir de eventos registrados. A remoção de um bloco
e a coleta de um item são evidências distintas. Hipóteses não são descobertas.
Os identificadores de evidência permitem auditoria no banco local, que não é
publicado. Um dia sem eventos registrados não recebe uma história inventada.

A publicação ocorre somente após o encerramento de um dia observado e autorização
do usuário para a visibilidade escolhida. Reflexões ficam na subpasta reflections/.
'''


class JournalWriter:
    def __init__(self, memory, export_root):
        self.memory = memory
        self.root = Path(export_root)

    def write(self, world, day, kind='daily', event_id=None):
        source = str(day) if kind == 'daily' else event_id
        found = self.memory.rows('SELECT * FROM JournalEntries WHERE world=? AND kind=? AND source_key=?',
                                 (world, kind, source))
        if found:
            self.export_entry(found[0])
            return found[0]
        events = self.memory.rows('SELECT * FROM Events WHERE world=? AND day=? AND verified=1 '
                                  + ('AND id=? ' if event_id else '') + 'ORDER BY timestamp,id',
                                  (world, day, event_id) if event_id else (world, day))
        if not events:
            return None
        # Every factual sentence is produced by the verified event formatter.
        sentences = [e['description'] for e in events]
        count = sum(e['type'] == 'collected' for e in events)
        intro = ('Hoje registrei uma descoberta apoiada no que observei.' if count else
                 'Hoje acompanhei minhas tentativas e as perguntas que elas trouxeram.')
        text = intro + '\n\n' + '\n\n'.join(dict.fromkeys(sentences))
        ids = [e['id'] for e in events]
        entry = dict(id=str(uuid4()), world=world, day=day, kind=kind, source_key=source,
                     text=text, evidence_ids=json.dumps(ids), timestamp=now())
        self.memory.db.execute('INSERT INTO JournalEntries VALUES(:id,:world,:day,:kind,:source_key,'
                               ':text,:evidence_ids,:timestamp)', entry)
        if kind == 'daily':
            self.memory.db.execute('INSERT OR IGNORE INTO PublicationQueue(world,entry) VALUES(?,?)',
                                   (world, entry['id']))
        self.memory.db.commit()
        self.export_entry(entry)
        return entry

    def finalize_before(self, world, day):
        for row in self.memory.rows('SELECT DISTINCT day FROM Events WHERE world=? AND day<? ORDER BY day',
                                     (world, day)):
            self.write(world, row['day'])

    def directory(self, world):
        return self.root / world

    @staticmethod
    def immutable_write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_text(encoding='utf-8') != content:
                raise ValueError(f'Entrada imutável diverge: {path.name}')
        else:
            with path.open('x', encoding='utf-8', newline='\n') as f:
                f.write(content)

    def export_entry(self, entry):
        directory = self.directory(entry['world'])
        self.immutable_write(directory / 'README.md', README)
        filename = (f"day_{entry['day']:03d}.md" if entry['kind'] == 'daily' else
                    f"reflections/day_{entry['day']:03d}_{entry['id']}.md")
        evidence = ', '.join(json.loads(entry['evidence_ids']))
        content = (f"# Dia {entry['day']} — {'Diário' if entry['kind'] == 'daily' else 'Reflexão'}\n\n"
                   f"{entry['text']}\n\nEvidências: {evidence}\n\nRegistro: {entry['id']}\n")
        self.immutable_write(directory / filename, content)

    def export_all(self, world):
        for entry in self.memory.rows('SELECT * FROM JournalEntries WHERE world=?', (world,)):
            self.export_entry(entry)
        return self.directory(world)
