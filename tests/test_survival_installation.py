"""Temporary file/metadata validation only; never starts Minecraft or installs mods."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
import zipfile

from scripts import prepare_survival_validation as survival


class SurvivalInstallationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.instance = self.root/'data/validation/phase04'
        self.instance.mkdir(parents=True)

    def jar(self, path, metadata, nested=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('fabric.mod.json', json.dumps(metadata))
            if nested:
                memory = io.BytesIO()
                with zipfile.ZipFile(memory, 'w') as inner:
                    inner.writestr('fabric.mod.json', json.dumps(nested))
                archive.writestr('META-INF/jars/module.jar', memory.getvalue())
        return path

    def test_preparation_creates_only_empty_dirs_and_local_report(self):
        report = survival.prepare(self.instance, dict(runtime=[], gameplay_tested=False), self.root)
        self.assertEqual(report['status'], 'prepared_without_installation')
        self.assertEqual(sorted(p.name for p in self.instance.iterdir()), ['config', 'mods', 'preparation-report.json'])
        self.assertFalse(list((self.instance/'mods').iterdir()))
        self.assertFalse(list((self.instance/'config').iterdir()))
        self.assertFalse((self.instance/'saves').exists())

    def test_preparation_preserves_existing_configuration(self):
        (self.instance/'config').mkdir()
        config = self.instance/'config/user.json'
        config.write_text('preserved')
        with self.assertRaises(ValueError):
            survival.prepare(self.instance, {}, self.root)
        self.assertEqual(config.read_text(), 'preserved')

    def test_main_outside_and_validation_root_are_refused(self):
        for path in [self.root/'.minecraft', self.root/'data/validation', self.instance/'../../../outside']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                survival.isolated_path(path, self.root)

    def test_link_inside_instance_is_refused(self):
        target = self.root/'outside'
        target.mkdir()
        try:
            (self.instance/'mods').symlink_to(target, target_is_directory=True)
        except OSError:
            if os.name != 'nt':
                self.skipTest('Symlink privilege unavailable')
            # Windows junction creation requires no symlink privilege.
            env = os.environ | dict(phase04TestLink=str(self.instance/'mods'), phase04TestTarget=str(target))
            subprocess.run(['powershell.exe','-NoProfile','-Command',
                            'New-Item -ItemType Junction -Path $env:phase04TestLink -Target $env:phase04TestTarget -ErrorAction Stop | Out-Null'],
                           env=env, check=True, capture_output=True)
        with self.assertRaises(ValueError):
            survival.isolated_path(self.instance, self.root)

    def test_size_hash_and_unsafe_filename_fail_closed(self):
        path = self.root/'official.jar'
        path.write_bytes(b'fixture')
        pin = dict(filename=path.name, size=7, sha512=hashlib.sha512(b'fixture').hexdigest())
        survival.verify_artifact(path, pin)
        for changes in [dict(size=8), dict(sha512='0'*128), dict(filename='../official.jar'), dict(filename='official.jar:stream')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                survival.verify_artifact(path, pin | changes)

    def test_alias_nested_dependencies_and_version_ranges(self):
        target = dict(minecraft='1.21.1', java=21, fabric_loader='0.20.1')
        modules = [dict(id='cloth-config', version='15.0.140', provides=['cloth-config2']),
                   dict(id='environmentz', version='2.2.0', depends={'cloth-config2': '>=15.0.140', 'minecraft': '>=1.21- <1.21.2-'})]
        self.assertEqual(survival.check_compatibility(modules, target)['cloth-config2'], '15.0.140')
        for required in ['>=1.21.2', '>=1.22', '~1.21.1']:
            bad = [dict(id='test', version='1', depends={'minecraft': required})]
            with self.subTest(required=required), self.assertRaises(ValueError):
                survival.check_compatibility(bad, target)
        self.assertTrue(survival.satisfies('1.21.1', ['1.20', '>=1.21']))

    def test_conflicts_missing_dependencies_and_duplicate_aliases_refused(self):
        target = dict(minecraft='1.21.1', java=21, fabric_loader='0.20.1')
        for modules in [
            [dict(id='test',version='1',depends={'absent': '*'})],
            [dict(id='test',version='1',conflicts={'minecraft': '*'})],
            [dict(id='test',version='1',provides=['minecraft'])],
        ]:
            with self.subTest(modules=modules), self.assertRaises(ValueError):
                survival.check_compatibility(modules, target)

    def install_fixture(self):
        survival.prepare(self.instance, {}, self.root)
        save = self.instance/'saves'/survival.WORLD
        save.mkdir(parents=True)
        (save/'level.dat').write_bytes(b'synthetic fixture; not a Minecraft world')
        self.jar(self.root/'mod/build/libs/minelife-ai-0.2.0.jar', dict(id='minelife_ai',version='0.2.0',depends={'minecraft': '1.21.1'}))
        (self.root/'config').mkdir()
        (self.root/'config/local.json').write_text(json.dumps(dict(token='synthetic-fixture-'*3, port=8765)))
        return dict(runtime=[], modules={'minecraft': '1.21.1'})

    def test_install_requires_existing_new_world_and_build(self):
        with self.assertRaises(ValueError):
            survival.validate_install(self.instance, dict(runtime=[]), self.root)
        report = self.install_fixture()
        plan = survival.validate_install(self.instance, report, self.root)
        self.assertEqual(plan['world'], survival.WORLD)
        with self.assertRaises(ValueError):
            survival.validate_install(self.instance, report, self.root, world='ia')

    def test_unknown_source_or_duplicate_minelife_jars_are_refused(self):
        report = self.install_fixture()
        unknown = self.jar(self.instance/'mods/unknown-sources.jar', dict(id='unknown', version='1'))
        with self.assertRaises(ValueError):
            survival.validate_install(self.instance, report, self.root)
        unknown.unlink()
        for name in ['minelife-ai-old.jar','minelife-ai-other.jar']:
            self.jar(self.instance/'mods'/name, dict(id='minelife_ai', version='0.1'))
        with self.assertRaises(ValueError):
            survival.validate_install(self.instance, report, self.root)

    def test_missing_authentication_is_not_created(self):
        report = self.install_fixture()
        config = self.root/'config/local.json'
        config.unlink()
        with self.assertRaises(FileNotFoundError):
            survival.validate_install(self.instance, report, self.root)
        self.assertFalse(config.exists())

    def test_recursive_jar_metadata_includes_bundled_module(self):
        path = self.jar(self.root/'nested.jar', dict(id='fabric-api', version='1',jars=[{'file':'META-INF/jars/module.jar'}]),
                        dict(id='fabric-rendering-v1',version='5.2.1'))
        with zipfile.ZipFile(path) as archive:
            self.assertEqual([m['id'] for m in survival.metadata_tree(archive)], ['fabric-api','fabric-rendering-v1'])

    def test_lock_checks_runtime_metadata_sources_and_hashes_offline(self):
        cache = self.root/'cache'
        pins = []
        for index in range(7):
            source = index >= 5
            mod_id = 'mod'+str(index if not source else index-5)
            filename = mod_id+('-sources' if source else '')+'.jar'
            metadata = dict(id=mod_id,version='1.0.0',depends={},provides=[])
            path = self.jar(cache/filename, metadata)
            pin = dict(project_id=mod_id,version_id='version-'+mod_id,version_number='1.0.0',filename=filename,
                       url='https://cdn.modrinth.com/data/'+mod_id+'/versions/version-'+mod_id+'/'+filename,
                       size=path.stat().st_size,sha512=survival.file_digest(path))
            if source:
                pin |= dict(artifact_kind='sources',for_version_id='version-'+mod_id)
            else:
                pin |= dict(mod_id=mod_id,depends={},provides=[],environment='client_and_server')
            pins.append(pin)
        lock = dict(schema_version=1,target=dict(minecraft='1.21.1',loader='fabric',fabric_loader='0.20.1',java=21),artifacts=pins)
        lock_path = self.root/'lock.json'
        lock_path.write_text(json.dumps(lock))
        report = survival.validate_cache(lock_path,cache)
        self.assertEqual(len(report['runtime']),5)
        self.assertEqual(len(report['sources']),2)
        pins[0]['depends'] = {'absent': '*'}
        lock_path.write_text(json.dumps(lock))
        with self.assertRaisesRegex(ValueError, 'metadata differs'):
            survival.validate_cache(lock_path,cache)


if __name__ == '__main__':
    unittest.main()
