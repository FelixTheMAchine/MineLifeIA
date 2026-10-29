from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    name: str
    actions: tuple
    preconditions: str
    success: str
    max_attempts: int = 2
    timeout_seconds: int = 20


class SkillRegistry:
    """Só habilidades com executor físico real; capacidades são negociadas com o mod."""
    skills = {
        'craft_planks': Skill('craft_planks', ('craft',), 'receita vanilla 2x2 desbloqueada de tábuas, gravetos ou bancada; grade vazia e materiais',
                             'estatística CRAFTED e inventário confirmam resultado e ingredientes consumidos'),
        'investigate_log': Skill('investigate_log', ('approach', 'break', 'collect'),
                                'tronco natural desconhecido, dia, saúde e chão seguros',
                                'MINED aumentou, bloco virou ar e inventário aumentou'),
        'observe_block': Skill('observe_block', ('approach', 'observe'),
                              'bloco observado e caminho local viável',
                              'bloco confirmado pelo servidor; não implica coleta/utilidade'),
        'explore_region': Skill('explore_region', ('explore',),
                               'fronteira carregada, caminho validado, região não visitada',
                               'posição final confirmada pelo servidor dentro da região alvo'),
    }

    def available(self, name, capabilities):
        return name in self.skills and set(self.skills[name].actions) <= set(capabilities)

    def record(self, memory, world, name, success):
        memory.db.execute('INSERT OR IGNORE INTO SkillProgress(world,name) VALUES(?,?)', (world, name))
        field = 'successes' if success else 'failures'
        memory.db.execute(f'UPDATE SkillProgress SET {field}={field}+1 WHERE world=? AND name=?', (world, name))
