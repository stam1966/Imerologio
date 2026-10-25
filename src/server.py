"""Τοπική υπηρεσία της εφαρμογής: API, άνοιγμα παραθύρου, εργασίες συντήρησης.

Η εφαρμογή ανοίγει σε δικό της παράθυρο (Edge/Chrome σε λειτουργία εφαρμογής) στη διεύθυνση
127.0.0.1 του υπολογιστή. Δεν φιλοξενείται σε ιστοσελίδα και δεν στέλνει δεδομένα πουθενά.
"""
import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import core
import exports
import reports
import storage
import updater

ROOT = storage.ROOT
SRC = ROOT / 'src'
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
APP = {'paths': None, 'db': None, 'lock': None, 'source': '', 'first_run': False, 'unlocked': False,
       'update': None, 'last_backup_written': ''}
LAST_SEEN = [time.time()]
BYE = [0.0]
MAX_BODY = 40_000_000


def log(*a):
    try:
        f = storage.machine_dir() / 'app.log'
        if f.exists() and f.stat().st_size > 2_000_000:
            f.replace(f.with_suffix('.old.log'))
        with open(f, 'a', encoding='utf-8') as fh:
            fh.write(time.strftime('%Y-%m-%d %H:%M:%S ') + ' '.join(str(x) for x in a) + '\n')
    except OSError:
        pass
    try:
        print(*a)
    except Exception:
        pass


# ------------------------------------------------------------------ δεδομένα
def open_data(root: Path, source: str):
    """Ανοίγει (ή δημιουργεί) τα δεδομένα στον φάκελο root. Επιστρέφει None ή μήνυμα σφάλματος."""
    paths = storage.Paths(root)
    try:
        paths.ensure()
    except OSError as ex:
        return f'Ο φάκελος δεδομένων δεν είναι διαθέσιμος:\n{root}\n\n{ex}'
    lock = storage.DataLock(paths.root)
    if not lock.acquire():
        return (f'Τα δεδομένα χρησιμοποιούνται ήδη από άλλον υπολογιστή:\n{lock.holder()}\n\n'
                f'Φάκελος: {root}\n\nΚλείστε την εφαρμογή εκεί και ξαναδοκιμάστε.')
    first = not paths.db.exists()
    try:
        db = core.Database(paths.db)
    except Exception as ex:
        lock.release()
        return f'Δεν ήταν δυνατό να ανοίξει η βάση δεδομένων:\n{paths.db}\n\n{ex}'
    APP.update(paths=paths, db=db, lock=lock, source=source, first_run=first, unlocked=False)
    try:
        n = storage.prune_auto_backups(paths)
        if n:
            log('pruned auto backups', n)
    except Exception as ex:
        log('prune error', repr(ex))
    log('data', root, source, 'new' if first else 'existing')
    return None


def close_data():
    if APP['db']:
        APP['db'].close()
    if APP['lock']:
        APP['lock'].release()
    APP.update(db=None, lock=None)


def db() -> core.Database:
    return APP['db']


def paths() -> storage.Paths:
    return APP['paths']


# ------------------------------------------------------------------ κατάσταση
def state():
    d = db()
    cfg = storage.load_config()
    return {
        'version': core.VERSION, 'app_name': core.APP_NAME, 'author': core.APP_AUTHOR, 'today': date.today().isoformat(),
        'school_name': d.school_name(), 'school_years': d.school_years(), 'current_school_year': d.current_school_year(),
        'categories': d.categories(), 'category_config': d.category_config(), 'icon_choices': core.CATEGORY_ICON_CHOICES,
        'palette': core.CATEGORY_COLORS,
        'statuses': core.STATUSES, 'flags': core.CALENDAR_FLAGS, 'features': d.features(), 'report_types': reports.REPORT_TYPES,
        'default_category': core.DEFAULT_ACTION_CATEGORY,
        'data': {'root': str(paths().root), 'source': APP['source'], 'db': str(paths().db),
                 'documents_default': str(storage.documents_dir() / storage.FOLDER_NAME)},
        'lifelog': lifelog_status(), 'update': APP['update'], 'first_run': APP['first_run'],
        'backup': {'folder': cfg.get('backup_dir', ''), 'last': cfg.get('last_backup', '')},
        'platform': sys.platform,
    }


