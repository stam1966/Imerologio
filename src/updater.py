"""Ενημέρωση της εφαρμογής από αρχείο .zip (ή από τα Releases του GitHub), με αντίγραφο και επαναφορά.

Κανόνες ασφαλείας:
• Το zip πρέπει να έχει pds-update.json με app = APP_ID.
• Επιτρέπονται μόνο src/, tests/ και αρχεία .cmd/.txt/.json στη ρίζα.
  Ποτέ runtime/ ή δεδομένα: τα δεδομένα βρίσκονται σε άλλον φάκελο και το Python δεν αγγίζεται.
• Ο νέος κώδικας ελέγχεται (μεταγλώττιση + φόρτωση) σε προσωρινό φάκελο
  πριν αντικαταστήσει τον τρέχοντα. Αν αποτύχει η αντικατάσταση, επανέρχεται ο παλιός.
"""
import io, json, os, re, shutil, subprocess, sys, tempfile, time, zipfile, py_compile
from pathlib import Path

APP_ID = 'programma-draseon'
REPO = 'stam1966/Imerologio'
ALLOWED_HOSTS = ('github.com', 'api.github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com')
MANIFEST = 'pds-update.json'
MAX_SIZE = 40_000_000
REQUIRED = ('src/server.py', 'src/core.py', 'src/exports.py', 'src/reports.py', 'src/storage.py', 'src/index.html', 'src/updater.py')
TOP_SUFFIX = ('.cmd', '.txt', '.json')


def vtuple(v):
    return tuple(int(x) for x in re.findall(r'\d+', v or '0')[:3])


def _clean(name):
    n = name.replace('\\', '/')
    if n.endswith('/'):
        return None
    if n.startswith('/') or re.match(r'^[A-Za-z]:', n) or any(part in ('..', '') for part in n.split('/')):
        raise ValueError('Μη ασφαλής διαδρομή στο αρχείο ενημέρωσης: ' + name)
    first = n.split('/')[0]
    if '/' in n:
        if first not in ('src', 'tests') or '__pycache__' in n:
            raise ValueError('Το αρχείο ενημέρωσης περιέχει μη επιτρεπτό φάκελο: ' + first)
    elif not n.lower().endswith(TOP_SUFFIX):
        raise ValueError('Μη επιτρεπτό αρχείο στην ενημέρωση: ' + n)
    return n


def read(raw):
    """Ελέγχει ένα αρχείο ενημέρωσης. Επιστρέφει (manifest, {διαδρομή: bytes})."""
    if len(raw) > MAX_SIZE:
        raise ValueError('Το αρχείο είναι πολύ μεγάλο για ενημέρωση. Μήπως είναι το πλήρες πακέτο; Χρησιμοποιήστε τότε το Setup.exe.')
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ValueError('Το αρχείο δεν είναι έγκυρο .zip.')
    names = z.namelist()
    if MANIFEST not in names:
        if any(n.replace('\\', '/').split('/')[-1] == 'python.exe' for n in names):
            raise ValueError('Αυτό είναι το πλήρες (φορητό) πακέτο, όχι αρχείο ενημέρωσης. Για εγκατάσταση χρησιμοποιήστε το Setup.exe.')
        raise ValueError('Το αρχείο δεν είναι ενημέρωση του «Πρόγραμμα Δράσεων Σχολείου» (λείπει το ' + MANIFEST + ').')
    man = json.loads(z.read(MANIFEST).decode('utf-8'))
    if man.get('app') != APP_ID or not man.get('version'):
        raise ValueError('Το αρχείο δεν είναι ενημέρωση αυτής της εφαρμογής.')
    files = {}
    total = 0
    for info in z.infolist():
        n = _clean(info.filename)
        if n is None or n == MANIFEST:
            continue
        total += info.file_size
        if total > 4 * MAX_SIZE:
            raise ValueError('Μη αποδεκτό μέγεθος περιεχομένων.')
        files[n] = z.read(info)
    missing = [r for r in REQUIRED if r not in files]
    if missing:
        raise ValueError('Ελλιπές αρχείο ενημέρωσης (λείπει ' + ', '.join(missing) + ').')
    return man, files


