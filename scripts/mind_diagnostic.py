"""Read-only local prerequisites report. Never imports backend startup or migrations."""
import argparse
import asyncio
from contextlib import closing
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile

import httpx

from agent.local_model import LocalModelProvider

ROOT = Path(__file__).resolve().parents[1]


def run_readonly(command, timeout=4):
    try:
        environment = None
        if command and command[0] == 'ollama':
            environment = {**os.environ, 'OLLAMA_HOST': 'http://127.0.0.1:11434'}
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                check=False, env=environment,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return result.returncode, (result.stdout + result.stderr)[:65536]
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None, ''


def safe_name(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:+-]{1,80}', value) else None


def read_config(root):
    """Read an existing file only; missing configuration stays missing."""
    path = Path(root) / 'config' / 'local.json'
    if not path.exists():
        return {}, 'missing'
    try:
        if path.stat().st_size > 262144:
            return {}, 'invalid'
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return (value, 'present') if isinstance(value, dict) else ({}, 'invalid')
    except (OSError, ValueError):
        return {}, 'invalid'


def config_report(config, status):
    llm = config.get('llm', {})
    llm = llm if isinstance(llm, dict) else {}
    provider = llm.get('provider', 'none')
    return {'status': status, 'llm': {
        'provider': provider if provider in ('none', 'ollama', 'openai_compatible') else 'unknown',
        'model': safe_name(llm.get('model')),
        'enabled': provider == 'ollama',
        **{key: llm[key] for key in ('timeout_seconds', 'num_ctx', 'max_output_tokens', 'num_gpu', 'num_thread')
           if isinstance(llm.get(key), (int, float)) and not isinstance(llm[key], bool)
           and math.isfinite(llm[key])}}}


def memory_report(root):
    path = Path(root) / 'data' / 'memory.sqlite3'
    if not path.is_file():
        return {'status': 'missing', 'exists': False}
    try:
        # mode=ro prohibits migrations/inserts; do not use MemoryManager here.
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            deadline = time.monotonic() + 3
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            db.execute('PRAGMA query_only=ON')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            integrity = db.execute('PRAGMA integrity_check(1)').fetchone()[0] == 'ok'
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts = {name: db.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]
                      for name in ('Worlds', 'Events', 'Observations', 'Knowledge', 'LifeMemories',
                                   'CognitiveSuggestions', 'CognitivePlans', 'NarrativeDrafts') if name in tables}
            return {'status': 'ok' if integrity else 'invalid', 'exists': True,
                    'user_version': version, 'integrity': 'ok' if integrity else 'failed',
                    'table_count': len(tables), 'row_counts': counts}
    except (OSError, sqlite3.Error):
        return {'status': 'unavailable', 'exists': True}


def _metadata(value):
    if not isinstance(value, dict):
        raise ValueError('invalid_metadata')
    depends = value.get('depends', {})
    depends = depends if isinstance(depends, dict) else {}
    return {'id': safe_name(value.get('id')), 'version': safe_name(value.get('version')),
            'depends': {key: str(depends[key])[:64] for key in ('minecraft', 'java', 'fabricloader', 'fabric-api')
                        if key in depends and re.fullmatch(r'[A-Za-z0-9.*+><= -]{1,64}', str(depends[key]))}}


def mod_report(root, minecraft_dir=None):
    workspace = {'status': 'unavailable'}
    try:
        value = json.loads((Path(root) / 'mod/src/main/resources/fabric.mod.json').read_text(encoding='utf-8'))
        metadata = _metadata(value)
        gradle = (Path(root) / 'mod/build.gradle').read_text(encoding='utf-8')
        version = re.search(r"(?m)^version\s*=\s*'([^']+)'", gradle)
        if version:
            metadata['version'] = safe_name(version.group(1))
        workspace = {'status': 'ok', **metadata}
    except (OSError, ValueError, TypeError):
        pass
    installed = []
    if minecraft_dir is None and os.environ.get('APPDATA'):
        minecraft_dir = Path(os.environ['APPDATA']) / '.minecraft'
    if minecraft_dir is not None:
        try:
            for path in sorted((Path(minecraft_dir) / 'mods').glob('minelife-ai*.jar'))[:8]:
                try:
                    with zipfile.ZipFile(path) as archive:
                        info = archive.getinfo('fabric.mod.json')
                        if info.file_size > 65536:
                            raise ValueError()
                        installed.append({'status': 'ok', **_metadata(json.loads(archive.read(info)))})
                except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                    installed.append({'status': 'invalid'})
        except OSError:
            pass
    return {'workspace': workspace, 'installed': {'status': 'present' if installed else 'missing', 'mods': installed}}


