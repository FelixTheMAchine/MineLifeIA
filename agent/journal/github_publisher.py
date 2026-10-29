"""Publicação explícita de entradas concluídas; nenhuma tarefa automática por padrão."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from agent.config import ROOT, load_config
from agent.memory import MemoryManager
from agent.journal.writer import JournalWriter, valid_narrative

REPOSITORY = 'FelixTheMAchine/MineLifeIA'
REMOTE = 'https://github.com/' + REPOSITORY + '.git'
SAFE_PATH = re.compile(r'^journals/[a-f0-9]{64}/(?:README\.md|day_\d+\.md|reflections/day_\d+_[a-f0-9-]+\.md)$')
SENSITIVE = re.compile(
    r'(?i)(?:[a-z]:[\\/]|/Users/|/home/|\\\\[a-z0-9]|'
    r'gh[pousr]_[A-Za-z0-9_]{10,}|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,}|'
    r'-----BEGIN .*PRIVATE KEY|bearer\s+[A-Za-z0-9_.-]{12,}|'
    r'(?:api[_ -]?key|password|access[_ -]?token)\s*[:=]\s*\S+)')


def validate_content(path, text):
    if not SAFE_PATH.fullmatch(path) or '..' in Path(path).parts:
        raise ValueError('Caminho não permitido para diário')
    if SENSITIVE.search(text) or '\x00' in text or len(text.encode('utf-8')) > 200000:
        raise ValueError('Conteúdo potencialmente sensível ou tamanho inválido')


class GitHubPublisher:
    def __init__(self, memory, root=ROOT):
        self.m = memory
        self.root = Path(root)
        self.writer = JournalWriter(memory, self.root / 'journals')

    def prepare(self):
        entries = self.m.rows("SELECT j.* FROM JournalEntries j JOIN PublicationQueue q ON q.entry=j.id "
                              "WHERE q.status='pending' AND j.kind='daily' ORDER BY j.world,j.day,j.timestamp")
        files = {}
        for daily in entries:
            # Valida referências contra fatos locais; um texto arbitrário no disco não é publicado.
            sources = self.m.rows('SELECT * FROM JournalEntries WHERE world=? AND day=? ORDER BY timestamp',
                                  (daily['world'], daily['day']))
            for entry in sources:
                if not self.writer.validate_entry(entry):
                    raise ValueError('Narrativa ou proveniência não confere com registros verificados')
                self.writer.export_entry(entry)
                folder = self.writer.directory(entry['world'])
                paths = [folder / 'README.md', folder / (f"day_{entry['day']:03d}.md" if entry['kind'] == 'daily' else
                         f"reflections/day_{entry['day']:03d}_{entry['id']}.md")]
                for path in paths:
                    if path.is_symlink():
                        raise ValueError('Links não são permitidos no diário')
                    relative = path.relative_to(self.root).as_posix()
                    text = path.read_text(encoding='utf-8')
                    validate_content(relative, text)
                    files[relative] = text
        return entries, files

    @staticmethod
    def run(args, cwd):
        env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True,
                                encoding='utf-8', timeout=60)
        if result.returncode:
            # Não persista stderr: pode conter credenciais, nomes ou caminhos locais.
            raise RuntimeError('Git/GitHub indisponível, sem autenticação ou operação recusada; fila preservada.')
        return result.stdout.strip()

    def publish(self, approved=False, allow_public=False):
        entries, files = self.prepare()
        report = {'mode': 'dry-run', 'entries': len(entries),
                  'files': {p: hashlib.sha256(t.encode('utf-8')).hexdigest() for p, t in files.items()},
                  'repository': REPOSITORY, 'auto_publish': False}
        if not approved or not entries:
            return report
        try:
            if not shutil.which('gh'):
                raise RuntimeError('GitHub CLI ausente; fila preservada.')
            repo = json.loads(self.run(['gh', 'api', 'repos/' + REPOSITORY], self.root))
            if repo.get('full_name') != REPOSITORY or (not repo.get('private') and not allow_public):
                raise ValueError('Repositório oficial/visibilidade autorizada não confirmado')
            origin = self.run(['git', 'remote', 'get-url', 'origin'], self.root)
            if origin != REMOTE:
                raise ValueError('Remote origin não é o repositório oficial')
            work_parent = self.root / 'data' / 'publish-work'
            work_parent.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix='journal-', dir=work_parent))
            git = ['git', '-c', 'core.hooksPath=NUL']
            self.run(git + ['clone', '--single-branch', '--branch', 'main', REMOTE, str(work)], self.root)
            self.run(git + ['config', 'user.name', 'MineLife AI Journal'], work)
            self.run(git + ['config', 'user.email', '149002962+FelixTheMAchine@users.noreply.github.com'], work)
            changed = []
            for relative, content in files.items():
                dest = work / relative
                if any(p.is_symlink() for p in [dest, *dest.parents] if p != work.parent):
                    raise ValueError('Destino com link simbólico')
                if dest.exists():
                    if dest.read_text(encoding='utf-8') != content:
                        raise ValueError('Entrada remota diverge; sobrescrita recusada')
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open('x', encoding='utf-8', newline='\n') as f:
                    f.write(content)
                changed.append(relative)
            if changed:
                self.run(git + ['add', '-f', '--', *changed], work)
                staged = self.run(git + ['diff', '--cached', '--name-only'], work).splitlines()
                if set(staged) != set(changed) or any(not SAFE_PATH.fullmatch(p) for p in staged):
                    raise ValueError('Área de staging contém arquivos inesperados')
                self.run(git + ['commit', '-m', f"journal: {len(entries)} dia(s) concluído(s), com evidências"], work)
                # Sem force. Uma atualização concorrente interrompe e preserva a fila.
                self.run(git + ['push', 'origin', 'HEAD:main'], work)
            for entry in entries:
                self.m.db.execute("UPDATE PublicationQueue SET status='published',error=NULL WHERE entry=?", (entry['id'],))
            self.m.db.commit()
            report['mode'] = 'published'
            return report
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            self.m.db.execute("UPDATE PublicationQueue SET error='Publicação pendente; verificar conectividade, autenticação e validação.' WHERE status='pending'")
            self.m.db.commit()
            raise RuntimeError('Publicação não concluída. Fila local preservada.') from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish', action='store_true', help='Envio manual explicitamente autorizado')
    args = parser.parse_args()
    config = load_config()
    if args.publish and not config.get('journal_publish_approved', False):
        parser.error('Primeiro valide dry-run e autorize journal_publish_approved em config/local.json.')
    memory = MemoryManager(ROOT / 'data' / 'memory.sqlite3')
    try:
        print(json.dumps(GitHubPublisher(memory).publish(args.publish, config.get('journal_allow_public', False)), ensure_ascii=False, indent=2))
    finally:
        memory.close()


if __name__ == '__main__':
    main()
