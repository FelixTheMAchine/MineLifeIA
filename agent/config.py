from pathlib import Path
import json
import secrets

ROOT = Path(__file__).resolve().parents[1]


def load_config(root=ROOT):
    path = root / 'config' / 'local.json'
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        config = {'token': secrets.token_urlsafe(32), 'port': 8765,
                  'auto_publish': False, 'journal_publish_approved': False,
                  'journal_allow_public': False, 'github_repository': 'FelixTheMAchine/MineLifeIA'}
        with path.open('x', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if len(config['token']) < 32 or config['port'] != 8765:
        raise ValueError('Token inválido ou porta diferente da porta local suportada (8765).')
    return config