def lifelog_status():
    d = db()
    return {'protected': d.lifelog_protected(), 'has_password': d.lifelog_has_password(), 'unlocked': APP['unlocked']}


def lifelog_guard():
    s = lifelog_status()
    if s['protected'] and not s['unlocked']:
        raise PermissionError('Το Ημερολόγιο Σχολικής Ζωής είναι κλειδωμένο.')


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def auto_backup(reason: str, feature: str):
    if feature and not db().get_bool(feature, True):
        return ''
    p = storage.create_backup(db(), paths(), reason)
    return p.name


# ------------------------------------------------------------------ ενέργειες API
def a_state(r):
    return state()


def a_dashboard(r):
    return db().dashboard()


def a_actions_list(r):
    rows = db().list_actions(r.get('filters') or {})
    return {'rows': rows, 'total': len(db().list_actions())}


def a_actions_save(r):
    a = r.get('action') or {}
    aid = db().save_action(a)
    APP['first_run'] = False
    return {'id': aid, 'action': db().get_action(aid)}


def a_actions_delete(r):
    ids = [int(i) for i in r.get('ids') or []]
    if not ids:
        raise ValueError('Δεν επιλέχθηκαν δράσεις.')
    rows = db().list_actions({'ids': ids})
    name = auto_backup('auto_delete', 'auto_backup_before_delete')
    return {'deleted': db().delete_actions(ids), 'backup': name, 'rows': rows}


def a_actions_undelete(r):
    return {'restored': db().restore_actions(r.get('rows') or [])}


def a_actions_bulk(r):
    return db().bulk_update(r.get('ids') or [], r.get('status'), r.get('calendar_flag'))


def a_guide_list(r):
    d = db()
    sy = r.get('school_year') or d.current_school_year()
    cat = r.get('category') or 'Όλες'
    cfg = d.category_config()
    out = []
    for it in d.guide_items():
        if cat != 'Όλες' and it['category'] != cat:
            continue
        iso = core.guide_item_iso_date(it, sy)
        out.append({**it, 'date': iso, 'exists': d.action_exists(iso, it['title']), 'internal': core.is_internal(it['category'], cfg),
                    'milestone': core.is_academic_milestone(it['category'], it['title']), 'icon': core.category_icon(it['category'], cfg)})
    return {'items': out, 'school_year': sy}


def a_guide_save(r):
    db().save_guide_item(r.get('item') or {}, r.get('original'))
    return {}


def a_guide_delete(r):
    db().delete_guide_item(r['item'])
    return {}


def a_guide_reset(r):
    db().reset_guide()
    return {}


def a_guide_create(r):
    """Δημιουργία δράσεων από επιλεγμένες ημέρες του Οδηγού (παραλείπει όσες υπάρχουν ήδη)."""
    d = db()
    sy = r.get('school_year') or d.current_school_year()
    created = skipped = 0
    for it in r.get('items') or []:
        it = core.clean_guide_item(it)
        iso = core.guide_item_iso_date(it, sy)
        if d.action_exists(iso, it['title']):
            skipped += 1
            continue
        d.ensure_category(it['category'])
        d.save_action({'action_date': iso, 'title': it['title'], 'category': it['category'], 'description': it['description'],
                       'status': 'Προγραμματισμένη'})
        created += 1
    if created:
        APP['first_run'] = False
    return {'created': created, 'skipped': skipped}


def _import_rows(r):
    raw = base64.b64decode(r.get('data') or '')
    if not raw:
        raise ValueError('Το αρχείο είναι κενό.')
    rows = exports.read_import(r.get('name') or '', raw)
    if not rows:
        raise ValueError('Το αρχείο δεν περιέχει εγγραφές.')
    return rows


def a_import_preview(r):
    plan = exports.plan_import(db(), _import_rows(r))
    return {'count': len(plan['records']), 'records': plan['records'][:300], 'errors': plan['errors'],
            'duplicates': plan['duplicates'], 'warnings': plan['warnings']}


