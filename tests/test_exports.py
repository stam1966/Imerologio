"""Έλεγχοι εισαγωγής (CSV/XLSX) και εξαγωγών (CSV, Google, ICS) και αναφορών."""
import csv, io, sys, tempfile, unittest, zipfile
from pathlib import Path
SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))
import core, exports, reports


def xlsx_bytes(rows, date_cols=()):
    """Ελάχιστο .xlsx: πρώτη γραμμή κείμενα, οι αριθμοί ως αριθμοί· date_cols με στυλ ημερομηνίας."""
    def cell(ref, v, style=None):
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"{f" s=\"{style}\"" if style else ""}><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
    letters = 'ABCDEFGHIJKLMNOP'
    data = ''.join(f'<row r="{i+1}">' + ''.join(cell(f'{letters[j]}{i+1}', v, '1' if j in date_cols and i else None)
                                               for j, v in enumerate(r) if v != '') + '</row>' for i, r in enumerate(rows))
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Δράσεις" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/styles.xml', '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs count="3"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="20"/></cellXfs></styleSheet>')
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{data}</sheetData></worksheet>')
    return b.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = core.Database(Path(self.tmp.name) / 'school_actions.db')

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()


class Import(Base):
    def test_template_file(self):
        rows = exports.read_import('ypodeigma.xlsx', (SRC / 'templates' / 'ypodeigma_eisagogis_draseon.xlsx').read_bytes())
        plan = exports.plan_import(self.db, rows)
        self.assertGreaterEqual(len(plan['records']), 3)
        self.assertEqual(plan['errors'], [])
        internal = [r for r in plan['records'] if r['category'] == 'Εσωτερική Αξιολόγηση']
        self.assertTrue(internal and not internal[0]['export_google'] and not internal[0]['export_website'])

    def test_excel_dates_times_and_errors(self):
        raw = xlsx_bytes([['Ημερομηνία', 'Τίτλος', 'Ώρα έναρξης', 'Κατηγορία', 'κατάσταση'],
                          [46323, 'Από αριθμό Excel', 0.375, 'εθνικες επετειοι', 'ολοκληρωθηκε'],
                          ['2026-11-17', 'Πολυτεχνείο', '', 'Ανύπαρκτη', ''],
                          ['32/01/2026', 'Λάθος ημερομηνία', '', '', ''],
                          ['10/12/2026', '', '', '', '']], date_cols=(0,))
        plan = exports.plan_import(self.db, exports.read_import('a.xlsx', raw))
        recs = {r['title']: r for r in plan['records']}
        self.assertEqual(recs['Από αριθμό Excel']['action_date'], '2026-10-28')
        self.assertEqual(recs['Από αριθμό Excel']['start_time'], '09:00')
        self.assertEqual(recs['Από αριθμό Excel']['category'], 'Εθνικές Επέτειοι')
        self.assertEqual(recs['Από αριθμό Excel']['status'], 'Ολοκληρώθηκε')
        self.assertEqual(recs['Πολυτεχνείο']['category'], 'Άλλο')
        self.assertTrue(plan['warnings'])
        self.assertEqual(len(plan['errors']), 2)
        self.assertIn('Γραμμή 4', plan['errors'][0])

    def test_csv_roundtrip_and_duplicates(self):
        self.db.save_action({'action_date': '2026-10-28', 'title': 'Παρέλαση', 'start_time': '10:00', 'description': 'Με «εισαγωγικά», κόμμα\nκαι νέα γραμμή'})
        self.db.save_action({'action_date': '2026-10-20', 'title': 'Σχεδιασμός', 'category': 'Εσωτερική Αξιολόγηση'})
        data = exports.app_csv(self.db.list_actions())
        plan = exports.plan_import(self.db, exports.read_import('x.csv', data))
        self.assertEqual(len(plan['records']), 0)
        self.assertEqual(len(plan['duplicates']), 2)
        other = core.Database(Path(self.tmp.name) / 'other.db')
        plan = exports.plan_import(other, exports.read_import('x.csv', data))
        self.assertEqual(len(plan['records']), 2)
        other.insert_many(plan['records'])
        self.assertEqual({r['description'] for r in other.list_actions()} - {''}, {'Με «εισαγωγικά», κόμμα\nκαι νέα γραμμή'})
        other.close()

    def test_semicolon_cp1253_csv(self):
        text = 'ημερομηνια;τιτλος;ωρα\n01/12/2026;Δοκιμή;9:00\n'
        rows = exports.read_import('x.csv', text.encode('cp1253'))
        plan = exports.plan_import(self.db, rows)
        self.assertEqual(plan['records'][0]['start_time'], '09:00')

    def test_missing_columns(self):
        with self.assertRaises(ValueError):
            exports.read_import('x.csv', 'α,β\n1,2\n'.encode())


