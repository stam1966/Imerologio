"""Έλεγχοι της τοπικής υπηρεσίας μέσω HTTP: ασφάλεια, δράσεις, Ημερολόγιο, αντίγραφα, φάκελος δεδομένων."""
import base64, json, os, shutil, sys, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
TMP = tempfile.mkdtemp(prefix='pds_test_')
os.environ['PDS_MACHINE_DIR'] = str(Path(TMP) / 'machine')
os.environ['PDS_NO_UPDATE_CHECK'] = '1'
import core, server, storage


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(TMP) / 'data1'
        err = server.open_data(cls.root, 'custom')
        assert err is None, err
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.url = f'http://127.0.0.1:{cls.httpd.server_port}'
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()
        server.close_data()
        shutil.rmtree(TMP, ignore_errors=True)

    def api(self, path, data=None, token=True, expect=200):
        req = urllib.request.Request(self.url + '/api/' + path, data=json.dumps(data or {}).encode(), method='POST',
                                     headers={'Content-Type': 'application/json', **({'X-App-Token': server.TOKEN} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                code, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read()
        self.assertEqual(code, expect, body[:300])
        return json.loads(body or b'{}')

    def test_01_security(self):
        self.api('state', token=False, expect=403)
        req = urllib.request.Request(self.url + '/', headers={'Host': 'evil.example:80'})
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(req, timeout=10)
        page = urllib.request.urlopen(self.url + '/', timeout=10).read().decode()
        self.assertIn(server.TOKEN, page); self.assertIn(core.VERSION, page)
        self.assertEqual(urllib.request.urlopen(self.url + '/logo.png', timeout=10).status, 200)
        self.assertIn('Οδηγός χρήσης', urllib.request.urlopen(self.url + '/manual', timeout=10).read().decode())
        self.assertIn('error', self.api('den-yparxei', expect=400))

    def test_02_state_and_actions(self):
        s = self.api('state')
        self.assertEqual(s['version'], core.VERSION)
        self.assertTrue(s['first_run'])
        a = self.api('actions/save', {'action': {'action_date': '2026-10-28', 'title': 'Παρέλαση', 'start_time': '10:00'}})
        b = self.api('actions/save', {'action': {'action_date': '2026-11-17', 'title': 'Πολυτεχνείο'}})
        self.assertFalse(self.api('state')['first_run'])
        rows = self.api('actions/list', {'filters': {'school_year': '2026-2027'}})['rows']
        self.assertEqual([r['title'] for r in rows], ['Παρέλαση', 'Πολυτεχνείο'])
        res = self.api('actions/bulk', {'ids': [a['id'], b['id']], 'status': 'Ολοκληρώθηκε'})
        self.assertEqual(res['updated'], 2)
        self.assertIn('ημερομηνία', self.api('actions/save', {'action': {'action_date': 'χθες', 'title': 'Χ'}}, expect=400)['error'])
        d = self.api('actions/delete', {'ids': [b['id']]})
        self.assertEqual(d['deleted'], 1); self.assertTrue(d['backup'].startswith('auto_prin_diagrafi'))
        self.assertTrue(any(x['name'] == d['backup'] for x in self.api('backup/list')['backups']))

    def test_03_guide_create(self):
        items = self.api('guide/list', {'school_year': '2026-2027'})['items'][:3]
        r = self.api('guide/create', {'school_year': '2026-2027', 'items': items})
        self.assertEqual(r['created'], 3)
        r = self.api('guide/create', {'school_year': '2026-2027', 'items': items})
        self.assertEqual((r['created'], r['skipped']), (0, 3))
        self.assertTrue(all(i['exists'] for i in self.api('guide/list', {'school_year': '2026-2027'})['items'][:3]))

    def test_04_lifelog_is_locked_server_side(self):
        self.assertTrue(self.api('lifelog/list', expect=423)['locked'])
        self.api('lifelog/setup', {'password': 'κωδ1234', 'confirm': 'κωδ1234'})
        self.api('lifelog/save', {'entry': {'log_date': '2026-10-28', 'description': 'Γιορτή'}})
        self.api('lifelog/lock')
        self.api('lifelog/list', expect=423)
        self.api('lifelog/report', expect=423)
        self.api('lifelog/setup', {'password': 'άλλος1', 'confirm': 'άλλος1'}, expect=423)  # δεν αλλάζει χωρίς ξεκλείδωμα
        self.api('lifelog/unlock', {'password': 'λάθος'}, expect=423)
        self.api('lifelog/unlock', {'password': 'κωδ1234'})
        self.assertEqual(len(self.api('lifelog/list')['rows']), 1)
        self.api('lifelog/lock')

    def test_05_import_export_report(self):
        csv_data = 'ημερομηνία,τίτλος,κατηγορία\n01/12/2026,Χριστουγεννιάτικη γιορτή,Σχολική Ζωή & Δράσεις\nλάθος,Χ,\n'.encode('utf-8')
        p = self.api('import/preview', {'name': 'a.csv', 'data': base64.b64encode(csv_data).decode()})
        self.assertEqual((p['count'], len(p['errors'])), (1, 1))
        r = self.api('import/apply', {'name': 'a.csv', 'data': base64.b64encode(csv_data).decode()})
        self.assertEqual(r['imported'], 1); self.assertTrue(r['backup'].startswith('auto_prin_eisagogi'))
        self.api('import/apply', {'name': 'a.csv', 'data': base64.b64encode(csv_data).decode()}, expect=400)  # μόνο διπλότυπα
        e = self.api('export', {'kind': 'ics', 'filters': {'school_year': 'Όλα'}})
        self.assertIn(b'BEGIN:VCALENDAR', base64.b64decode(e['data']))
        self.assertTrue(e['filename'].endswith('.ics'))
        t = self.api('template')
        self.assertTrue(base64.b64decode(t['data']).startswith(b'PK'))
        rep = self.api('report', {'options': {'type': 'all', 'school_year': '2026-2027'}})
        self.assertGreater(rep['count'], 0); self.assertIn('<table', rep['html'])

    def test_06_settings_categories_years(self):
        s = self.api('settings/save', {'school_name': '1ο Δημοτικό', 'features': {'enable_csv': False}})
        self.assertEqual(s['school_name'], '1ο Δημοτικό'); self.assertFalse(s['features']['enable_csv'])
        self.api('export', {'kind': 'app_csv', 'filters': {}}, expect=400)
        self.api('settings/save', {'features': {'enable_csv': True}})
        s = self.api('years/add', {'year': '2030-2031', 'make_current': True})
        self.assertEqual(s['current_school_year'], '2030-2031')
        self.api('years/add', {'year': '2030-2032'}, expect=400)
        self.api('settings/save', {'current_school_year': '2026-2027'})
        cats = s['categories']
        self.api('categories/save', {'categories': cats[:-1] + ['Νέα'] + cats[-1:], 'config': s['category_config']})
        self.assertIn('Νέα', self.api('state')['categories'])
        self.api('categories/save', {'categories': ['Α', 'Α']}, expect=400)

    def test_07_backup_restore_upload(self):
        n = len(self.api('actions/list', {'filters': {'school_year': 'Όλα'}})['rows'])
        name = self.api('backup/create')['name']
        self.api('actions/save', {'action': {'action_date': '2027-01-30', 'title': 'Μετά το αντίγραφο'}})
        r = self.api('backup/restore', {'name': name})
        self.assertEqual(r['count'], n); self.assertTrue(r['safety'].startswith('before_restore'))
        self.api('backup/restore', {'name': '../../etc/passwd'}, expect=400)
        cur = base64.b64decode(self.api('backup/current')['data'])
        self.assertTrue(cur.startswith(b'SQLite format 3'))
        self.api('backup/upload', {'name': 'x.db', 'data': base64.b64encode(b'not a database').decode()}, expect=400)
        self.assertEqual(self.api('backup/upload', {'name': 'x.db', 'data': base64.b64encode(cur).decode()})['count'], n)

    def test_08_change_data_folder(self):
        old = Path(self.api('state')['data']['root'])
        new = Path(TMP) / 'Κοινόχρηστος'
        s = self.api('datadir/set', {'path': str(new), 'mode': 'copy'})
        self.assertEqual(Path(s['data']['root']), new)
        self.assertTrue((new / 'data' / 'school_actions.db').exists())
        self.assertEqual(storage.load_config()['data_dir'], str(new))
        # δεύτερη «εγκατάσταση» δεν μπορεί να ανοίξει τα ίδια δεδομένα όσο είναι ανοιχτά
        lock = storage.DataLock(new)
        self.assertFalse(lock.acquire())
        self.assertIn('(', lock.holder())
        # επιστροφή στα παλιά δεδομένα (υπάρχουν ήδη)
        s = self.api('datadir/set', {'path': str(old), 'mode': 'use'})
        self.assertEqual(Path(s['data']['root']), old)
        self.api('datadir/set', {'path': str(Path(TMP) / 'κενός'), 'mode': 'use'}, expect=400)
        lock2 = storage.DataLock(new)
        self.assertTrue(lock2.acquire()); lock2.release()

    def test_09_folder_browser(self):
        j = self.api('fs/list', {'path': TMP})
        self.assertTrue(j['writable'])
        p = self.api('fs/mkdir', {'parent': TMP, 'name': 'Νέος φάκελος'})['path']
        self.assertTrue(Path(p).is_dir())
        self.api('fs/mkdir', {'parent': TMP, 'name': 'κακό:όνομα'}, expect=400)
        ext = Path(TMP) / 'usb'; ext.mkdir()
        r = self.api('backup/settings', {'folder': str(ext)})
        self.assertTrue(r['written'] and Path(r['written']).exists())
        self.api('backup/settings', {'folder': ''})


if __name__ == '__main__':
    unittest.main(verbosity=2)
