"""Έλεγχοι πυρήνα: βάση, μετάβαση από v1.7, κανόνες κατηγοριών, σχολικά έτη, Οδηγός, Ημερολόγιο."""
import os, sys, sqlite3, tempfile, unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import core

OLD_SCHEMA = """
CREATE TABLE actions (id INTEGER PRIMARY KEY AUTOINCREMENT, action_date TEXT NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL,
 start_time TEXT, end_time TEXT, class_group TEXT, location TEXT, status TEXT NOT NULL DEFAULT 'Προγραμματισμένη',
 calendar_flag TEXT NOT NULL DEFAULT 'Δεν περάστηκε', description TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO settings VALUES ('school_name', 'Δοκιμαστικό Σχολείο'), ('life_log_password', 'μυστικό1'),
 ('categories', 'Εθνικές Επέτειοι\nΠεριβάλλον\nΆλλο');
INSERT INTO actions(action_date,title,category,status,calendar_flag,created_at,updated_at) VALUES
 ('2025-10-28','Γιορτή','Εθνικές Επέτειοι & Σχολικές Εορτές','Ολοκληρώθηκε','Περάστηκε','x','x'),
 ('2026-03-22','Νερό','Περιβάλλον','Προγραμματισμένη','Δεν περάστηκε','x','x'),
 ('2026-01-10','Άγνωστη','Κάτι παλιό','Προγραμματισμένη','Δεν περάστηκε','x','x');
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'school_actions.db'
        self.dbs = []

    def tearDown(self):
        for d in self.dbs:
            d.close()
        self.tmp.cleanup()

    def open(self):
        self.dbs.append(core.Database(self.path))
        return self.dbs[-1]


class Migration(Base):
    def test_old_v17_database(self):
        con = sqlite3.connect(self.path); con.executescript(OLD_SCHEMA); con.commit(); con.close()
        db = self.open()
        rows = {r['title']: r for r in db.list_actions()}
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows['Γιορτή']['category'], 'Εθνικές Επέτειοι')
        self.assertEqual(rows['Νερό']['category'], 'Σχολική Ζωή & Δράσεις')
        self.assertEqual(rows['Άγνωστη']['category'], 'Άλλο')
        self.assertEqual(rows['Γιορτή']['school_year'], '2025-2026')
        self.assertEqual(rows['Νερό']['school_year'], '2025-2026')
        self.assertTrue(rows['Γιορτή']['export_google'])
        # ο κωδικός δεν μένει ως απλό κείμενο
        self.assertEqual(db.get_setting('life_log_password'), '')
        self.assertTrue(db.lifelog_has_password())
        self.assertTrue(db.lifelog_check('μυστικό1'))
        self.assertFalse(db.lifelog_check('λάθος'))
        self.assertIn('2025-2026', db.school_years())
        self.assertEqual(db.school_name(), 'Δοκιμαστικό Σχολείο')
        self.assertEqual(len(db.guide_items()), len(core.DAY_GUIDE_ITEMS))
        db.close()
        self.assertTrue(core.is_valid_database(self.path))

    def test_not_a_database(self):
        p = Path(self.tmp.name) / 'x.db'
        p.write_bytes(b'hello')
        self.assertFalse(core.is_valid_database(p))
        con = sqlite3.connect(Path(self.tmp.name) / 'y.db'); con.execute('CREATE TABLE z(a)'); con.close()
        self.assertFalse(core.is_valid_database(Path(self.tmp.name) / 'y.db'))


class Categories(Base):
    def test_order_and_deleted_defaults_survive_restart(self):
        db = self.open()
        cats = db.categories()
        self.assertEqual(cats[-1], 'Άλλο')
        new = ['Εθνικές Επέτειοι', 'Δικά μας'] + [c for c in cats if c not in ('Εθνικές Επέτειοι', 'Θεσμοθετημένες Σχολικές Ημέρες', 'Άλλο')]
        db.save_categories(new)
        db.close()
        db = self.open()
        self.assertEqual(db.categories()[:2], ['Εθνικές Επέτειοι', 'Δικά μας'])
        self.assertNotIn('Θεσμοθετημένες Σχολικές Ημέρες', db.categories())  # δεν ξαναεμφανίζεται
        db.close()

    def test_rename_and_remove_move_actions(self):
        db = self.open()
        a = db.save_action({'action_date': '2026-11-02', 'title': 'Α', 'category': 'Εθνικές Επέτειοι'})
        b = db.save_action({'action_date': '2026-11-03', 'title': 'Β', 'category': 'Ενημέρωση & Οργάνωση'})
        cats = [c for c in db.categories() if c != 'Ενημέρωση & Οργάνωση']
        cats[cats.index('Εθνικές Επέτειοι')] = 'Επέτειοι'
        db.save_categories(cats, renames={'Εθνικές Επέτειοι': 'Επέτειοι'})
        self.assertEqual(db.get_action(a)['category'], 'Επέτειοι')
        self.assertEqual(db.get_action(b)['category'], 'Άλλο')

    def test_internal_rules(self):
        db = self.open()
        aid = db.save_action({'action_date': '2026-10-20', 'title': 'Συλλογικός', 'category': 'Εσωτερική Αξιολόγηση',
                              'export_google': True, 'export_website': True, 'calendar_flag': 'Περάστηκε'})
        r = db.get_action(aid)
        self.assertFalse(r['export_google']); self.assertFalse(r['export_website'])
        self.assertEqual(r['calendar_flag'], 'Δεν περάστηκε'); self.assertTrue(r['internal'])
        res = db.bulk_update([aid], calendar_flag='Περάστηκε')
        self.assertEqual(res, {'updated': 0, 'skipped': 1})
        # δεν μπορεί να γίνει «εξαγώγιμη» η Εσωτερική Αξιολόγηση
        cfg = db.category_config(); cfg['Εσωτερική Αξιολόγηση'].update(google=True, website=True, internal=False)
        db.save_categories(db.categories(), cfg)
        c = db.category_config()['Εσωτερική Αξιολόγηση']
        self.assertTrue(c['internal']); self.assertFalse(c['google']); self.assertFalse(c['website'])

    def test_category_disable_updates_existing(self):
        db = self.open()
        aid = db.save_action({'action_date': '2026-11-02', 'title': 'Α', 'category': 'Εθνικές Επέτειοι'})
        cfg = db.category_config(); cfg['Εθνικές Επέτειοι']['website'] = False
        db.save_categories(db.categories(), cfg)
        self.assertFalse(db.get_action(aid)['export_website'])


class Actions(Base):
    def test_validation_and_years(self):
        db = self.open()
        with self.assertRaises(ValueError):
            db.save_action({'action_date': '2026-11-02', 'title': ' '})
        with self.assertRaises(ValueError):
            db.save_action({'action_date': '31/02/2026', 'title': 'Χ'})
        with self.assertRaises(ValueError):
            db.save_action({'action_date': '2026-11-02', 'title': 'Χ', 'start_time': '25:00'})
        with self.assertRaises(ValueError):
            db.save_action({'action_date': '2026-11-02', 'title': 'Χ', 'start_time': '10:00', 'end_time': '09:00'})
        aid = db.save_action({'action_date': '15/03/2031', 'title': 'Μέλλον', 'start_time': '9.30'})
        r = db.get_action(aid)
        self.assertEqual((r['action_date'], r['start_time'], r['school_year'], r['category']), ('2031-03-15', '09:30', '2030-2031', core.DEFAULT_ACTION_CATEGORY))
        self.assertIn('2030-2031', db.school_years())

    def test_search_ignores_accents_and_case(self):
        db = self.open()
        db.save_action({'action_date': '2026-09-11', 'title': 'Αγιασμός - Έναρξη', 'location': 'Αυλή'})
        db.save_action({'action_date': '2026-09-12', 'title': 'Άλλο θέμα'})
        self.assertEqual(len(db.list_actions({'search': 'αγιασμος'})), 1)
        self.assertEqual(len(db.list_actions({'search': 'ΕΝΑΡΞΗ αυλη'})), 1)
        self.assertEqual(len(db.list_actions({'search': 'θεμα'})), 1)

    def test_filters_and_dashboard(self):
        db = self.open()
        today = date.today()
        db.save_action({'action_date': (today - timedelta(days=3)).isoformat(), 'title': 'Παλιά'})
        db.save_action({'action_date': today.isoformat(), 'title': 'Σήμερα'})
        db.save_action({'action_date': (today + timedelta(days=5)).isoformat(), 'title': 'Σύντομα'})
        c = db.save_action({'action_date': (today + timedelta(days=6)).isoformat(), 'title': 'Ακυρωμένη', 'status': 'Ακυρώθηκε'})
        d = db.dashboard()
        self.assertEqual((d['total'], d['today'], d['overdue'], d['upcoming'], d['cancelled']), (4, 1, 1, 2, 1))
        self.assertEqual([r['title'] for r in db.list_actions({'overdue': True})], ['Παλιά'])
        self.assertEqual(len(db.list_actions({'status': 'Ακυρώθηκε'})), 1)
        self.assertEqual(db.delete_actions([c]), 1)
        self.assertTrue(db.action_exists(today.isoformat(), 'σήμερα'))  # χωρίς διάκριση πεζών (και ελληνικά)

    def test_backup_api(self):
        db = self.open()
        db.save_action({'action_date': '2026-11-02', 'title': 'Α'})
        target = Path(self.tmp.name) / 'copy.db'
        db.backup_to(target)
        self.assertTrue(core.is_valid_database(target))
        copy = core.Database(target)
        self.assertEqual(len(copy.list_actions()), 1)
        copy.close()


class Guide(Base):
    def test_dates_by_school_year(self):
        item = {'day': 28, 'month': 10, 'title': 'Χ'}
        self.assertEqual(core.guide_item_iso_date(item, '2026-2027'), '2026-10-28')
        self.assertEqual(core.guide_item_iso_date({'day': 25, 'month': 3, 'title': 'Χ'}, '2026-2027'), '2027-03-25')
        self.assertEqual(core.guide_item_iso_date({'day': 29, 'month': 2, 'title': 'Χ'}, '2026-2027'), '2027-02-28')
        self.assertEqual(core.guide_item_iso_date({'day': 29, 'month': 2, 'title': 'Χ'}, '2027-2028'), '2028-02-29')

    def test_edit_delete_reset_persist(self):
        db = self.open()
        n = len(db.guide_items())
        first = db.guide_items()[0]
        db.delete_guide_item(first)
        db.save_guide_item({'day': 3, 'month': 11, 'title': 'Δική μας ημέρα', 'category': 'Νέα κατηγορία'})
        self.assertIn('Νέα κατηγορία', db.categories())
        with self.assertRaises(ValueError):
            db.save_guide_item({'day': 3, 'month': 11, 'title': 'Δική μας ημέρα', 'category': 'Άλλο'})
        with self.assertRaises(ValueError):
            db.save_guide_item({'day': 31, 'month': 11, 'title': 'Λάθος'})
        db.close()
        db = self.open()  # η διαγραφή προτεινόμενης ημέρας δεν αναιρείται στην επανεκκίνηση
        titles = [g['title'] for g in db.guide_items()]
        self.assertNotIn(first['title'], titles)
        self.assertIn('Δική μας ημέρα', titles)
        self.assertEqual(len(titles), n)
        db.reset_guide()
        self.assertEqual(len(db.guide_items()), n)
        self.assertIn(first['title'], [g['title'] for g in db.guide_items()])


class LifeLog(Base):
    def test_password_and_transfer(self):
        db = self.open()
        self.assertFalse(db.lifelog_has_password())
        with self.assertRaises(ValueError):
            db.lifelog_set_password('12')
        db.lifelog_set_password('κωδικός')
        self.assertTrue(db.lifelog_check('κωδικός'))
        self.assertNotIn('κωδικός', db.get_setting('life_log_password_hash'))
        db.save_action({'action_date': '2026-10-28', 'title': 'Παρέλαση', 'status': 'Ολοκληρώθηκε', 'class_group': 'Ε΄', 'start_time': '10:00'})
        db.save_action({'action_date': '2026-10-29', 'title': 'Μελλοντική'})
        self.assertEqual(db.lifelog_transfer_completed(), 1)
        self.assertEqual(db.lifelog_transfer_completed(), 0)
        rows = db.lifelog_list()
        self.assertIn('«Παρέλαση»', rows[0]['description']); self.assertIn('Ε΄', rows[0]['description'])
        lid = db.lifelog_save({'log_date': '27/10/2026', 'description': 'Επίσκεψη γονέων'})
        self.assertEqual([r['log_date'] for r in db.lifelog_list()], ['2026-10-27', '2026-10-28'])
        self.assertEqual(len(db.lifelog_list('ΓΟΝΕΩΝ')), 1)
        self.assertEqual(len(db.lifelog_list(date_from='2026-10-28')), 1)
        db.lifelog_delete([lid])
        self.assertEqual(len(db.lifelog_list()), 1)


class Helpers(unittest.TestCase):
    def test_years(self):
        self.assertEqual(core.school_year_of(date(2026, 9, 1)), '2026-2027')
        self.assertEqual(core.school_year_of(date(2027, 8, 31)), '2026-2027')
        self.assertTrue(core.valid_school_year_label('2026-2027'))
        self.assertFalse(core.valid_school_year_label('2026-2028'))
        self.assertEqual(core.school_year_months('2026-2027')[0], '2026-09')
        self.assertEqual(core.school_year_months('2026-2027')[-1], '2027-08')

    def test_parse(self):
        self.assertEqual(core.parse_date_to_iso('5/3/2027'), '2027-03-05')
        self.assertEqual(core.parse_date_to_iso('2027-03-05'), '2027-03-05')
        self.assertEqual(core.parse_date_to_iso('05.03.2027'), '2027-03-05')
        self.assertEqual(core.normalize_time('0930'), '09:30')
        self.assertEqual(core.normalize_time('09:30:00'), '09:30')
        self.assertEqual(core.fold('Άγιος ΪΣΤΟΣ'), 'αγιοσ ιστοσ')


if __name__ == '__main__':
    unittest.main(verbosity=2)
