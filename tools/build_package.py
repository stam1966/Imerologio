"""Κατασκευή πακέτων της εφαρμογής.

  python tools/build_package.py                → dist/Programma_Draseon (εφαρμογή + runtime-x64 + runtime-x86),
                                                  dist/Programma_Draseon_<v>_Portable.zip, dist/PDS_Enimerosi_<v>.zip
  python tools/build_package.py --update-only  → μόνο το αρχείο ενημέρωσης
  python tools/build_package.py --runtime-from <φάκελος με runtime-x64/runtime-x86>  → χωρίς λήψη Python

Runtime: Python 3.12 «embeddable» για Windows (64-bit και 32-bit). Η εφαρμογή χρησιμοποιεί μόνο
τη βασική βιβλιοθήκη της Python· δεν εγκαθίστανται πρόσθετα πακέτα.
Ποτέ δεν μπαίνουν δεδομένα σχολείου στα πακέτα (τα δεδομένα βρίσκονται στα Έγγραφα του χρήστη).
"""
import io, json, re, shutil, sys, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
PY_VERSION = '3.12.10'
EMBED = {'x64': 'https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip' % (PY_VERSION, PY_VERSION),
         'x86': 'https://www.python.org/ftp/python/%s/python-%s-embed-win32.zip' % (PY_VERSION, PY_VERSION)}
APP = 'Programma_Draseon'
TOP_FILES = ['START.cmd', 'START_KONSOLA.cmd', 'CHECK.cmd', 'README_EL.txt', 'CHANGELOG.txt']


def version():
    return re.search(r"VERSION = '([^']+)'", (ROOT / 'src/core.py').read_text(encoding='utf-8')).group(1)


def app_files():
    files = {}
    for p in sorted((ROOT / 'src').rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc':
            files['src/' + p.relative_to(ROOT / 'src').as_posix()] = p.read_bytes()
    for p in sorted((ROOT / 'tests').glob('test_*.py')):
        files['tests/' + p.name] = p.read_bytes()
    for n in TOP_FILES:
        if (ROOT / n).exists():
            files[n] = (ROOT / n).read_bytes()
    for p in sorted(ROOT.glob('UPDATE_*.txt')):
        files[p.name] = p.read_bytes()
    return files


def notes(v):
    p = ROOT / ('UPDATE_' + v.split('-')[0] + '.txt')
    return p.read_text(encoding='utf-8') if p.exists() else ''


def build_update(v, files):
    DIST.mkdir(exist_ok=True)
    out = DIST / ('PDS_Enimerosi_' + v.split('-')[0] + '.zip')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('pds-update.json', json.dumps({'app': 'programma-draseon', 'version': v, 'notes': notes(v)}, ensure_ascii=False, indent=1))
        for n, b in sorted(files.items()):
            z.writestr(n, b)
    print('update:', out, out.stat().st_size)
    return out


def build_runtime(target: Path, arch: str):
    """Python embeddable: μόνο η βασική βιβλιοθήκη· ο κώδικας της εφαρμογής από το ../src."""
    target.mkdir(parents=True, exist_ok=True)
    print('download', EMBED[arch])
    raw = urllib.request.urlopen(EMBED[arch], timeout=180).read()
    zipfile.ZipFile(io.BytesIO(raw)).extractall(target)
    (target / ('python%s._pth' % PY_VERSION.replace('.', '')[:3])).write_text('python312.zip\n.\n../src\nimport site\n', encoding='ascii')


def build_full(v, files, runtime_from=None):
    folder = DIST / APP
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for arch in ('x64', 'x86'):
        dst = folder / ('runtime-' + arch)
        if runtime_from:
            shutil.copytree(Path(runtime_from) / ('runtime-' + arch), dst, ignore=shutil.ignore_patterns('__pycache__'))
        else:
            build_runtime(dst, arch)
    for n, b in files.items():
        p = folder / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    return folder


def build_portable(v, folder: Path):
    """Φορητό πακέτο: τα δεδομένα μένουν δίπλα στην εφαρμογή (φάκελος data), όπως στην v1.7."""
    out = DIST / f'{APP}_{v.split("-")[0]}_Portable.zip'
    extra = {
        'shared_data_path.txt': 'Dedomena\r\n',
        'README_FORITO.txt': ('ΦΟΡΗΤΗ ΕΚΔΟΣΗ — Πρόγραμμα Δράσεων Σχολείου %s\r\n\r\n'
                              'Αποσυμπιέστε ΟΛΟ το zip σε φάκελο (π.χ. USB ή κοινόχρηστο φάκελο) και ανοίξτε το START.cmd.\r\n'
                              'Λειτουργεί σε Windows 64-bit και 32-bit χωρίς εγκατάσταση.\r\n\r\n'
                              'Τα δεδομένα αποθηκεύονται στον φάκελο «Dedomena» δίπλα στην εφαρμογή.\r\n'
                              'Για άλλον φάκελο (π.χ. κοινόχρηστο στο δίκτυο), γράψτε τη διαδρομή του στο shared_data_path.txt,\r\n'
                              'π.χ. \\\\server\\PDS\\Shared  (μπορεί να είναι και ο φάκελος Shared της παλιάς v1.7).\r\n\r\n'
                              'Για τους περισσότερους υπολογιστές προτείνεται το Programma_Draseon_Setup.exe.\r\n' % v),
    }
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(folder.rglob('*')):
            if p.is_file():
                z.write(p, APP + '/' + p.relative_to(folder).as_posix())
        for n, text in extra.items():
            z.writestr(APP + '/' + n, text.encode('utf-8-sig' if n.endswith('.txt') and n.startswith('README') else 'utf-8'))
    print('portable:', out, out.stat().st_size)
    return out


if __name__ == '__main__':
    v = version()
    files = app_files()
    build_update(v, files)
    if '--update-only' not in sys.argv:
        rf = sys.argv[sys.argv.index('--runtime-from') + 1] if '--runtime-from' in sys.argv else None
        folder = build_full(v, files, rf)
        build_portable(v, folder)
    DIST.mkdir(exist_ok=True)
    (DIST / 'VERSION.txt').write_text(v, encoding='utf-8')
    (DIST / 'RELEASE_NOTES.md').write_text(
        '**Νέα εγκατάσταση:** κατεβάστε το `Programma_Draseon_Setup.exe` και ανοίξτε το (Windows 64-bit και 32-bit, χωρίς δικαιώματα διαχειριστή).\n\n'
        'Μόνιμος σύνδεσμος λήψης (πάντα η τελευταία έκδοση): '
        'https://github.com/stam1966/Imerologio/releases/latest/download/Programma_Draseon_Setup.exe\n\n'
        '**Ενημέρωση υπάρχουσας εγκατάστασης:** μέσα στην εφαρμογή, κουμπί «Νέα έκδοση» ή Ρυθμίσεις → «Έλεγχος τώρα» '
        '(χωρίς Internet: «Ενημέρωση από αρχείο…» με το `PDS_Enimerosi_….zip`).\n\n'
        '**Φορητή έκδοση** (USB / κοινόχρηστος φάκελος, χωρίς εγκατάσταση): `Programma_Draseon_…_Portable.zip`.\n\n'
        '```\n' + notes(v) + '\n```\n', encoding='utf-8')
