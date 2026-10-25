"""Έλεγχοι ενημέρωσης της εφαρμογής από αρχείο."""
import io, json, shutil, sys, tempfile, unittest, zipfile
from pathlib import Path
SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))
import core, updater


def make_zip(version='9.9.9', extra=None, drop=(), manifest=True, app=updater.APP_ID):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        if manifest:
            z.writestr(updater.MANIFEST, json.dumps({'app': app, 'version': version, 'notes': 'δοκιμή'}))
        for p in SRC.rglob('*'):
            n = 'src/' + p.relative_to(SRC).as_posix()
            if p.is_file() and '__pycache__' not in n and n not in drop:
                z.writestr(n, p.read_bytes())
        z.writestr('UPDATE_TEST.txt', 'σημειώσεις')
        for n, data in (extra or {}).items():
            z.writestr(n, data)
    return b.getvalue()


class Updater(unittest.TestCase):
    def test_accepts_valid(self):
        man, files = updater.read(make_zip())
        self.assertEqual(man['version'], '9.9.9')
        self.assertIn('src/core.py', files); self.assertIn('src/templates/ypodeigma_eisagogis_draseon.xlsx', files)
        self.assertEqual(updater.verify(files), core.VERSION)  # ο νέος κώδικας φορτώνεται

    def test_rejects_unsafe_and_foreign(self):
        for extra in ({'../evil.py': 'x'}, {'data/school_actions.db': 'x'}, {'runtime/python.exe': 'x'}, {'evil.exe': 'x'}, {'C:/x.txt': 'x'}):
            with self.assertRaises(ValueError):
                updater.read(make_zip(extra=extra))
        with self.assertRaises(ValueError):
            updater.read(make_zip(manifest=False))
        with self.assertRaises(ValueError):
            updater.read(make_zip(app='orologio-dimotikou'))
        with self.assertRaises(ValueError):
            updater.read(make_zip(drop=('src/server.py',)))
        with self.assertRaises(ValueError):
            updater.read(b'not a zip')

    def test_full_package_hint(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            z.writestr('PDS/runtime/python.exe', 'x')
        with self.assertRaisesRegex(ValueError, 'Setup'):
            updater.read(b.getvalue())

    def test_broken_code_is_rejected_before_install(self):
        man, files = updater.read(make_zip(extra={'src/reports.py': 'def broken(:\n'}))
        with self.assertRaises(ValueError):
            updater.verify(files)

    def test_install_backup_rollback(self):
        root = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(SRC, root / 'src', ignore=shutil.ignore_patterns('__pycache__'))
            (root / 'tests').mkdir(); (root / 'tests' / 'old.py').write_text('# old')
            (root / 'runtime').mkdir(); (root / 'runtime' / 'python.exe').write_text('PY')
            (root / 'START.cmd').write_text('old')
            saved = updater.backup(root, '1.0.0')
            man, files = updater.read(make_zip(extra={'START.cmd': 'new', 'src/extra.txt': 'νέο'}))
            updater.install(root, files)
            self.assertEqual((root / 'START.cmd').read_text(), 'new')
            self.assertTrue((root / 'src' / 'extra.txt').exists())
            self.assertTrue((root / 'src' / 'templates' / 'ypodeigma_eisagogis_draseon.xlsx').exists())
            self.assertTrue((root / 'tests' / 'old.py').exists())
            self.assertEqual((root / 'runtime' / 'python.exe').read_text(), 'PY')
            self.assertEqual([b['version'] for b in updater.list_backups(root)], ['1.0.0'])
            man, files = updater.read(saved.read_bytes()); updater.install(root, files)  # επαναφορά
            self.assertEqual((root / 'START.cmd').read_text(), 'old')
            self.assertFalse((root / 'src' / 'extra.txt').exists())
            self.assertFalse((root / 'versions' / 'update_stage').exists()); self.assertFalse((root / 'versions' / 'update_old').exists())
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_versions(self):
        self.assertGreater(updater.vtuple('2.10.0'), updater.vtuple('2.9.3'))
        self.assertGreater(updater.vtuple(core.VERSION), updater.vtuple('1.7.4'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