def a_import_apply(r):
    plan = exports.plan_import(db(), _import_rows(r))
    if not plan['records']:
        raise ValueError('Δεν υπάρχουν νέες έγκυρες εγγραφές για εισαγωγή.')
    name = auto_backup('auto_import', 'auto_backup_before_import')
    n = db().insert_many(plan['records'])
    APP['first_run'] = False
    return {'imported': n, 'duplicates': len(plan['duplicates']), 'errors': plan['errors'], 'backup': name}


def a_template(r):
    data = (SRC / 'templates' / 'ypodeigma_eisagogis_draseon.xlsx').read_bytes()
    return {'data': b64(data), 'filename': 'ypodeigma_eisagogis_draseon.xlsx',
            'mime': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}


def a_export(r):
    rows = db().list_actions(r.get('filters') or {})
    res = exports.export(db(), r.get('kind'), rows)
    res['data'] = b64(res['data'])
    return res


def a_report(r):
    res = reports.actions_report(db(), r.get('options') or {}, toolbar=bool(r.get('toolbar')))
    return res


def a_lifelog_status(r):
    return lifelog_status()


def a_lifelog_setup(r):
    d = db()
    if d.lifelog_has_password() and not APP['unlocked']:
        raise PermissionError('Έχει ήδη οριστεί κωδικός.')
    pw, pw2 = r.get('password') or '', r.get('confirm') or ''
    if pw != pw2:
        raise ValueError('Οι δύο κωδικοί δεν συμφωνούν.')
    d.lifelog_set_password(pw)
    APP['unlocked'] = True
    return lifelog_status()


FAILS = {'n': 0, 'until': 0.0}


def a_lifelog_unlock(r):
    if time.time() < FAILS['until']:
        raise PermissionError('Πολλές λανθασμένες προσπάθειες. Δοκιμάστε ξανά σε λίγα δευτερόλεπτα.')
    if not db().lifelog_check(r.get('password') or ''):
        FAILS['n'] += 1
        if FAILS['n'] >= 5:
            FAILS.update(n=0, until=time.time() + 30)
        raise PermissionError('Λανθασμένος κωδικός πρόσβασης.')
    FAILS['n'] = 0
    APP['unlocked'] = True
    return lifelog_status()


def a_lifelog_lock(r):
    APP['unlocked'] = False
    return lifelog_status()


def _ll_range(r):
    """Περίοδος από τα πεδία από/έως ή, αν λείπουν, από το σχολικό έτος."""
    f, t = r.get('date_from') or '', r.get('date_to') or ''
    sy = r.get('school_year') or ''
    if not f and not t and core.valid_school_year_label(sy):
        a, b = core.school_year_bounds(sy)
        f, t = a.isoformat(), (b - timedelta(days=1)).isoformat()
    return f, t


def a_lifelog_list(r):
    lifelog_guard()
    f, t = _ll_range(r)
    return {'rows': db().lifelog_list(r.get('search') or '', f, t), 'years': db().lifelog_years()}


def _ll_file(r):
    raw = base64.b64decode(r.get('data') or '')
    if len(raw) > 30 * 1024 * 1024:
        raise ValueError('Το αρχείο είναι πολύ μεγάλο.')
    return exports.plan_lifelog_import(db(), r.get('name') or '', raw)


def a_lifelog_import_preview(r):
    lifelog_guard()
    plan = _ll_file(r)
    plan['records'] = plan['records'][:400]
    return plan


def a_lifelog_import_apply(r):
    lifelog_guard()
    plan = _ll_file(r)
    if not plan['records']:
        raise ValueError('Δεν υπάρχουν νέες καταγραφές για εισαγωγή.')
    name = auto_backup('auto_import', 'auto_backup_before_import')
    return {'imported': db().lifelog_insert_many(plan['records']), 'duplicates': plan['duplicates'], 'backup': name,
            'years': plan['years']}


def a_lifelog_phrases(r):
    return db().lifelog_phrases()


def a_lifelog_phrases_save(r):
    lifelog_guard()
    return db().set_lifelog_phrases(r.get('items') or [])


def a_lifelog_phrases_reset(r):
    lifelog_guard()
    return db().reset_lifelog_phrases()