def runtime_report():
    code, java = run_readonly(['java', '-version'])
    match = re.search(r'(?:openjdk|java) version "(\d+)(?:\.([^"\s]+))?', java)
    major = int(match.group(1)) if match else None
    return {'python': {'version': '.'.join(map(str, sys.version_info[:3])), 'required': '3.11',
                       'status': 'ok' if sys.version_info[:2] == (3, 11) else 'mismatch'},
            'java': {'major': major, 'required': 21,
                     'status': 'ok' if major == 21 else 'mismatch' if major else 'unavailable'}}


def minecraft_process_status():
    """Inspect Java command lines, without printing them or mistaking Gradle for Minecraft."""
    if os.name == 'nt':
        script = ("$p=@(Get-CimInstance Win32_Process -Filter \"Name='java.exe' OR Name='javaw.exe'\" "
                  "-ErrorAction Stop); if($p | Where-Object {$_.CommandLine -match "
                  "'net\\.minecraft\\.client\\.main\\.Main|net\\.fabricmc\\.loader.*KnotClient|--gameDir'}) "
                  "{'running'} elseif($p | Where-Object {-not $_.CommandLine}) {'unknown'} else {'clear'}")
        code, value = run_readonly(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script])
        return value.strip() if code == 0 and value.strip() in ('running', 'clear', 'unknown') else 'unknown'
    proc = Path('/proc')
    if not proc.is_dir():
        return 'unknown'
    try:
        for item in proc.iterdir():
            if not item.name.isdigit():
                continue
            try:
                executable = (item / 'comm').read_text().strip()
                if executable not in ('java', 'javaw'):
                    continue
                command = (item / 'cmdline').read_bytes().replace(b'\x00', b' ').decode(errors='replace')
                if re.search(r'net\.minecraft\.client\.main\.Main|net\.fabricmc\.loader.*KnotClient|--gameDir', command):
                    return 'running'
            except FileNotFoundError:
                continue
            except OSError:
                return 'unknown'
        return 'clear'
    except OSError:
        return 'unknown'


async def bridge_report(transport=None):
    try:
        async with asyncio.timeout(3):
            async with httpx.AsyncClient(timeout=2, trust_env=False, follow_redirects=False,
                                         transport=transport) as client:
                async with client.stream('GET', 'http://127.0.0.1:8765/health') as response:
                    if response.status_code != 200:
                        return {'status': 'unavailable'}
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > 16384:
                            return {'status': 'invalid'}
                        body.extend(chunk)
                    data = json.loads(body)
        if not isinstance(data, dict):
            return {'status': 'invalid'}
        features = data.get('features', [])
        return {'status': 'ok' if data.get('protocol') == 1 else 'mismatch',
                'protocol': data.get('protocol') if isinstance(data.get('protocol'), int) else None,
                'version': safe_name(data.get('version')),
                'features': [safe_name(v) for v in features if safe_name(v)] if isinstance(features, list) else []}
    except (httpx.HTTPError, OSError, ValueError, TimeoutError):
        return {'status': 'unavailable'}


def ollama_cli_report():
    if not shutil.which('ollama'):
        return {'status': 'unavailable'}
    version_code, version = run_readonly(['ollama', '--version'])
    list_code, listing = run_readonly(['ollama', 'list'])
    match = re.search(r'\b\d+\.\d+\.\d+\b', version)
    return {'status': 'ok' if version_code == 0 else 'unavailable',
            'version': match.group(0) if match else None,
            'list_status': 'ok' if list_code == 0 else 'unavailable',
            'listed_models': max(0, len(listing.strip().splitlines()) - 1) if list_code == 0 else None}


async def diagnostic(root=ROOT, minecraft_dir=None, transport=None):
    config, status = read_config(root)
    llm = config.get('llm') if isinstance(config.get('llm'), dict) else {}
    provider = LocalModelProvider({**llm, 'provider': 'ollama', 'timeout_seconds': 3}, transport)
    health = await provider.health_check()
    # Whitelist public fields; never expose configuration, paths, prompts or tokens.
    ollama = {'status': health['status'], 'error': health['error'],
              'available': health['available'], 'model': safe_name(health['model']),
              'version': safe_name(health['version']),
              'available_models': [safe_name(v) for v in health['available_models'] if safe_name(v)],
              'loaded_models': [safe_name(v) for v in health['loaded_models'] if safe_name(v)],
              'capabilities': health['capabilities']}
    return {'read_only': True, 'runtime': runtime_report(), 'configuration': config_report(config, status),
            'memory': memory_report(root), 'mod': mod_report(root, minecraft_dir),
            'bridge': await bridge_report(transport), 'ollama': ollama, 'ollama_cli': ollama_cli_report(),
            'minecraft_process': minecraft_process_status()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(json.dumps(asyncio.run(diagnostic()), ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == '__main__':
    main()