class Export(Base):
    def setUp(self):
        super().setUp()
        self.db.save_action({'action_date': '2026-10-28', 'title': 'Παρέλαση, 28η; \\ test', 'start_time': '10:00', 'location': 'Πλατεία',
                             'description': 'Πολύ μεγάλη περιγραφή ' * 12})
        self.db.save_action({'action_date': '2026-11-17', 'title': 'Πολυτεχνείο', 'export_google': False})
        self.db.save_action({'action_date': '2026-10-20', 'title': 'Συλλογικός', 'category': 'Εσωτερική Αξιολόγηση'})
        self.rows = self.db.list_actions()

    def test_ics(self):
        res = exports.export(self.db, 'ics', self.rows)
        self.assertEqual(res['count'], 2)  # χωρίς την εσωτερική
        text = res['data'].decode('utf-8')
        self.assertTrue(text.startswith('BEGIN:VCALENDAR\r\n'))
        self.assertNotIn('\n', text.replace('\r\n', ''))
        for line in text.split('\r\n'):
            self.assertLessEqual(len(line.encode('utf-8')), 75)
        unfolded = text.replace('\r\n ', '')
        self.assertIn('SUMMARY:Παρέλαση\\, 28η\\; \\\\ test', unfolded)
        self.assertIn('DTSTART;TZID=Europe/Athens:20261028T100000', unfolded)
        self.assertIn('DTEND;TZID=Europe/Athens:20261028T110000', unfolded)
        self.assertIn('DTSTART;VALUE=DATE:20261117', unfolded)
        self.assertIn('DTEND;VALUE=DATE:20261118', unfolded)
        ids = [r['id'] for r in self.rows if r['title'].startswith('Παρέλαση')]
        self.assertIn(f'UID:school-action-{ids[0]}@local', unfolded)
        self.assertEqual(len(res['pending_ids']), 2)

    def test_google_and_website(self):
        g = exports.export(self.db, 'google', self.rows)
        self.assertEqual(g['count'], 1)  # η μία δεν θέλει Google, η άλλη είναι εσωτερική
        rows = list(csv.reader(io.StringIO(g['data'].decode('utf-8-sig'))))
        self.assertEqual(rows[0][:3], ['Subject', 'Start Date', 'Start Time'])
        self.assertEqual(rows[1][1], '10/28/2026'); self.assertEqual(rows[1][4], '11:00'); self.assertEqual(rows[1][5], 'False')
        w = exports.export(self.db, 'website', self.rows)
        self.assertEqual(w['count'], 2)
        self.db.set_bool('enable_website_export', False)
        with self.assertRaises(ValueError):
            exports.export(self.db, 'website', self.rows)


