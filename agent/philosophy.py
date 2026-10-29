"""Reflexão narrativa contextual. As interpretações são simuladas e ligadas a eventos verificáveis."""
import json
from uuid import uuid4
from agent.memory import now


class PhilosophicalReflectionEngine:
    # Temas são acionados por experiências e limiares observáveis, nunca por sorteio periódico.
    def __init__(self, memory, autobiography):
        self.m, self.autobiography = memory, autobiography

    def consider(self, world, day, session, event_id):
        rows = self.m.rows('SELECT * FROM Events WHERE id=? AND world=? AND verified=1', (event_id, world))
        if not rows:
            return None
        event = rows[0]
        data = json.loads(event['evidence'])
        theme = None
        subject = str(data.get('subject', ''))
        if event['type'] == 'collected' and subject:
            theme = 'knowledge'
            question = f"O que a coleta verificada de {subject} confirma nesta experiência, e que usos ainda precisam de uma prova própria?"
            interpretation = f"A evidência confirma a coleta de {subject}; ela não demonstra, por si só, todas as suas aplicações."
            importance, novelty = .82, .9
        elif event['type'] == 'crafted' and data.get('recipe'):
            theme = 'creation'
            output = next((k for k in data if k.endswith('_id')), 'um material')
            question = f"Que novas possibilidades posso investigar com o resultado observado da receita {data['recipe']}?"
            interpretation = f"A receita {data['recipe']} foi observada nesta sessão; qualquer uso posterior do resultado ainda depende de outra ação verificada."
            importance, novelty = .78, .85
        elif event['type'] == 'placed' and data.get('after_block'):
            theme = 'changing-a-place'
            question = f"Coloquei {data['after_block']} neste lugar. Como essa alteração observada pode mudar os projetos que consigo tentar aqui?"
            interpretation = 'Confirmei uma estação colocada e um recurso consumido. Isso cria uma possibilidade de uso; fabricar algo ou transformar o local em abrigo ainda exige outras evidências.'
            importance, novelty = .84, .85
        elif event['type'] == 'region_reached':
            theme = 'place'
            position = data.get('position', {})
            question = f"O que mudou na minha compreensão do lugar em torno das coordenadas observadas {position.get('x','?')}, {position.get('y','?')}, {position.get('z','?')}?"
            interpretation = "A posição alcançada e o bioma registrado acrescentam uma observação ao mapa; ainda não bastam para chamar o lugar de familiar ou seguro."
            importance, novelty = .66, .72
        elif event['type'] == 'ate' and type(data.get('food_before')) is int and type(data.get('food_after')) is int:
            theme = 'need-and-choice'
            question = f"Depois de observar a fome subir de {data['food_before']} para {data['food_after']}, como devo equilibrar necessidades imediatas e objetivos de descoberta?"
            interpretation = 'Nesta experiência, uma necessidade corporal observada mudou a prioridade da ação; isso não determina quais objetivos serão importantes em outros momentos.'
            importance, novelty = .72, .68
        elif event['type'] == 'crop_harvested':
            theme = 'need-and-creation'
            question = f"A remoção verificada de {subject or 'um cultivo maduro'} alterou o bloco; que recursos ela realmente oferece, e como isso poderia mudar minhas escolhas?"
            interpretation = 'O servidor confirmou a remoção do cultivo, mas ainda não confirmei quais itens caíram; por enquanto, a utilidade permanece uma pergunta.'
            importance, novelty = .74, .75
        elif event['type'] == 'slept':
            theme = 'safety-and-discovery'
            question = 'Depois de atravessar uma noite usando uma cama confirmada, como a segurança muda o que posso escolher investigar depois?'
            interpretation = 'O servidor confirmou repouso e avanço do horário; isso mostra uma forma concreta de atravessar a noite, mas não prova que todos os lugares ou abrigos sejam seguros.'
            importance, novelty = .84, .76
        elif event['type'] == 'attempt_failed':
            theme = 'failure'
            goal_rows = self.m.rows('SELECT g.status,p.attempts,p.last_error FROM Goals g JOIN GoalPlans p ON p.goal_id=g.id '
                                    'WHERE g.world=? AND p.goal_id=? LIMIT 1', (world, data.get('goal','')))
            attempts = goal_rows[0]['attempts'] if goal_rows else 1
            if attempts < 2:
                return None
            question = f"Qual condição observada na tentativa de {data.get('reason','ação')} consigo mudar antes de voltar a investigar este objetivo?"
            interpretation = "O resultado foi insuficiente para confirmar a hipótese; interromper a repetição preserva a diferença entre uma tentativa e um fato."
            importance, novelty = .72, .65
        else:
            return None

        prior = self.m.rows('SELECT current FROM PhilosophicalRevisions WHERE world=? AND theme=? ORDER BY created DESC LIMIT 1',
                            (world, theme))
        previous = prior[0]['current'] if prior else ''
        existing = self.m.rows('SELECT id FROM PhilosophicalQuestions WHERE world=? AND theme=? AND origin_event=?',
                               (world, theme, event_id))
        if existing:
            return self.m.rows('SELECT * FROM PhilosophicalQuestions WHERE id=?', (existing[0]['id'],))[0]
        qid = str(uuid4())
        source_ids = json.dumps([event_id])
        created = now()
        self.m.db.execute('INSERT INTO PhilosophicalQuestions VALUES(?,?,?,?,?,?,?,?)',
                          (qid, world, theme, question, event_id, interpretation, 'open', created))
        reason = ('Primeira interpretação baseada no acontecimento' if not previous else
                  'Revisão da interpretação após nova evidência do mesmo tema')
        self.m.db.execute('INSERT INTO PhilosophicalRevisions VALUES(?,?,?,?,?,?,?,?,?,?)',
                          (str(uuid4()), world, theme, event_id, previous, interpretation, source_ids, reason,
                           .75 if previous else .6, created))
        self.autobiography.record(world, event_id, theme, importance, novelty,
                                  {'event_type': event['type'], 'day': day, 'subject': subject})
        return self.m.rows('SELECT * FROM PhilosophicalQuestions WHERE id=?', (qid,))[0]
