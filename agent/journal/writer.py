"""Diário autobiográfico renderizado somente a partir de eventos e memórias ligados por IDs."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from agent.memory import now
from agent.motivation import PERSONALITY

LEGACY_INTROS = ('Hoje registrei uma descoberta apoiada no que observei.',
                 'Hoje acompanhei minhas tentativas e as perguntas que elas trouxeram.')
INTROS = ('Estas são as experiências e decisões que registrei hoje.',
          'Quero guardar o que observei e o que ainda preciso compreender.',
          'Ao reler minhas experiências, consigo separar resultados e perguntas.',
          'Registro aqui minhas tentativas, com cuidado para não confundir hipótese e descoberta.')

README = '''# MineLife AI — Diário

Esta experiência acompanha um agente artificial que controla o personagem local no Minecraft Survival. A primeira pessoa expressa uma personalidade simulada, não consciência ou sentimentos reais.

Entradas derivam de eventos registrados e mantêm referências verificáveis. Coleta, crafting, observação e movimento têm critérios próprios. Interpretações filosóficas são marcadas como provisórias e apontam para a experiência que as motivou; perguntas não são descobertas.

Os diários completos podem ser publicados somente após revisão, validação de proveniência e autorização explícita para a visibilidade do repositório. O banco privado e as memórias locais não são publicados.
'''


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def valid_narrative(text, descriptions):
    """Aceita apenas o formato histórico do writer v1; novas entradas usam proveniência v3."""
    suffix = '\n\n'.join(dict.fromkeys(descriptions))
    return text in [intro + '\n\n' + suffix for intro in (*LEGACY_INTROS, *INTROS)]


class JournalWriter:
    def __init__(self, memory, export_root):
        self.memory = memory
        self.root = Path(export_root)

    def _style(self, world):
        rows = self.memory.rows('SELECT values_json FROM Personality WHERE world=?', (world,))
        return {**PERSONALITY, **(json.loads(rows[0]['values_json']) if rows else {})}

    def _events(self, world, day, ids):
        if not ids:
            return []
        records = self.memory.rows('SELECT * FROM Events WHERE world=? AND day=? AND verified=1 ORDER BY timestamp,id',
                                   (world, day))
        by_id = {e['id']: e for e in records}
        if any(eid not in by_id for eid in ids):
            return []
        return [by_id[eid] for eid in ids]

    def _thoughts(self, world, day, event_ids):
        if not event_ids:
            return []
        rows = self.memory.rows('SELECT q.*,r.current,r.evidence_ids FROM PhilosophicalQuestions q '
                                'JOIN PhilosophicalRevisions r ON r.world=q.world AND r.theme=q.theme AND r.origin_event=q.origin_event '
                                'WHERE q.world=? AND q.origin_event IN (' + ','.join('?' for _ in event_ids) + ') '
                                'ORDER BY q.created,q.id', (world, *event_ids))
        return rows

    def _related_memories(self, world, day, events):
        if not events:
            return []
        cues = set((events[0]['description'] + ' ' + ' '.join(e['type'] for e in events)).lower().replace(':', ' ').split())
        rows = self.memory.rows('SELECT lm.*,e.day source_day,e.verified FROM LifeMemories lm JOIN Events e '
                                'ON e.id=lm.source_event AND e.world=lm.world WHERE lm.world=? AND e.day<? '
                                'AND e.verified=1 ORDER BY lm.importance DESC,lm.novelty DESC,e.day DESC LIMIT 40',
                                (world, day))
        ranked = []
        for row in rows:
            terms = set((row['theme'] + ' ' + row['summary']).lower().replace(':', ' ').split())
            overlap = sum(len(t) >= 4 for t in cues & terms)
            if overlap:
                ranked.append((row['importance'] + overlap * .03, row))
        ranked.sort(key=lambda x: (x[0], x[1]['source_day']), reverse=True)
        return [dict(row) for _, row in ranked[:1]]

    @staticmethod
    def _voice(event, style):
        kind = event['type']
        if kind == 'collected':
            if style.get('prudence', 60) > style.get('curiosity', 95):
                return 'Guardo com cuidado o alcance dessa evidência: ela confirma esta coleta, enquanto outras aplicações continuam sem teste.'
            return 'Esta resposta observada me deixa uma nova margem para investigar, sem transformar possibilidades em fatos.'
        if kind == 'crafted':
            return 'A transformação dos itens e a estatística do servidor sustentam este resultado; o que construirei depois ainda está em aberto.'
        if kind == 'placed':
            return 'Escolhi um espaço e coloquei ali uma estação. Registrei a mudança no mundo e o material gasto; o próximo uso ainda precisa acontecer.'
        if kind=='shelter_completed':
            return 'O lugar que planejei ganhou paredes, teto e uma entrada verificáveis. Quero descobrir como ter esse ponto de retorno pode mudar minhas escolhas.'
        if kind=='shelter_entered':
            return 'Entrei e fechei a porta. Posso considerar a próxima decisão a partir deste lugar, sem transformar uma entrada confirmada na história de uma noite que ainda não terminou.'
        if kind=='shelter_left':
            return 'Voltei ao lado de fora. O que deixei para trás permanece na memória como um lugar observado, e as próximas experiências ainda estão por acontecer.'
        if kind == 'ate':
            return 'A alteração observada na fome confirmou o efeito desta refeição. Precisei cuidar de uma necessidade imediata antes de escolher o próximo caminho.'
        if kind == 'crop_harvested':
            return 'O cultivo maduro deixou de ocupar aquele bloco, como confirmou o servidor. Ainda preciso observar os itens que possam ter caído antes de dizer o que obtive.'
        if kind == 'slept':
            return 'Usei uma cama durante a noite; a estatística de repouso e a mudança do horário foram confirmadas pelo servidor. Amanhecer não me diz, por si só, o que me espera lá fora.'
        if kind == 'attempt_failed':
            return 'A tentativa não forneceu prova suficiente. Posso mudar uma condição antes de considerar outra tentativa.'
        if kind == 'region_reached':
            return 'Registrei a posição alcançada e o bioma observado; isso acrescenta um ponto ao mapa, mas não certifica os caminhos ao redor.'
        if kind == 'observed':
            return 'Confirmei a presença desse bloco. Ainda não testei suas propriedades nem o que poderia fornecer.'
        return None

    @staticmethod
    def _opening(events, style, day, kind):
        if kind == 'reflection':
            first = events[0]
            return 'Quero guardar esta experiência específica e a pergunta que nasceu dela.' if first['type'] in ('collected', 'crafted', 'region_reached', 'ate', 'crop_harvested', 'slept') else 'Registro esta tentativa junto com o que ela ainda não me permite concluir.'
        types = {e['type'] for e in events}
        if 'region_reached' in types and style.get('exploration', 95) >= 60:
            return f'No dia {day}, acrescentei ao meu mapa uma região cuja chegada foi confirmada.'
        if 'attempt_failed' in types and style.get('prudence', 60) >= 60:
            return 'Hoje precisei distinguir uma tentativa registrada de um resultado que ainda não consegui confirmar.'
        if 'crafted' in types:
            return 'Uma transformação observada entrou para o que posso recordar e testar em seguida.'
        if 'collected' in types:
            return 'Hoje obtive uma resposta limitada, acompanhada de uma pergunta que permanece aberta.'
        return f'No dia {day}, reuni os acontecimentos que pude registrar neste mundo.'

    def _render(self, events, thoughts, memories, style, day, kind):
        if not events:
            raise ValueError('Não há eventos verificados para este diário')
        paragraphs = [self._opening(events, style, day, kind)]
        for event in events:
            paragraphs.append(event['description'])
            voice = self._voice(event, style)
            if voice:
                paragraphs.append(voice)
            for thought in (t for t in thoughts if t['origin_event'] == event['id']):
                paragraphs.append('Dessa experiência nasceu uma pergunta ainda aberta: “' + thought['question'] + '”')
                paragraphs.append('Minha interpretação provisória, ligada a essa evidência, é: ' + thought['current'])
        for memory in memories:
            paragraphs.append(f"Ao reler o registro do dia {memory['source_day']}, encontrei esta experiência anterior: “{memory['summary']}”")
            paragraphs.append('A comparação entre esses registros é uma associação narrativa; cada acontecimento continua apoiado em sua própria evidência.')
        # Deduplica blocos mantendo ordem; não modifica entradas antigas.
        return '\n\n'.join(dict.fromkeys(paragraphs))

    def _manifest(self, world, day, kind, events):
        event_ids = [e['id'] for e in events]
        thoughts = self._thoughts(world, day, event_ids)
        memories = self._related_memories(world, day, events) if kind == 'daily' else []
        return {'version': 3, 'world': world, 'day': day, 'kind': kind, 'event_ids': event_ids,
                'thought_ids': [t['id'] for t in thoughts], 'memory_ids': [m['id'] for m in memories],
                'style': self._style(world)}

    def validate_entry(self, entry):
        provenance = self.memory.rows('SELECT * FROM JournalProvenance WHERE entry_id=?', (entry['id'],))
        if not provenance:
            descriptions = []
            for eid in json.loads(entry['evidence_ids']):
                rows = self.memory.rows('SELECT description FROM Events WHERE id=? AND world=? AND day=? AND verified=1',
                                        (eid, entry['world'], entry['day']))
                if not rows:
                    return False
                descriptions.append(rows[0]['description'])
            return bool(descriptions) and all(d in entry['text'] for d in descriptions) and valid_narrative(entry['text'], list(dict.fromkeys(descriptions)))
        p = provenance[0]
        if p['renderer'] != 3 or _hash(p['manifest']) != p['manifest_hash'] or _hash(entry['text']) != p['text_hash']:
            return False
        try:
            manifest = json.loads(p['manifest'])
            if (manifest.get('version') != 3 or manifest.get('world') != entry['world'] or
                    manifest.get('day') != entry['day'] or manifest.get('kind') != entry['kind']):
                return False
            events = self._events(entry['world'], entry['day'], manifest['event_ids'])
            if len(events) != len(manifest['event_ids']):
                return False
            thoughts = self.memory.rows('SELECT q.*,r.current FROM PhilosophicalQuestions q JOIN PhilosophicalRevisions r '
                                        'ON r.world=q.world AND r.theme=q.theme AND r.origin_event=q.origin_event '
                                        'WHERE q.id IN (' + ','.join('?' for _ in manifest['thought_ids']) + ')', manifest['thought_ids']) if manifest['thought_ids'] else []
            if {t['id'] for t in thoughts} != set(manifest['thought_ids']) or any(t['origin_event'] not in manifest['event_ids'] for t in thoughts):
                return False
            memories = self.memory.rows('SELECT lm.*,e.day source_day,e.verified FROM LifeMemories lm JOIN Events e '
                                        'ON e.id=lm.source_event AND e.world=lm.world WHERE lm.id IN (' + ','.join('?' for _ in manifest['memory_ids']) + ')',
                                        manifest['memory_ids']) if manifest['memory_ids'] else []
            if {m['id'] for m in memories} != set(manifest['memory_ids']) or any(not m['verified'] or m['source_day'] >= entry['day'] for m in memories):
                return False
            evidence_ids = set(manifest['event_ids']) | {t['origin_event'] for t in thoughts} | {m['source_event'] for m in memories}
            if set(json.loads(entry['evidence_ids'])) != evidence_ids:
                return False
            return self._render(events, thoughts, memories, manifest['style'], entry['day'], entry['kind']) == entry['text']
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return False

    def write(self, world, day, kind='daily', event_id=None):
        source = str(day) if kind == 'daily' else event_id
        found = self.memory.rows('SELECT * FROM JournalEntries WHERE world=? AND kind=? AND source_key=?',
                                 (world, kind, source))
        if found:
            self.export_entry(found[0])
            return found[0]
        events = self.memory.rows("SELECT * FROM Events WHERE world=? AND day=? AND verified=1 AND type NOT IN ('construction_step','shelter_inspected') "
                                  + ('AND id=? ' if event_id else '') + 'ORDER BY timestamp,id',
                                  (world, day, event_id) if event_id else (world, day))
        if not events:
            return None
        manifest = self._manifest(world, day, kind, events)
        thoughts = self._thoughts(world, day, manifest['event_ids'])
        memories = self.memory.rows('SELECT lm.*,e.day source_day,e.verified FROM LifeMemories lm JOIN Events e '
                                    'ON e.id=lm.source_event AND e.world=lm.world WHERE lm.id IN (' + ','.join('?' for _ in manifest['memory_ids']) + ')',
                                    manifest['memory_ids']) if manifest['memory_ids'] else []
        text = self._render(events, thoughts, memories, manifest['style'], day, kind)
        ids = list(dict.fromkeys(manifest['event_ids'] + [m['source_event'] for m in memories]))
        manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        entry = dict(id=str(uuid4()), world=world, day=day, kind=kind, source_key=source,
                     text=text, evidence_ids=json.dumps(ids), timestamp=now())
        self.memory.db.execute('INSERT INTO JournalEntries VALUES(:id,:world,:day,:kind,:source_key,:text,:evidence_ids,:timestamp)', entry)
        self.memory.db.execute('INSERT INTO JournalProvenance VALUES(?,3,?,?,?)',
                               (entry['id'], manifest_json, _hash(manifest_json), _hash(text)))
        if kind == 'daily':
            self.memory.db.execute('INSERT OR IGNORE INTO PublicationQueue(world,entry) VALUES(?,?)', (world, entry['id']))
        self.memory.db.commit()
        self.export_entry(entry)
        return entry

    def finalize_before(self, world, day):
        for row in self.memory.rows("SELECT DISTINCT day FROM Events e WHERE world=? AND day<? AND NOT EXISTS "
                                    "(SELECT 1 FROM JournalEntries j WHERE j.world=e.world AND j.day=e.day AND j.kind='daily') ORDER BY day",
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
        readme = directory / 'README.md'
        if not readme.exists():
            self.immutable_write(readme, README)
        filename = (f"day_{entry['day']:03d}.md" if entry['kind'] == 'daily' else
                    f"reflections/day_{entry['day']:03d}_{entry['id']}.md")
        evidence = ', '.join(json.loads(entry['evidence_ids']))
        verified_evidence = all(self.memory.rows('SELECT 1 FROM Events WHERE id=? AND world=? AND verified=1', (eid, entry['world'])) for eid in json.loads(entry['evidence_ids']))
        if not verified_evidence:
            raise ValueError('Diário com proveniência ausente; exportação recusada')
        content = (f"# Dia {entry['day']} — {'Diário' if entry['kind'] == 'daily' else 'Reflexão'}\n\n"
                   f"{entry['text']}\n\nEvidências: {evidence}\n\nRegistro: {entry['id']}\n")
        self.immutable_write(directory / filename, content)

    def export_all(self, world):
        for entry in self.memory.rows('SELECT * FROM JournalEntries WHERE world=?', (world,)):
            if not self.validate_entry(entry):
                raise ValueError('Entrada histórica sem validação; exportação interrompida')
            self.export_entry(entry)
        return self.directory(world)
