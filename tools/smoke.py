"""Έλεγχος λειτουργίας σε Windows με το πραγματικό runtime (εκτελείται στο GitHub Actions):
εκκίνηση της τοπικής υπηρεσίας σε προσωρινό φάκελο δεδομένων, άνοιγμα σελίδας, κλήσεις API, κλείσιμο."""
import base64, json, os, re, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tmp = Path(tempfile.mkdtemp(prefix='pds_smoke_'))
env = dict(os.environ, PDS_DATA_DIR=str(tmp / 'Δεδομένα σχολείου'), PDS_MACHINE_DIR=str(tmp / 'machine'), PDS_NO_UPDATE_CHECK='1')
print('==> server start', sys.executable, flush=True)
proc = subprocess.Popen([sys.executable, '-X', 'utf8', str(ROOT / 'src' / 'server.py'), '--no-browser', '--stay'], cwd=str(ROOT), env=env)
try:
    url = None
    for _ in range(60):
        time.sleep(0.5)
        f = tmp / 'machine' / 'app.url'
        if f.exists():
            url = f.read_text(encoding='utf-8').strip(); break
    assert url, 'server did not start'
    page = urllib.request.urlopen(url, timeout=10).read().decode('utf-8')
    token = re.search(r"const token='([^']+)'", page).group(1)

    def api(path, data=None):
        req = urllib.request.Request(url + 'api/' + path, data=json.dumps(data or {}).encode(), method='POST',
                                     headers={'X-App-Token': token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    s = api('state'); print('state', s['version'], s['data'])
    assert s['first_run']
    items = api('guide/list', {'school_year': s['current_school_year']})['items']
    print('guide created', api('guide/create', {'school_year': s['current_school_year'], 'items': items})['created'])
    api('actions/save', {'action': {'action_date': '2026-10-28', 'title': 'Δοκιμή «ελληνικών», ώρα', 'start_time': '10:00'}})
    rows = api('actions/list', {'filters': {'school_year': 'Όλα', 'search': 'δοκιμη'}})['rows']
    assert len(rows) == 1, rows
    for kind in ('app_csv', 'website', 'google', 'ics'):
        e = api('export', {'kind': kind, 'filters': {'school_year': 'Όλα'}}); assert base64.b64decode(e['data'])
    rep = api('report', {'options': {'type': 'all_by_month', 'school_year': s['current_school_year']}}); assert rep['count'] > 0
    name = api('backup/create')['name']; print('backup', name)
    assert (Path(env['PDS_DATA_DIR']) / 'backups' / name).exists()
    api('lifelog/setup', {'password': 'δοκιμή1', 'confirm': 'δοκιμή1'})
    api('lifelog/save', {'entry': {'log_date': '2026-10-28', 'description': 'Καταγραφή'}})
    assert (Path(env['PDS_DATA_DIR']) / 'data' / 'school_actions.db').exists()
    print('server OK', url)
    api('shutdown')
    proc.wait(timeout=20)
    assert not (Path(env['PDS_DATA_DIR']) / 'app.lock.info').exists(), 'lock info not cleaned'
finally:
    if proc.poll() is None:
        proc.terminate()
print('SMOKE OK')