def a_lifelog_suggest(r):
    lifelog_guard()
    return db().lifelog_suggest(r.get('date') or '', r.get('search') or '')


def a_lifelog_save(r):
    lifelog_guard()
    return {'id': db().lifelog_save(r.get('entry') or {})}


def a_lifelog_delete(r):
    lifelog_guard()
    ids = {int(i) for i in r.get('ids') or []}
    rows = [x for x in db().lifelog_list() if x['id'] in ids]
    db().lifelog_delete(ids)
    return {'rows': rows}


def a_lifelog_undelete(r):
    lifelog_guard()
    return {'restored': db().lifelog_restore(r.get('rows') or [])}


def a_lifelog_transfer(r):
    lifelog_guard()
    return {'count': db().lifelog_transfer_completed()}


def a_lifelog_report(r):
    lifelog_guard()
    f, t = _ll_range(r)
    rows = db().lifelog_list(r.get('search') or '', f, t)
    sub = []
    if not r.get('date_from') and not r.get('date_to') and core.valid_school_year_label(r.get('school_year') or ''):
        sub.append('Σχολικό έτος: ' + r['school_year'])
    elif f or t:
        sub.append('Περίοδος: ' + (core.iso_to_display(f) or '…') + ' έως ' + (core.iso_to_display(t) or '…'))
    if r.get('search'):
        sub.append(f"Αναζήτηση: «{r['search']}»")
    return reports.lifelog_report(db(), rows, ' • '.join(sub), toolbar=bool(r.get('toolbar')))


def a_lifelog_settings(r):
    lifelog_guard()
    d = db()
    protect = bool(r.get('protected', True))
    new = r.get('new_password') or ''
    if new:
        if new != (r.get('confirm') or ''):
            raise ValueError('Οι δύο κωδικοί δεν συμφωνούν.')
        d.lifelog_set_password(new)
    if protect and not d.lifelog_has_password():
        raise ValueError('Ορίστε κωδικό πρόσβασης για να ενεργοποιηθεί η προστασία.')
    d.set_bool('life_log_protection_enabled', protect)
    return lifelog_status()


def a_backup_list(r):
    return {'backups': storage.list_backups(paths()), 'folder': str(paths().backups)}


def a_backup_create(r):
    return {'name': storage.create_backup(db(), paths()).name}


def _restore_from(src: Path):
    if not core.is_valid_database(src):
        raise ValueError('Το αρχείο δεν είναι βάση δεδομένων του «Πρόγραμμα Δράσεων Σχολείου» (school_actions.db ή αντίγραφό της).')
    safety = storage.create_backup(db(), paths(), 'before_restore')
    root, source = paths().root, APP['source']
    tmp = paths().data / 'restore.tmp'
    shutil.copy2(src, tmp)
    close_data()
    os.replace(tmp, paths().db)
    err = open_data(root, source)
    if err:
        raise ValueError(err)
    return {'safety': safety.name, 'count': len(db().list_actions())}


def a_backup_restore(r):
    return _restore_from(storage.safe_backup_path(paths(), r.get('name', '')))


def a_backup_upload(r):
    raw = base64.b64decode(r.get('data') or '')
    tmp = paths().data / 'upload.tmp'
    tmp.write_bytes(raw)
    try:
        return _restore_from(tmp)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def a_backup_download(r):
    p = storage.safe_backup_path(paths(), r.get('name', ''))
    return {'data': b64(p.read_bytes()), 'filename': p.name, 'mime': 'application/octet-stream'}


def a_backup_current(r):
    tmp = paths().data / 'download.tmp'
    db().backup_to(tmp)
    try:
        return {'data': b64(tmp.read_bytes()), 'filename': storage.backup_name(), 'mime': 'application/octet-stream'}
    finally:
        tmp.unlink()


def a_backup_settings(r):
    cfg = storage.load_config()
    folder = (r.get('folder') or '').strip()
    if folder:
        storage.check_writable(Path(folder))
    cfg['backup_dir'] = folder
    cfg['last_backup'] = ''
    storage.save_config(cfg)
    written = daily_backup()
    return {'folder': folder, 'written': written}