class Reports(Base):
    def test_reports(self):
        self.db.set_current_school_year('2026-2027')
        self.db.save_action({'action_date': '2026-10-28', 'title': 'Παρέλαση <b>', 'status': 'Ολοκληρώθηκε'})
        self.db.save_action({'action_date': '2027-03-25', 'title': 'Μάρτιος'})
        self.db.save_action({'action_date': '2026-10-20', 'title': 'Συλλογικός', 'category': 'Εσωτερική Αξιολόγηση'})
        r = reports.actions_report(self.db, {'type': 'all', 'school_year': '2026-2027'})
        self.assertEqual(r['count'], 3)
        self.assertIn('Παρέλαση &lt;b&gt;', r['html']); self.assertIn('ΕΣΩΤΕΡΙΚΗΣ ΧΡΗΣΗΣ', r['html'])
        r = reports.actions_report(self.db, {'type': 'all_by_month', 'school_year': '2026-2027', 'from_month': '2026-10', 'to_month': '2026-10', 'include_internal': False})
        self.assertEqual(r['count'], 1); self.assertIn('Οκτώβριος 2026', r['html'])
        r = reports.actions_report(self.db, {'type': 'completed', 'school_year': '2026-2027'})
        self.assertEqual(r['count'], 1)
        r = reports.actions_report(self.db, {'type': 'by_category', 'school_year': '2026-2027'})
        self.assertGreaterEqual(r['count'], 1)
        r = reports.actions_report(self.db, {'type': 'by_category', 'school_year': '2026-2027', 'categories': ['Εσωτερική Αξιολόγηση']})
        self.assertEqual(r['count'], 1)
        with self.assertRaises(ValueError):
            reports.actions_report(self.db, {'type': 'all', 'school_year': '2026-2027', 'from_month': '2027-03', 'to_month': '2026-10'})
        r = reports.actions_report(self.db, {'type': 'filters', 'filters': {'search': 'μαρτιος', 'school_year': 'Όλα'}})
        self.assertEqual(r['count'], 1)
        r = reports.actions_report(self.db, {'type': 'guide', 'school_year': '2026-2027'})
        self.assertEqual(r['count'], len(core.DAY_GUIDE_ITEMS))
        self.db.lifelog_save({'log_date': '2026-10-28', 'description': 'Γραμμή 1\nΓραμμή 2'})
        r = reports.lifelog_report(self.db, self.db.lifelog_list(), toolbar=True)
        self.assertIn('Γραμμή 1<br>Γραμμή 2', r['html']); self.assertIn('window.print()', r['html'])


if __name__ == '__main__':
    unittest.main(verbosity=2)


def docx_bytes(rows):
    W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    def cell(v):
        return '<w:tc>' + ''.join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in (v.split('\n') if v else [''])) + '</w:tc>'
    body = '<w:tbl>' + ''.join('<w:tr>' + ''.join(cell(v) for v in r) + '</w:tr>' for r in rows) + '</w:tbl>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('word/document.xml', f'<w:document xmlns:w="{W}"><w:body><w:p/>{body}</w:body></w:document>')
    return b.getvalue()


