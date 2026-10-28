"""Audita exatamente os blobs do index Git, sem imprimir possíveis segredos."""
import re
import subprocess
import sys

FORBIDDEN_PARTS = {'.venv', '.tools', '.gradle', '__pycache__', 'build', 'data', 'saves',
                   'backups', '.minecraft', 'logs', 'secrets', 'node_modules'}
FORBIDDEN_SUFFIXES = ('.sqlite', '.sqlite3', '.db', '.log', '.pem', '.key', '.pfx', '.p12', '.mca', '.mcr')
SECRET = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
LOCAL_PATH = re.compile(rb'(?i)(?:[a-z]:[\\/]Users[\\/][A-Za-z0-9_. -]+|/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/)')


def git(*args):
    return subprocess.check_output(['git', *args])


def main():
    paths = git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z').decode('utf-8').split('\0')
    paths = [p for p in paths if p]
    failures = []
    for path in paths:
        parts = set(path.lower().split('/'))
        name = path.split('/')[-1].lower()
        if parts & FORBIDDEN_PARTS or name.startswith('.env') or name.endswith(FORBIDDEN_SUFFIXES) or path == 'config/local.json':
            failures.append((path, 'arquivo privado/gerado'))
            continue
        # Diários exigem validação do publicador, e não entram em commits de código.
        if path.startswith('journals/'):
            failures.append((path, 'use o publicador de diarios'))
            continue
        data = git('show', ':' + path)
        mode = git('ls-files', '--stage', '--', path).split(b' ', 1)[0]
        if mode == b'120000':
            failures.append((path, 'link simbolico'))
        if path.endswith('.jar'):
            if path != 'mod/gradle/wrapper/gradle-wrapper.jar':
                failures.append((path, 'binario nao permitido'))
            continue
        if SECRET.search(data) or LOCAL_PATH.search(data):
            failures.append((path, 'possivel segredo/caminho pessoal'))
    if failures:
        for path, reason in failures:
            print(f'RECUSADO: {path}: {reason}')
        return 1
    print(f'Auditoria aprovada: {len(paths)} arquivos; nenhum segredo conhecido, save ou banco no index.')
    print('\n'.join(paths))
    return 0


if __name__ == '__main__':
    sys.exit(main())