def daily_backup(force=False):
    cfg = storage.load_config()
    if not cfg.get('backup_dir') or not db():
        return None
    path = storage.daily_external(db(), cfg['backup_dir'], '' if force else cfg.get('last_backup', ''))
    if path:
        cfg['last_backup'] = date.today().isoformat()
        storage.save_config(cfg)
        log('daily backup', path)
    return path


def a_backup_external_now(r):
    p = daily_backup(force=True)
    if not p:
        raise ValueError('Ορίστε πρώτα φάκελο για τα ημερήσια αντίγραφα.')
    return {'written': p}


def a_settings_save(r):
    d = db()
    if 'school_name' in r:
        d.set_setting('school_name', (r['school_name'] or '').strip() or 'Σχολική μονάδα')
    if r.get('current_school_year'):
        d.set_current_school_year(r['current_school_year'])
    if isinstance(r.get('features'), dict):
        d.set_features(r['features'])
    return state()


def a_years_add(r):
    db().add_school_year(r.get('year', ''))
    if r.get('make_current'):
        db().set_current_school_year(r['year'])
    return state()


def a_categories_save(r):
    cats = [c for c in (r.get('categories') or []) if (c or '').strip()]
    if len(set(c.strip() for c in cats)) != len(cats):
        raise ValueError('Υπάρχουν δύο κατηγορίες με το ίδιο όνομα.')
    db().save_categories(cats, r.get('config') or {}, r.get('renames') or {})
    return state()


def a_open(r):
    what = r.get('what')
    target = {'data': paths().root, 'backups': paths().backups, 'exports': paths().exports, 'app': ROOT,
              'external': Path(storage.load_config().get('backup_dir') or paths().backups)}.get(what)
    if target is None:
        raise ValueError('Άγνωστος φάκελος.')
    storage.open_in_explorer(target)
    return {}


def a_fs_list(r):
    return storage.browse(r.get('path') or '')


def a_fs_mkdir(r):
    return {'path': storage.make_dir(r.get('parent') or '', r.get('name') or '')}


def a_datadir_set(r):
    """Αλλαγή φακέλου δεδομένων. mode: copy (μεταφορά αντιγράφου εκεί), use (χρήση υπαρχόντων), default (Έγγραφα)."""
    if APP['source'] in ('env', 'shared'):
        raise ValueError('Ο φάκελος δεδομένων ορίζεται από το αρχείο shared_data_path.txt δίπλα στην εφαρμογή· αλλάξτε το εκεί.')
    mode = r.get('mode')
    old_root, old_source = paths().root, APP['source']
    if mode == 'default':
        new_root = storage.documents_dir() / storage.FOLDER_NAME
    else:
        new_root = Path((r.get('path') or '').strip())
        if not str(new_root) or not new_root.is_absolute():
            raise ValueError('Επιλέξτε φάκελο.')
    storage.check_writable(new_root)
    if new_root.resolve() == old_root.resolve():
        raise ValueError('Αυτός είναι ήδη ο φάκελος δεδομένων.')
    dst = storage.Paths(new_root)
    if mode == 'copy':
        storage.copy_tree_data(paths(), dst)
    elif mode == 'use':
        if not dst.db.exists() or not core.is_valid_database(dst.db):
            raise ValueError('Στον φάκελο δεν βρέθηκαν δεδομένα της εφαρμογής (data\\school_actions.db).')
    elif mode == 'default':
        if not dst.db.exists():
            storage.copy_tree_data(paths(), dst)
    else:
        raise ValueError('Άγνωστη επιλογή.')
    close_data()
    err = open_data(new_root, 'documents' if mode == 'default' else 'custom')
    if err:
        open_data(old_root, old_source)
        raise ValueError(err)
    cfg = storage.load_config()
    if mode == 'default':
        cfg.pop('data_dir', None)
    else:
        cfg['data_dir'] = str(new_root)
    storage.save_config(cfg)
    return state()


def a_update_online(r):
    info = updater.check_online()
    newer = bool(info) and updater.vtuple(info['version']) > updater.vtuple(core.VERSION)
    APP['update'] = info if newer else None
    cfg = storage.load_config(); cfg['last_update_check'] = date.today().isoformat(); storage.save_config(cfg)
    return {'current': core.VERSION, 'latest': info, 'newer': newer}