class LifelogImport(Base):
    def test_docx_with_page_continuation_and_duplicates(self):
        raw = docx_bytes([['Ημερομηνία', 'Θέμα'], ['11/9/2024', 'Έγινε ο Αγιασμός.\nΣυνεδρίαση της ΕΔΥ.'],
                          ['20/2/2025', 'Προσήλθε η μητέρα της μαθήτριας με'], ['', 'αφορμή το πρόβλημα.'],
                          ['Ημερομηνία', 'Θέμα'], ['24/3/20266', 'Εκδήλωση 25ης Μαρτίου.'], ['1/9/2025', 'Έναρξη σχολικού έτους 2025-2026.']])
        p = exports.plan_lifelog_import(self.db, 'imerologio.docx', raw)
        self.assertEqual(p['count'], 3)
        self.assertEqual(p['records'][0]['description'], 'Έγινε ο Αγιασμός.\nΣυνεδρίαση της ΕΔΥ.')
        self.assertEqual(p['records'][1]['description'], 'Προσήλθε η μητέρα της μαθήτριας με αφορμή το πρόβλημα.')
        self.assertEqual(len(p['errors']), 1)
        self.assertEqual([y['year'] for y in p['years']], ['2024-2025', '2025-2026'])
        self.assertEqual(self.db.lifelog_insert_many(p['records']), 3)
        again = exports.plan_lifelog_import(self.db, 'imerologio.docx', raw)
        self.assertEqual((again['count'], again['duplicates']), (0, 3))

    def test_csv_and_xlsx_and_pdf(self):
        p = exports.plan_lifelog_import(self.db, 'a.csv', 'Ημερομηνία;Καταγραφή\n2/9/2024;Έναρξη.\n'.encode('utf-8'))
        self.assertEqual(p['count'], 1)
        p = exports.plan_lifelog_import(self.db, 'a.xlsx', xlsx_bytes([['Ημερομηνία', 'Περιγραφή'], [45546, 'Αγιασμός']], date_cols=(0,)))
        self.assertEqual(p['records'][0]['log_date'], '2024-09-11')
        with self.assertRaises(ValueError):
            exports.plan_lifelog_import(self.db, 'a.pdf', b'%PDF-1.4')

    def test_suggestions_from_previous_years(self):
        self.db.lifelog_insert_many([
            {'log_date': '2024-10-28', 'description': 'Παρέλαση στη Λαμία.\nΠραγματοποιήθηκε η 7η συνεδρίαση της ΕΔΥ.'},
            {'log_date': '2025-10-28', 'description': 'Παρέλαση στη Λαμία.'},
            {'log_date': '2025-10-31', 'description': 'Πραγματοποιήθηκε η 8η συνεδρίαση της ΕΔΥ.'},
            {'log_date': '2025-03-25', 'description': 'Δοξολογία.'},
            {'log_date': '2026-10-27', 'description': 'Φετινή καταγραφή.'}])
        s = self.db.lifelog_suggest('2026-10-28')
        texts = [i['text'] for i in s['items']]
        self.assertEqual(texts[0], 'Παρέλαση στη Λαμία.')
        self.assertEqual(s['items'][0]['times'], 2)
        self.assertEqual(sum('συνεδρίαση' in t for t in texts), 1)  # 7η/8η ενώνονται
        self.assertNotIn('Δοξολογία.', texts)
        self.assertNotIn('Φετινή καταγραφή.', texts)  # μόνο προηγούμενα σχολικά έτη
        self.assertEqual([i['text'] for i in self.db.lifelog_suggest('2026-10-28', 'δοξολογ')['items']], ['Δοξολογία.'])
        self.assertEqual(self.db.lifelog_years(), ['2024-2025', '2025-2026', '2026-2027'])


class Phrases(Base):
    def test_defaults_edit_reset(self):
        p = self.db.lifelog_phrases()
        self.assertFalse(p['customized'])
        self.assertGreaterEqual(len(p['items']), 60)
        self.assertEqual(p['items'][0]['text'], 'Έναρξη σχολικού έτους [σχολικό έτος].')
        self.assertTrue(all(i['group'] in p['groups'] for i in p['items']))
        q = self.db.set_lifelog_phrases([{'group': 'Συνεδριάσεις', 'text': '  Συνεδρίαση  ΕΔΥ. '}, {'group': '', 'text': 'Κάτι'},
                                         {'group': 'Συνεδριάσεις', 'text': 'Συνεδρίαση ΕΔΥ.'}, {'text': ''}])
        self.assertTrue(q['customized'])
        self.assertEqual(q['items'], [{'group': 'Συνεδριάσεις', 'text': 'Συνεδρίαση ΕΔΥ.'}, {'group': 'Άλλες', 'text': 'Κάτι'}])
        self.assertEqual(self.db.set_lifelog_phrases([])['items'], [])  # κενή λίστα είναι επιλογή του χρήστη
        self.assertFalse(self.db.reset_lifelog_phrases()['customized'])
