import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
import sys

spec = importlib.util.spec_from_file_location('repo_audit', Path(__file__).parents[1] / 'repos.py')
repos = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repos)


def item(name, repo='example', **kwargs):
    return NS(name=name, repo_name=repo, **kwargs)


def repo(name='example', cogs=()):
    return NS(name=name, available_cogs=[item(name) for name in cogs])


def report(added=(), installed=(), libraries=(), extensions=None, cogs=None, commands=(), apps=()):
    return repos.build_repo_report(added, installed, libraries, extensions or {}, cogs or {}, commands, apps)


class RepoTests(unittest.TestCase):
    def test_empty_repo_candidate(self):
        text, counts = report([repo()])
        self.assertEqual(counts['candidates'], 1)
        self.assertIn('CLEANUP CANDIDATE', text)

    def test_library_repo_not_candidate(self):
        text, counts = report([repo()], libraries=[item('shared')])
        self.assertEqual(counts['candidates'], 0)
        self.assertIn('shared libraries installed', text)

    def test_unloaded_not_reported_broken(self):
        text, counts = report([repo(cogs=['foo'])], [item('foo')])
        self.assertEqual(counts['unloaded'], 1)
        self.assertIn('UNLOADED (reason unknown)', text)
        self.assertEqual(counts['candidates'], 0)

    def test_missing_repo_preserves_original_name(self):
        text, counts = report(installed=[item('foo', 'MISSING_REPO', _json_repo_name='original')])
        self.assertIn('REPO: original', text)
        self.assertIn('no longer added', text)

    def test_loaded_background_cog(self):
        text, counts = report([repo(cogs=['foo'])], [item('foo')], extensions={'foo': NS(__name__='foo')})
        self.assertEqual(counts['unloaded'], 0)
        self.assertIn('background features', text)

    def test_module_boundary_and_hidden_parent(self):
        cmd = NS(module='foo.commands', cog=None, qualified_name='group child', parents=[NS(hidden=True, enabled=False)])
        unrelated = NS(module='foobar.commands', cog=None, qualified_name='other', parents=[])
        text, counts = report([repo(cogs=['foo'])], [item('foo')], commands=[cmd, unrelated])
        self.assertIn('Registered text commands: 1', text)
        self.assertIn('hidden (self or parent); disabled (self or parent)', text)
        self.assertNotIn('      other', text)

    def test_app_only_cog(self):
        app = NS(module='foo.app', qualified_name='hello', binding=None)
        text, counts = report([repo(cogs=['foo'])], [item('foo')], apps=[app])
        self.assertEqual(counts['unloaded'], 0)
        self.assertIn('/hello [application entry]', text)

    def test_core_extension_kept_separate(self):
        text, counts = report(extensions={'redbot.cogs.admin': NS(__name__='redbot.cogs.admin')})
        self.assertIn('- redbot.cogs.admin', text)
        self.assertEqual(counts['candidates'], 0)


class InventoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_downloader_required(self):
        with self.assertRaisesRegex(RuntimeError, 'Load Downloader'):
            await repos.downloader_inventory(NS(get_cog=lambda name: None))

    async def test_initializing_downloader(self):
        downloader = NS(_ready=NS(is_set=lambda: False))
        with self.assertRaisesRegex(RuntimeError, 'initializing'):
            await repos.downloader_inventory(NS(get_cog=lambda name: downloader))

    async def test_older_downloader(self):
        from unittest.mock import patch
        async def installed(): return [item('foo')]
        async def libraries(): return [item('shared')]
        downloader = NS(_repo_manager=NS(repos=[repo()]), installed_cogs=installed, installed_libraries=libraries)
        with patch.dict(sys.modules, {'redbot': NS(), 'redbot.core': NS()}):
            added, cogs, libs = await repos.downloader_inventory(NS(get_cog=lambda name: downloader))
        self.assertEqual((len(added), len(cogs), len(libs)), (1, 1, 1))

    async def test_new_downloader(self):
        from unittest.mock import patch
        async def installed(): return []
        source = NS(_repo_manager=NS(repos=[repo()]), installed_cogs=installed, installed_libraries=installed)
        with patch.dict(sys.modules, {'redbot': NS(), 'redbot.core': NS(_downloader=source)}):
            added, cogs, libs = await repos.downloader_inventory(NS(get_cog=lambda name: NS()))
        self.assertEqual(len(added), 1)


if __name__ == '__main__':
    unittest.main()