def a_update_check(r):
    man, files = updater.read(base64.b64decode(r['data']))
    return {'current': core.VERSION, 'version': man['version'], 'notes': man.get('notes', ''),
            'newer': updater.vtuple(man['version']) > updater.vtuple(core.VERSION),
            'same': updater.vtuple(man['version']) == updater.vtuple(core.VERSION)}


def a_update_backups(r):
    return {'current': core.VERSION, 'backups': updater.list_backups(ROOT)}


# ------------------------------------------------------------------ HTTP
ACTIONS = {
    'state': a_state, 'dashboard': a_dashboard,
    'actions/list': a_actions_list, 'actions/save': a_actions_save, 'actions/delete': a_actions_delete, 'actions/undelete': a_actions_undelete, 'actions/bulk': a_actions_bulk,
    'guide/list': a_guide_list, 'guide/save': a_guide_save, 'guide/delete': a_guide_delete, 'guide/reset': a_guide_reset, 'guide/create': a_guide_create,
    'import/preview': a_import_preview, 'import/apply': a_import_apply, 'template': a_template, 'export': a_export, 'report': a_report,
    'lifelog/status': a_lifelog_status, 'lifelog/setup': a_lifelog_setup, 'lifelog/unlock': a_lifelog_unlock, 'lifelog/lock': a_lifelog_lock,
    'lifelog/list': a_lifelog_list, 'lifelog/save': a_lifelog_save, 'lifelog/delete': a_lifelog_delete, 'lifelog/undelete': a_lifelog_undelete, 'lifelog/import/preview': a_lifelog_import_preview, 'lifelog/import/apply': a_lifelog_import_apply, 'lifelog/suggest': a_lifelog_suggest, 'lifelog/phrases': a_lifelog_phrases, 'lifelog/phrases/save': a_lifelog_phrases_save, 'lifelog/phrases/reset': a_lifelog_phrases_reset, 'lifelog/transfer': a_lifelog_transfer,
    'lifelog/report': a_lifelog_report, 'lifelog/settings': a_lifelog_settings,
    'backup/list': a_backup_list, 'backup/create': a_backup_create, 'backup/restore': a_backup_restore, 'backup/upload': a_backup_upload,
    'backup/download': a_backup_download, 'backup/current': a_backup_current, 'backup/settings': a_backup_settings,
    'backup/external-now': a_backup_external_now,
    'settings/save': a_settings_save, 'years/add': a_years_add, 'categories/save': a_categories_save,
    'open': a_open, 'fs/list': a_fs_list, 'fs/mkdir': a_fs_mkdir, 'datadir/set': a_datadir_set,
    'update/online': a_update_online, 'update/check': a_update_check, 'update/backups': a_update_backups,
}
STATIC = {'/logo.png': ('logo.png', 'image/png'), '/favicon.ico': ('app.ico', 'image/x-icon')}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, status, data, ctype='application/json; charset=utf-8'):
        b = data.encode('utf-8') if isinstance(data, str) else data
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(b)

    def valid_host(self):
        return self.headers.get('Host') == '127.0.0.1:' + str(self.server.server_port)

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, '{}')
        path = urlparse(self.path).path
        if path == '/':
            LAST_SEEN[0] = time.time(); BYE[0] = 0.0
            page = (SRC / 'index.html').read_text(encoding='utf-8').replace('__TOKEN__', TOKEN).replace('__VERSION__', core.VERSION)
            return self.send(200, page, 'text/html; charset=utf-8')
        if path == '/manual':
            page = (SRC / 'manual.html').read_text(encoding='utf-8').replace('__VERSION__', core.VERSION)
            return self.send(200, page, 'text/html; charset=utf-8')
        if path in STATIC:
            name, mime = STATIC[path]
            return self.send(200, (SRC / name).read_bytes(), mime)
        self.send(404, '{}')

    def do_POST(self):
        if not self.valid_host():
            return self.send(403, '{}')
        u = urlparse(self.path)
        if u.path == '/api/bye':  # κλείσιμο παραθύρου (το sendBeacon δεν στέλνει κεφαλίδες)
            if parse_qs(u.query).get('t', [''])[0] == TOKEN:
                BYE[0] = time.time()
            return self.send(200, '{}')
        if self.headers.get('X-App-Token') != TOKEN:
            return self.send(403, '{}')
        LAST_SEEN[0] = time.time(); BYE[0] = 0.0
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 <= length <= MAX_BODY:
                raise ValueError('Μη αποδεκτό μέγεθος αιτήματος (μέγιστο 30 MB).')
            req = json.loads(self.rfile.read(length) or b'{}')
            action = u.path[len('/api/'):] if u.path.startswith('/api/') else ''
            if action == 'ping':
                return self.send(200, '{}')
            if action == 'shutdown':
                self.send(200, '{}')
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if action == 'update/apply' or action == 'update/rollback':
                return self.update(action, req)
            fn = ACTIONS.get(action)
            if not fn:
                raise ValueError('Άγνωστη ενέργεια.')
            with LOCK:
                if not db():
                    raise ValueError('Τα δεδομένα δεν είναι διαθέσιμα.')
                out = fn(req)
            self.send(200, json.dumps(out, ensure_ascii=False))
        except PermissionError as ex:
            self.send(423, json.dumps({'error': str(ex), 'locked': True}, ensure_ascii=False))
        except Exception as ex:
            log('request error', self.path, repr(ex)[:400])
            msg = str(ex) if isinstance(ex, ValueError) else 'Απρόσμενο σφάλμα: ' + repr(ex)[:300]
            self.send(400, json.dumps({'error': msg}, ensure_ascii=False))

    def update(self, action, req):
        with LOCK:
            if action == 'update/apply' and req.get('online'):
                if not APP['update']:
                    raise ValueError('Δεν βρέθηκε νέα έκδοση· πατήστε πρώτα «Έλεγχος τώρα».')
                raw = updater.download(APP['update']['url'])
            elif action == 'update/apply':
                raw = base64.b64decode(req['data'])
            else:
                name = req.get('name', '')
                if not any(b['name'] == name for b in updater.list_backups(ROOT)):
                    raise ValueError('Άγνωστο αντίγραφο έκδοσης.')
                raw = (ROOT / 'versions' / name).read_bytes()
            man, files = updater.read(raw)
            updater.verify(files)
            if db():
                try:
                    storage.create_backup(db(), paths(), 'before_update')
                except Exception as ex:
                    log('backup before update failed', repr(ex))
            saved = updater.backup(ROOT, core.VERSION)
            updater.install(ROOT, files)
            log('updated', core.VERSION, '->', man['version'], 'backup', saved.name)
        self.send(200, json.dumps({'ok': True, 'version': man['version']}, ensure_ascii=False))

        def later(srv=self.server):
            time.sleep(0.6)
            with LOCK:
                close_data()
            updater.restart(ROOT, srv.server_port)
            srv.shutdown()
        threading.Thread(target=later, daemon=True).start()


