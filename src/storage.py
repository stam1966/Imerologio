"""Πού βρίσκονται τα δεδομένα, κλείδωμα κοινόχρηστης χρήσης και αντίγραφα ασφαλείας.

Θέση δεδομένων (με σειρά προτεραιότητας):
 1. Μεταβλητή περιβάλλοντος PDS_DATA_DIR (δοκιμές / προχωρημένη χρήση).
 2. Αρχείο shared_data_path.txt δίπλα στην εφαρμογή (φορητή / κοινόχρηστη χρήση, όπως στην v1.7).
    Σχετική διαδρομή = ως προς τον φάκελο της εφαρμογής.
 3. Επιλογή χρήστη από τις Ρυθμίσεις (αποθηκεύεται σε %LOCALAPPDATA%\\ProgrammaDraseon\\config.json).
 4. Έγγραφα\\Πρόγραμμα Δράσεων Σχολείου (προεπιλογή).
Μέσα στον φάκελο: data\\school_actions.db, backups\\, exports\\.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import string
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # φάκελος εφαρμογής
FOLDER_NAME = 'Πρόγραμμα Δράσεων Σχολείου'


def documents_dir() -> Path:
    """Ο φάκελος «Έγγραφα» (και όταν έχει μεταφερθεί στο OneDrive)."""
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:  # CSIDL_PERSONAL
                return Path(buf.value)
        except Exception:
            pass
    home = Path.home()
    return home / 'Documents' if (home / 'Documents').is_dir() else home


def machine_dir() -> Path:
    """Ρυθμίσεις του συγκεκριμένου υπολογιστή (όχι δεδομένα σχολείου)."""
    base = os.environ.get('LOCALAPPDATA') or str(Path.home() / '.local' / 'share')
    p = Path(os.environ.get('PDS_MACHINE_DIR') or (Path(base) / 'ProgrammaDraseon'))
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_config() -> dict:
    try:
        return json.loads((machine_dir() / 'config.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    p = machine_dir() / 'config.json'
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, p)


def shared_path_file() -> Path | None:
    for p in (ROOT / 'shared_data_path.txt', ROOT.parent / 'shared_data_path.txt'):
        if p.is_file():
            return p
    return None


def data_root() -> tuple[Path, str]:
    """(φάκελος, προέλευση) — προέλευση: env | shared | custom | documents."""
    if os.environ.get('PDS_DATA_DIR'):
        return Path(os.environ['PDS_DATA_DIR']), 'env'
    f = shared_path_file()
    if f:
        value = f.read_text(encoding='utf-8-sig').strip().strip('"')
        if value:
            p = Path(os.path.expandvars(value))
            return (p if p.is_absolute() else (f.parent / p).resolve()), 'shared'
    custom = load_config().get('data_dir')
    if custom:
        return Path(custom), 'custom'
    return documents_dir() / FOLDER_NAME, 'documents'


class Paths:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.data = self.root / 'data'
        self.db = self.data / 'school_actions.db'
        self.backups = self.root / 'backups'
        self.exports = self.root / 'exports'

    def ensure(self) -> 'Paths':
        for d in (self.data, self.backups, self.exports):
            d.mkdir(parents=True, exist_ok=True)
        return self


def check_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    test = path / '.pds_test'
    try:
        test.write_text('ok', encoding='utf-8')
        test.unlink()
    except OSError:
        raise ValueError('Δεν επιτρέπεται εγγραφή στον φάκελο: ' + str(path))


# ------------------------------------------------------------------ κλείδωμα κοινόχρηστης χρήσης
class DataLock:
    """Αποτρέπει ταυτόχρονη χρήση του ίδιου φακέλου δεδομένων από δύο υπολογιστές.
    Χρησιμοποιεί κλείδωμα αρχείου του λειτουργικού (ισχύει και σε κοινόχρηστο φάκελο δικτύου)
    και δεν «ξεχνιέται» αν η εφαρμογή κλείσει απότομα."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.handle = None

    def acquire(self) -> bool:
        self.folder.mkdir(parents=True, exist_ok=True)
        h = open(self.folder / 'app.lock', 'a+b')
        try:
            h.seek(0)
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(h.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            h.close()
            return False
        self.handle = h
        try:
            (self.folder / 'app.lock.info').write_text(
                f'host={socket.gethostname()}\nuser={os.environ.get("USERNAME") or os.environ.get("USER") or ""}\n'
                f'time={datetime.now().strftime("%d/%m/%Y %H:%M")}\npid={os.getpid()}\n', encoding='utf-8')
        except OSError:
            pass
        return True

    def holder(self) -> str:
        try:
            info = dict(line.split('=', 1) for line in (self.folder / 'app.lock.info').read_text(encoding='utf-8').splitlines() if '=' in line)
            return f"{info.get('host', '?')} ({info.get('user', '')}, από {info.get('time', '?')})"
        except Exception:
            return 'άγνωστος υπολογιστής'

    def release(self) -> None:
        if self.handle:
            for name in ('app.lock.info',):
                try:
                    (self.folder / name).unlink()
                except OSError:
                    pass
            try:
                self.handle.close()
            except OSError:
                pass
            self.handle = None
            try:  # ώστε η παλιά έκδοση v1.7 να μη θεωρεί ότι η εφαρμογή είναι ακόμη ανοιχτή
                (self.folder / 'app.lock').unlink()
            except OSError:
                pass


# ------------------------------------------------------------------ αντίγραφα ασφαλείας
BACKUP_RE = re.compile(r'(\d{8})_(\d{6})')


def backup_name(prefix: str = 'school_actions_backup') -> str:
    return f'{prefix}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'


def create_backup(db, paths: Paths, reason: str = '') -> Path:
    """Αντίγραφο της βάσης στον φάκελο backups. reason: '' (χειροκίνητο), 'auto_delete', 'auto_import', 'before_restore'."""
    prefix = {'': 'school_actions_backup', 'auto_delete': 'auto_prin_diagrafi', 'auto_import': 'auto_prin_eisagogi',
              'before_restore': 'before_restore', 'before_update': 'auto_prin_enimerosi'}.get(reason, 'school_actions_backup')
    target = paths.backups / backup_name(prefix)
    n = 1
    while target.exists():
        target = paths.backups / backup_name(prefix).replace('.db', f'_{n}.db'); n += 1
    db.backup_to(target)
    return target


KIND_LABEL = {'school_actions_backup': 'Χειροκίνητο', 'auto_prin_diagrafi': 'Πριν από διαγραφή', 'auto_prin_eisagogi': 'Πριν από εισαγωγή',
              'before_restore': 'Πριν από επαναφορά', 'auto_prin_enimerosi': 'Πριν από ενημέρωση', 'imerisio': 'Ημερήσιο'}


def list_backups(paths: Paths) -> list[dict]:
    out = []
    for f in paths.backups.glob('*.db'):
        m = BACKUP_RE.search(f.name)
        try:
            when = datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S') if m else datetime.fromtimestamp(f.stat().st_mtime)
        except ValueError:
            when = datetime.fromtimestamp(f.stat().st_mtime)
        prefix = f.name[:m.start()].rstrip('_') if m else ''
        out.append({'name': f.name, 'when': when.strftime('%d/%m/%Y %H:%M'), 'sort': when.isoformat(),
                    'size': f.stat().st_size, 'kind': KIND_LABEL.get(prefix, 'Αντίγραφο')})
    return sorted(out, key=lambda x: x['sort'], reverse=True)


def prune_auto_backups(paths: Paths, keep: int = 60) -> int:
    """Κρατά τα 60 πιο πρόσφατα αυτόματα αντίγραφα (τα χειροκίνητα δεν σβήνονται ποτέ)."""
    autos = sorted((f for f in paths.backups.glob('auto_*.db')), key=lambda f: f.name, reverse=True)
    removed = 0
    for f in autos[keep:]:
        try:
            f.unlink(); removed += 1
        except OSError:
            pass
    return removed


def safe_backup_path(paths: Paths, name: str) -> Path:
    if not name or '/' in name or '\\' in name or name.startswith('.') or not name.endswith('.db'):
        raise ValueError('Μη έγκυρο όνομα αντιγράφου.')
    p = paths.backups / name
    if not p.is_file():
        raise ValueError('Δεν βρέθηκε το αντίγραφο.')
    return p


def daily_external(db, folder: str, last: str, keep: int = 60) -> str | None:
    """Ημερήσιο αντίγραφο σε φάκελο επιλογής (π.χ. USB, OneDrive). Επιστρέφει τη διαδρομή ή None."""
    today = datetime.now().strftime('%Y-%m-%d')
    if not folder or last == today:
        return None
    p = Path(folder)
    check_writable(p)
    target = p / f'Draseis_{today}.db'
    db.backup_to(target)
    olds = sorted(p.glob('Draseis_????-??-??.db'))
    for f in olds[:-keep]:
        try:
            f.unlink()
        except OSError:
            pass
    return str(target)


# ------------------------------------------------------------------ επιλογή φακέλου (μέσα από την εφαρμογή)
def _drives():
    out = []
    if sys.platform == 'win32':
        try:
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            kinds = {2: 'Αφαιρούμενος δίσκος (USB)', 3: 'Τοπικός δίσκος', 4: 'Δίσκος δικτύου'}
            for i, letter in enumerate(string.ascii_uppercase):
                if mask & (1 << i):
                    root = letter + ':\\'
                    t = ctypes.windll.kernel32.GetDriveTypeW(root)
                    if t in kinds:
                        out.append({'label': letter + ': ' + kinds[t], 'path': root})
        except Exception:
            pass
    else:
        out.append({'label': '/', 'path': '/'})
    return out


def browse(path: str = '') -> dict:
    if not path:
        home = Path.home()
        places = []
        for label, p in (('Έγγραφα', documents_dir()), ('Επιφάνεια εργασίας', home / 'Desktop'),
                         ('OneDrive', Path(os.environ['OneDrive']) if os.environ.get('OneDrive') else None),
                         ('Λήψεις', home / 'Downloads'), ('Προσωπικός φάκελος', home)):
            if p and p.is_dir():
                places.append({'label': label, 'path': str(p)})
        return {'path': '', 'parent': None, 'places': places, 'drives': _drives(), 'dirs': [], 'crumbs': [], 'writable': False}
    p = Path(path).expanduser()
    if not p.is_dir():
        raise ValueError('Ο φάκελος δεν υπάρχει: ' + str(p))
    dirs = []
    try:
        for c in p.iterdir():
            try:
                if c.is_dir() and not c.name.startswith(('.', '$')) and c.name not in ('System Volume Information', '__pycache__'):
                    dirs.append(c.name)
            except OSError:
                continue
    except PermissionError:
        raise ValueError('Δεν επιτρέπεται η πρόσβαση στον φάκελο: ' + str(p))
    dirs.sort(key=str.casefold)
    try:
        check_writable(p); writable = True
    except (ValueError, OSError):
        writable = False
    crumbs = [{'label': (q.name or str(q)).rstrip('\\/') or str(q), 'path': str(q)} for q in reversed([p, *p.parents])]
    return {'path': str(p), 'parent': str(p.parent) if p.parent != p else '', 'places': [], 'drives': [], 'crumbs': crumbs,
            'dirs': [{'name': d, 'path': str(p / d)} for d in dirs[:500]], 'writable': writable,
            'has_data': (p / 'data' / 'school_actions.db').is_file()}


BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def make_dir(parent: str, name: str) -> str:
    name = (name or '').strip().rstrip('.')
    if not name or BAD_NAME.search(name) or name in ('.', '..'):
        raise ValueError('Μη έγκυρο όνομα φακέλου (δεν επιτρέπονται οι χαρακτήρες < > : " / \\ | ? *).')
    p = Path(parent)
    if not p.is_dir():
        raise ValueError('Ο φάκελος δεν υπάρχει: ' + str(p))
    q = p / name
    try:
        q.mkdir(exist_ok=True)
    except OSError as ex:
        raise ValueError('Δεν ήταν δυνατή η δημιουργία του φακέλου: ' + str(ex))
    return str(q)


def open_in_explorer(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'win32':
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == 'darwin':
        import subprocess; subprocess.Popen(['open', str(path)])
    else:
        import subprocess; subprocess.Popen(['xdg-open', str(path)])


def copy_tree_data(src: Paths, dst: Paths) -> None:
    """Αντιγραφή δεδομένων σε νέο φάκελο (για αλλαγή θέσης). Δεν σβήνει τα παλιά."""
    dst.ensure()
    if dst.db.exists():
        raise ValueError('Στον νέο φάκελο υπάρχουν ήδη δεδομένα της εφαρμογής. Επιλέξτε «Χρήση των δεδομένων του φακέλου».')
    shutil.copy2(src.db, dst.db)
    for sub in ('backups', 'exports'):
        s, d = src.root / sub, dst.root / sub
        if s.is_dir():
            for f in s.rglob('*'):
                if f.is_file():
                    t = d / f.relative_to(s)
                    t.parent.mkdir(parents=True, exist_ok=True)
                    if not t.exists():
                        shutil.copy2(f, t)
    time.sleep(0)