def verify(files):
    """Μεταγλώττιση και φόρτωση του νέου κώδικα σε προσωρινό φάκελο."""
    tmp = Path(tempfile.mkdtemp(prefix='pds_upd_'))
    try:
        for n, b in files.items():
            p = tmp / n; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b)
        for p in (tmp / 'src').glob('*.py'):
            py_compile.compile(str(p), doraise=True, cfile=str(tmp / 'pyc' / (p.name + 'c')))
        code = 'import sys;sys.path.insert(0,sys.argv[1]);import core,exports,reports,storage,updater,server;print(core.VERSION)'
        exe = sys.executable
        if exe.lower().endswith('pythonw.exe') and Path(exe[:-5] + '.exe').exists():
            exe = exe[:-5] + '.exe'
        kw = {}
        if sys.platform == 'win32':
            kw['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
        r = subprocess.run([exe, '-X', 'utf8', '-c', code, str(tmp / 'src')], capture_output=True, timeout=120, cwd=str(tmp), **kw)
        if r.returncode != 0:
            raise ValueError('Ο νέος κώδικας δεν φορτώνεται σε αυτόν τον υπολογιστή· η ενημέρωση ακυρώθηκε.\n' + r.stderr.decode('utf-8', 'replace')[-800:])
        return r.stdout.decode('utf-8', 'replace').strip()
    except py_compile.PyCompileError as ex:
        raise ValueError('Σφάλμα στον νέο κώδικα· η ενημέρωση ακυρώθηκε. ' + str(ex)[:400])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def current_files(root):
    out = {}
    for d in ('src', 'tests'):
        for p in (root / d).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                out[p.relative_to(root).as_posix()] = p.read_bytes()
    for p in root.iterdir():
        if p.is_file() and p.suffix.lower() in TOP_SUFFIX:
            out[p.name] = p.read_bytes()
    return out


def backup(root, version):
    """Αντίγραφο της τρέχουσας έκδοσης σε μορφή αρχείου ενημέρωσης (για επαναφορά)."""
    folder = root / 'versions'; folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('efarmogi_' + re.sub(r'[^0-9A-Za-z.-]', '', version) + '_' + time.strftime('%Y%m%d_%H%M%S') + '.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST, json.dumps({'app': APP_ID, 'version': version, 'notes': 'Αντίγραφο πριν από ενημέρωση'}, ensure_ascii=False))
        for n, b in current_files(root).items():
            z.writestr(n, b)
    return path


def install(root, files):
    """Αντικαθιστά src/ και tests/ ατομικά (μετονομασία) και γράφει τα αρχεία ρίζας."""
    stage = root / 'versions' / 'update_stage'
    old = root / 'versions' / 'update_old'
    for d in (stage, old):
        shutil.rmtree(d, ignore_errors=True)
    for n, b in files.items():
        p = stage / n; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b)
    moved = []
    try:
        old.mkdir(parents=True)
        for d in ('src', 'tests'):
            if (stage / d).exists():
                if (root / d).exists():
                    (root / d).rename(old / d)
                moved.append(d)
                (stage / d).rename(root / d)
        for n in files:
            if '/' not in n:
                if (root / n).exists():
                    shutil.copy2(root / n, old / n)
                shutil.copy2(stage / n, root / n)
    except Exception:
        for d in moved:  # επαναφορά
            if (root / d).exists() and (old / d).exists():
                shutil.rmtree(root / d, ignore_errors=True)
            if (old / d).exists():
                (old / d).rename(root / d)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)


def list_backups(root):
    folder = root / 'versions'
    out = []
    for p in sorted(folder.glob('efarmogi_*.zip'), reverse=True):
        try:
            with zipfile.ZipFile(p) as z:
                man = json.loads(z.read(MANIFEST).decode('utf-8'))
            out.append({'name': p.name, 'version': man.get('version', '?'), 'date': time.strftime('%d/%m/%Y %H:%M', time.localtime(p.stat().st_mtime))})
        except Exception:
            continue
    return out


def restart(root, port):
    """Ξεκινά νέα διεργασία της εφαρμογής στην ίδια θύρα· η τρέχουσα πρέπει να τερματίσει αμέσως μετά."""
    exe = sys.executable
    args = [exe, '-X', 'utf8', str(root / 'src' / 'server.py'), '--port', str(port), '--restarted']
    kw = {'cwd': str(root), 'close_fds': True}
    if sys.platform == 'win32':
        kw['creationflags'] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw['start_new_session'] = True
    subprocess.Popen(args, **kw)


def _get(url, limit, accept='application/octet-stream'):
    import urllib.request, urllib.parse
    host = urllib.parse.urlparse(url).hostname or ''
    if url.split(':', 1)[0] != 'https' or not any(host == h or host.endswith('.' + h) for h in ALLOWED_HOSTS):
        raise ValueError('Μη αποδεκτή διεύθυνση ενημέρωσης.')
    req = urllib.request.Request(url, headers={'User-Agent': 'Programma-Draseon', 'Accept': accept})
    with urllib.request.urlopen(req, timeout=60) as r:
        final = urllib.parse.urlparse(r.geturl()).hostname or ''
        if not any(final == h or final.endswith('.' + h) for h in ALLOWED_HOSTS):
            raise ValueError('Μη αποδεκτή ανακατεύθυνση ενημέρωσης.')
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Πολύ μεγάλο αρχείο.')
    return data


def check_online():
    """Η τελευταία δημοσιευμένη έκδοση στο GitHub: {'version','notes','url','page'} ή None."""
    try:
        info = json.loads(_get('https://api.github.com/repos/' + REPO + '/releases/latest', 2_000_000, 'application/vnd.github+json').decode('utf-8'))
    except Exception as ex:
        raise ValueError('Δεν ήταν δυνατός ο έλεγχος για νέα έκδοση (σύνδεση στο Internet;). ' + str(ex)[:120])
    asset = next((a for a in info.get('assets', []) if a.get('name', '').startswith('PDS_Enimerosi_') and a['name'].endswith('.zip')), None)
    if not asset:
        return None
    return {'version': (info.get('tag_name') or '').lstrip('v'), 'notes': info.get('body') or '', 'url': asset['browser_download_url'], 'page': info.get('html_url', '')}


def download(url):
    return _get(url, MAX_SIZE)