# ------------------------------------------------------------------ παράθυρο εφαρμογής
def find_browser():
    if sys.platform != 'win32':
        return None
    cands = []
    for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'), os.environ.get('LOCALAPPDATA')):
        if base:
            cands += [Path(base) / 'Microsoft/Edge/Application/msedge.exe', Path(base) / 'Google/Chrome/Application/chrome.exe']
    for c in cands:
        if c.exists():
            return str(c)
    return shutil.which('msedge') or shutil.which('chrome')


def open_window(url):
    if '--no-browser' in sys.argv:
        return
    exe = find_browser()
    if exe:
        profile = storage.machine_dir() / 'window'
        try:
            profile.mkdir(parents=True, exist_ok=True)
            subprocess.Popen([exe, '--app=' + url, '--user-data-dir=' + str(profile), '--no-first-run', '--no-default-browser-check',
                              '--window-size=1400,900', '--lang=el', '--disable-features=Translate'], close_fds=True)
            return
        except OSError as ex:
            log('app window failed', repr(ex))
    webbrowser.open(url)


def watchdog(server):
    """Κλείνει την εφαρμογή λίγο μετά το κλείσιμο του παραθύρου (όχι σε ανανέωση σελίδας)."""
    while True:
        time.sleep(2)
        if BYE[0] and time.time() - BYE[0] > 20 and LAST_SEEN[0] < BYE[0]:
            log('window closed: exiting'); server.shutdown(); return
        if time.time() - LAST_SEEN[0] > 900:
            log('no window for 15 minutes: exiting'); server.shutdown(); return


