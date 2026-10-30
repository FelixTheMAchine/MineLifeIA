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
        'build_shelter': Skill('build_shelter',('build_shelter',),'projeto persistente, dia, materiais reservados, célula vazia e apoio alcançável',
                               'bloco de uma etapa, consumo e USED confirmados pelo servidor; não confirma o abrigo inteiro'),
        'inspect_shelter': Skill('inspect_shelter',('inspect_shelter',),'projeto conhecido no alcance local e chunks carregados',
                                 'todos os componentes, piso, interior e porta inspecionados no servidor'),
        'enter_shelter': Skill('enter_shelter',('enter_shelter',),'abrigo completo próximo, caminho seguro e sem ameaça imediata',
                               'posição interna, estrutura completa e porta fechada confirmadas'),
        'leave_shelter': Skill('leave_shelter',('leave_shelter',),'local de projeto com piso, passagem aberta ou porta válida e saída local viável',
                               'posição externa e fechamento da porta existente confirmados; obra parcial continua parcial'),
        'place_workstation': Skill('place_workstation', ('place',), 'estação no inventário, espaço vazio observado, apoio e hotbar disponíveis',
                                   'bloco confirmado pelo servidor, item consumido e estatística USED incrementada'),
        'craft_table': Skill('craft_table', ('craft_table',), 'bancada observada, receita 3x3 desbloqueada, ingredientes e espaço no inventário',
                             'interface nativa da bancada, todos os ingredientes consumidos, resultado e CRAFTED confirmados'),
        'pickup_item': Skill('pickup_item', ('pickup',), 'entidade de item observada, inventário com espaço e rota local segura',
                             'servidor confirma aumento do inventário e redução/remoção da entidade', max_attempts=2, timeout_seconds=18),
        'harvest_crop': Skill('harvest_crop', ('approach', 'harvest'), 'cultivo vanilla maduro observado e dia seguro',
                              'servidor confirma remoção do bloco maduro; drops exigem coleta verificada separadamente'),
        'sleep_in_bed': Skill('sleep_in_bed', ('approach', 'sleep'), 'cama observada no Overworld, noite, sem ameaça próxima e rota local segura',
                              'servidor confirma SLEEP_IN_BED e avanço do horário para o dia'),
        'eat_food': Skill('eat_food', ('eat',), 'fome abaixo da margem prudente e alimento permitido no inventário principal',
                          'Servidor confirma aumento da fome e consumo de exatamente uma unidade', max_attempts=3, timeout_seconds=12),
        'craft_planks': Skill('craft_planks', ('craft',), 'receita vanilla 2x2 permitida e desbloqueada; grade vazia e materiais',
                             'estatística CRAFTED e inventário confirmam resultado e ingredientes consumidos'),
        'investigate_log': Skill('investigate_log', ('approach', 'break', 'collect'),
                                'tronco natural para investigação ou reposição limitada, dia, saúde e chão seguros',
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
