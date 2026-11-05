"""Offline, fail-closed preparation for an isolated Survival validation instance.

This module never installs jars, opens Minecraft, or creates/changes a save.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlparse
import zipfile


ROOT = Path(__file__).resolve().parents[1]
WORLD = 'phase04-validation'


def reject_links(path):
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('Symlink/reparse path refused: ' + str(part))
    return path


def isolated_path(path, project_root=ROOT):
    path = reject_links(path)
    allowed = reject_links(Path(project_root) / 'data' / 'validation')
    if path == allowed or not path.is_relative_to(allowed):
        raise ValueError('Instance must be strictly inside data/validation')
    if path.exists():
        for base, directories, files in os.walk(path, followlinks=False):
            for name in directories + files:
                reject_links(Path(base)/name)
    return path


def file_digest(path):
    reject_links(path)
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha512').hexdigest()


def verify_artifact(path, pin):
    if not re.fullmatch(r'[A-Za-z0-9._+\-]+\.jar', pin['filename']):
        raise ValueError('Unsafe artifact filename')
    path = reject_links(path)
    if not path.is_file() or path.stat().st_size != pin['size'] or file_digest(path) != pin['sha512']:
        raise ValueError('Artifact size/hash mismatch: ' + pin['filename'])


def version_key(value):
    match = re.fullmatch(r'(\d+(?:\.\d+)*)(?:-([^+]*))?(?:\+.*)?', value)
    if not match:
        raise ValueError('Unsupported version: ' + value)
    core = tuple(int(n) for n in match[1].split('.'))
    core += (0,) * max(0, 3-len(core))
    pre = tuple((0, int(p)) if p.isdigit() else (1, p) for p in (match[2] or '').split('.') if p)
    return core, (1, ()) if match[2] is None else (0, pre)


def satisfies(version, requirement):
    if isinstance(requirement, list):
        return any(satisfies(version, alternative) for alternative in requirement)
    if requirement == '*':
        return True
    for term in requirement.split():
        match = re.fullmatch(r'(>=|<=|>|<|=)?(.+)', term)
        op, expected = match[1] or '=', match[2]
        actual, bound = version_key(version), version_key(expected)
        if not {'>=': actual >= bound, '<=': actual <= bound, '>': actual > bound,
                '<': actual < bound, '=': actual == bound}[op]:
            return False
    if not requirement.strip():
        raise ValueError('Empty version requirement')
    return True


def jar_metadata(path):
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read('fabric.mod.json'))


def metadata_tree(archive):
    metadata = json.loads(archive.read('fabric.mod.json'))
    yield metadata
    for entry in metadata.get('jars', []):
        with zipfile.ZipFile(io.BytesIO(archive.read(entry['file']))) as nested:
            yield from metadata_tree(nested)


def check_compatibility(modules, target):
    available = {'minecraft': target['minecraft'], 'java': str(target['java']), 'fabricloader': target['fabric_loader']}
    for module in modules:
        for name in [module['id'], *module.get('provides', [])]:
            if name in available:
                raise ValueError('Duplicate mod/alias: ' + name)
            available[name] = module['version']
    for module in modules:
        for name, requirement in module.get('depends', {}).items():
            if name not in available or not satisfies(available[name], requirement):
                raise ValueError('Unsatisfied dependency: ' + module['id'] + ' -> ' + name)
        for name, requirement in (module.get('breaks', {}) | module.get('conflicts', {})).items():
            if name in available and satisfies(available[name], requirement):
                raise ValueError('Conflicting mod: ' + name)
    return available


def validate_cache(lock_path=ROOT/'docs/survival-mods.lock.json', cache=ROOT/'data/phase04-research'):
    reject_links(lock_path)
    lock = json.loads(Path(lock_path).read_text(encoding='utf-8'))
    target = lock['target']
    if lock['schema_version'] != 1 or target != dict(minecraft='1.21.1', loader='fabric', fabric_loader='0.20.1', java=21):
        raise ValueError('Unexpected runtime target')
    pins = lock['artifacts']
    runtime = [p for p in pins if p.get('artifact_kind') != 'sources']
    sources = [p for p in pins if p.get('artifact_kind') == 'sources']
    if len(runtime) != 5 or len(sources) != 2 or len({p['filename'] for p in pins}) != len(pins):
        raise ValueError('Expected five runtime jars and two source jars')
    modules = []
    for pin in pins:
        url = urlparse(pin['url'])
        expected = '/data/' + pin['project_id'] + '/versions/' + pin['version_id'] + '/' + pin['filename']
        if url.scheme != 'https' or url.netloc != 'cdn.modrinth.com' or unquote(url.path) != expected or url.query or url.fragment:
            raise ValueError('Artifact is not pinned to its official CDN path')
        path = Path(cache)/pin['filename']
        verify_artifact(path, pin)
        metadata = jar_metadata(path)
        if pin.get('artifact_kind') == 'sources':
            parent = next((p for p in runtime if p['version_id'] == pin['for_version_id']), None)
            if (not parent or metadata['id'] != parent['mod_id']
                    or set(metadata.get('depends', {})) != set(parent['depends'])
                    or metadata.get('provides', []) != parent['provides']):
                raise ValueError('Source artifact does not match runtime')
            continue
        if (metadata['id'] != pin['mod_id'] or metadata.get('depends', {}) != pin['depends']
                or metadata.get('provides', []) != pin['provides']
                or metadata['version'] not in (pin['version_number'], pin['version_number'].split('+')[0])):
            raise ValueError('Runtime metadata differs from lock: ' + pin['filename'])
        env = {'client_and_server': '*', 'client_only': 'client', 'client_or_server_prefers_both': '*'}.get(pin['environment'])
        if metadata.get('environment', '*') != env:
            raise ValueError('Runtime environment differs from lock')
        with zipfile.ZipFile(path) as archive:
            modules.extend(metadata_tree(archive))
    available = check_compatibility(modules, target)
    return dict(status='verified_offline', target=target, runtime=runtime, sources=sources,
                modules=available, cache=str(Path(cache).absolute()), gameplay_tested=False)


def validate_install(instance, report, project_root=ROOT, world=WORLD):
    instance = isolated_path(instance, project_root)
    if world != WORLD or not (instance/'saves'/world/'level.dat').is_file():
        raise ValueError('A new user-created phase04-validation world is required; ia is refused')
    expected = {p['filename']: p for p in report['runtime']}
    mods = instance/'mods'
    if not mods.is_dir() or not (instance/'config').is_dir():
        raise ValueError('Prepare isolated config/mods directories first')
    minelife = []
    for path in mods.iterdir():
        if not path.is_file() or path.suffix.lower() != '.jar':
            raise ValueError('Unknown entry in isolated mods directory: ' + path.name)
        if path.name in expected:
            verify_artifact(path, expected[path.name])
        elif path.name.startswith('minelife-ai') and jar_metadata(path).get('id') == 'minelife_ai':
            minelife.append(path)
        else:
            raise ValueError('Unknown/conflicting jar: ' + path.name)
    if len(minelife) > 1:
        raise ValueError('Multiple MineLife jars refused')
    jar = Path(project_root)/'mod/build/libs/minelife-ai-0.2.0.jar'
    reject_links(jar)
    metadata = jar_metadata(jar)
    if metadata.get('id') != 'minelife_ai' or metadata.get('version') != '0.2.0':
        raise ValueError('Unexpected MineLife build')
    for name, requirement in metadata.get('depends', {}).items():
        if name not in report['modules'] or not satisfies(report['modules'][name], requirement):
            raise ValueError('MineLife dependency is incompatible: ' + name)
    config = reject_links(Path(project_root)/'config/local.json')
    backend = json.loads(config.read_text(encoding='utf-8-sig'))
    if not isinstance(backend.get('token'), str) or len(backend['token']) < 32 or backend.get('port') != 8765:
        raise ValueError('Existing backend configuration required; installer must not generate authentication')
    return dict(instance=str(instance), world=world, jar=str(jar), jar_sha512=file_digest(jar))


def prepare(instance, report, project_root=ROOT):
    instance = isolated_path(instance, project_root)
    for name in ('config', 'mods'):
        directory = instance/name
        if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
            raise ValueError('Preparation requires empty config/mods directories')
    for name in ('config', 'mods'):
        (instance/name).mkdir(parents=True, exist_ok=True)
    report = report | dict(status='prepared_without_installation', instance=str(instance), world_required=WORLD)
    (instance/'preparation-report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', type=Path, default=ROOT/'data/validation/phase04')
    parser.add_argument('--validate-install', action='store_true')
    args = parser.parse_args()
    report = validate_cache()
    if args.validate_install:
        report['installation'] = validate_install(args.instance, report)
    else:
        report = prepare(args.instance, report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