def message_box(text, ask=False):
    log(text)
    if sys.platform == 'win32':
        try:
            import ctypes
            res = ctypes.windll.user32.MessageBoxW(0, text, core.APP_NAME, (0x04 | 0x30) if ask else 0x10)
            return res == 6
        except Exception:
            pass
    try:
        if ask:
            return input(text + '\n[ν/ο] ').strip().lower().startswith(('ν', 'y'))
        input(text + '\nEnter για έξοδο.')
    except Exception:
        pass
    return False


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else default


def housekeeping():
    while True:
        try:
            with LOCK:
                if db():
                    daily_backup()
        except Exception as ex:
            log('daily backup error', repr(ex)[:200])
        try:
            cfg = storage.load_config()
            with LOCK:
                enabled = db().get_bool('check_updates_on_startup', True) if db() else False
            if enabled and cfg.get('last_update_check') != date.today().isoformat() and not os.environ.get('PDS_NO_UPDATE_CHECK'):
                info = updater.check_online()
                APP['update'] = info if info and updater.vtuple(info['version']) > updater.vtuple(core.VERSION) else None
                cfg = storage.load_config(); cfg['last_update_check'] = date.today().isoformat(); storage.save_config(cfg)
                if APP['update']:
                    log('new version available', APP['update']['version'])
        except Exception as ex:
            log('update check failed', repr(ex)[:200])
        time.sleep(3600)


def main():
    mdir = storage.machine_dir()
    urlfile = mdir / 'app.url'
    restarted = '--restarted' in sys.argv
    handle = open(mdir / 'instance.lock', 'a+b')
    deadline = time.time() + (30 if restarted else 0)
    while True:
        try:
            handle.seek(0)
            if sys.platform == 'win32':
                import msvcrt; msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl; fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() < deadline:  # μετά από ενημέρωση: περιμένουμε να κλείσει η παλιά διεργασία
                time.sleep(0.3); continue
            try:  # ήδη ανοικτή σε αυτόν τον υπολογιστή: ανοίγουμε ξανά το παράθυρό της
                open_window(urlfile.read_text(encoding='utf-8').strip())
            except OSError:
                message_box('Η εφαρμογή είναι ήδη ανοικτή.')
            return
    root, source = storage.data_root()
    err = open_data(root, source)
    if err and source == 'custom' and 'άλλον υπολογιστή' not in err:
        if message_box(err + '\n\nΝα χρησιμοποιηθεί ο προεπιλεγμένος φάκελος (Έγγραφα) αυτή τη φορά;', ask=True):
            root, source = storage.documents_dir() / storage.FOLDER_NAME, 'documents'
            err = open_data(root, source)
    if err:
        handle.close()
        message_box(err)
        return
    port = int(arg('--port', 0) or 0)
    server = None
    for attempt in range(60):
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), Handler); break
        except OSError:
            if not port or attempt >= 58:
                port = 0
            time.sleep(0.5)
    url = 'http://127.0.0.1:' + str(server.server_port) + '/'
    try:
        urlfile.write_text(url, encoding='utf-8')
    except OSError:
        pass
    log(core.APP_NAME, core.VERSION, url, '(μετά από ενημέρωση)' if restarted else '')
    if not restarted or server.server_port != int(arg('--port', 0) or 0):
        open_window(url)
    LAST_SEEN[0] = time.time()
    threading.Thread(target=housekeeping, daemon=True).start()
    if '--stay' not in sys.argv and '--no-browser' not in sys.argv:
        threading.Thread(target=watchdog, args=(server,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        with LOCK:
            close_data()
        try:
            urlfile.unlink()
        except OSError:
            pass
        handle.close()


if __name__ == '__main__':
    main()
