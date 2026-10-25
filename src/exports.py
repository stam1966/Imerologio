"""Εισαγωγή δράσεων από CSV/XLSX και εξαγωγές (CSV εφαρμογής, πίνακας ιστοσελίδας,
Google Calendar CSV, ICS). Μόνο βασική βιβλιοθήκη της Python."""
from __future__ import annotations

import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import core

# ------------------------------------------------------------------ επικεφαλίδες
HEADER_ALIASES = {
    'ημερομηνία': 'action_date', 'ημερομηνια': 'action_date', 'date': 'action_date', 'actiondate': 'action_date',
    'τίτλος': 'title', 'τιτλος': 'title', 'title': 'title', 'δράση': 'title', 'δραση': 'title', 'τίτλοςδράσης': 'title', 'τιτλοςδρασης': 'title', 'subject': 'title',
    'περιγραφή': 'description', 'περιγραφη': 'description', 'description': 'description', 'σύντομηπεριγραφή': 'description', 'συντομηπεριγραφη': 'description',
    'τάξητμήμα': 'class_group', 'ταξητμημα': 'class_group', 'τάξη': 'class_group', 'ταξη': 'class_group', 'τμήμα': 'class_group', 'τμημα': 'class_group', 'class': 'class_group', 'classgroup': 'class_group',
    'ώραέναρξης': 'start_time', 'ωραεναρξης': 'start_time', 'starttime': 'start_time', 'start': 'start_time', 'ώρα': 'start_time', 'ωρα': 'start_time',
    'ώραλήξης': 'end_time', 'ωραληξης': 'end_time', 'endtime': 'end_time', 'end': 'end_time',
    'κατηγορία': 'category', 'κατηγορια': 'category', 'category': 'category',
    'τοποθεσία': 'location', 'τοποθεσια': 'location', 'location': 'location', 'χώρος': 'location', 'χωρος': 'location',
    'κατάσταση': 'status', 'κατασταση': 'status', 'status': 'status',
    'calendar': 'calendar_flag', 'ημερολόγιο': 'calendar_flag', 'ημερολογιο': 'calendar_flag',
    'exportgoogle': 'export_google', 'εξαγωγήgoogle': 'export_google', 'εξαγωγηgoogle': 'export_google', 'googlecalendar': 'export_google',
    'exportwebsite': 'export_website', 'εξαγωγήιστοσελίδας': 'export_website', 'εξαγωγηιστοσελιδας': 'export_website', 'ιστοσελίδα': 'export_website', 'ιστοσελιδα': 'export_website',
}


def normalize_header(value: str) -> str:
    key = re.sub(r'[\s_/\-\.]+', '', (value or '').strip().lower())
    return HEADER_ALIASES.get(key, HEADER_ALIASES.get(core.fold(key), key))


# ------------------------------------------------------------------ ανάγνωση αρχείων
def read_csv(raw: bytes) -> list[dict]:
    text = None
    for enc in ('utf-8-sig', 'utf-8', 'cp1253'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError('Δεν ήταν δυνατή η ανάγνωση του CSV (άγνωστη κωδικοποίηση).')
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text, newline=''), dialect)
    matrix = [row for row in reader]
    return _rows_from_matrix(matrix)


NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
RNS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def _col_index(ref: str) -> int:
    col = 0
    for ch in ref:
        if ch.isalpha():
            col = col * 26 + (ord(ch.upper()) - 64)
    return col - 1


def read_xlsx(raw: bytes) -> list[dict]:
    """Ανάγνωση του πρώτου φύλλου ενός .xlsx (κείμενα, αριθμοί, ημερομηνίες/ώρες του Excel)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = z.namelist()
        shared = []
        if 'xl/sharedStrings.xml' in names:
            for si in ET.fromstring(z.read('xl/sharedStrings.xml')).iter(NS + 'si'):
                shared.append(''.join(t.text or '' for t in si.iter(NS + 't')))
        sheet = 'xl/worksheets/sheet1.xml'
        try:  # το πρώτο φύλλο κατά σειρά στο βιβλίο εργασίας
            wb = ET.fromstring(z.read('xl/workbook.xml'))
            first = next(wb.iter(NS + 'sheet'))
            rid = first.get(RNS + 'id')
            rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
            for rel in rels:
                if rel.get('Id') == rid:
                    target = rel.get('Target').lstrip('/')
                    sheet = target if target.startswith('xl/') else 'xl/' + target
        except Exception:
            pass
        if sheet not in names:
            sheet = sorted(n for n in names if n.startswith('xl/worksheets/sheet'))[0]
        date_styles = _date_styles(z) if 'xl/styles.xml' in names else set()
        root = ET.fromstring(z.read(sheet))
    except (zipfile.BadZipFile, KeyError, IndexError, ET.ParseError) as ex:
        raise ValueError('Δεν ήταν δυνατή η ανάγνωση του XLSX. Αποθηκεύστε το ως απλό .xlsx ή CSV. (' + str(ex)[:80] + ')')
    matrix = []
    for row in root.iter(NS + 'row'):
        values = []
        for c in row.findall(NS + 'c'):
            idx = _col_index(c.get('r', '')) if c.get('r') else len(values)
            while len(values) < idx:
                values.append('')
            t = c.get('t')
            v = c.find(NS + 'v')
            if t == 'inlineStr':
                val = ''.join(x.text or '' for x in c.iter(NS + 't'))
            elif v is None or v.text is None:
                val = ''
            elif t == 's':
                try:
                    val = shared[int(v.text)]
                except (ValueError, IndexError):
                    val = ''
            elif t in ('str', 'e'):
                val = v.text
            elif t == 'b':
                val = '1' if v.text == '1' else '0'
            else:
                val = _excel_number(v.text, c.get('s'), date_styles)
            values.append(val.strip())
        matrix.append(values)
    return _rows_from_matrix(matrix)


def _date_styles(z) -> set:
    """Δείκτες στυλ κελιών που μορφοποιούνται ως ημερομηνία/ώρα."""
    root = ET.fromstring(z.read('xl/styles.xml'))
    custom = {}
    nf = root.find(NS + 'numFmts')
    if nf is not None:
        for f in nf:
            custom[f.get('numFmtId')] = f.get('formatCode', '')
    out = set()
    xfs = root.find(NS + 'cellXfs')
    for i, xf in enumerate(xfs if xfs is not None else []):
        fid = xf.get('numFmtId', '0')
        code = custom.get(fid, '')
        builtin_date = fid.isdigit() and (14 <= int(fid) <= 22 or 45 <= int(fid) <= 47)
        if builtin_date or (code and re.search(r'[dmyhs]', re.sub(r'"[^"]*"|\[[^\]]*\]', '', code), re.I)):
            out.add(str(i))
    return out


def _excel_number(text: str, style, date_styles) -> str:
    try:
        num = float(text)
    except ValueError:
        return text
    if style in date_styles:
        if 0 <= num < 1:  # μόνο ώρα
            minutes = round(num * 24 * 60)
            return f'{minutes // 60:02d}:{minutes % 60:02d}'
        d = datetime(1899, 12, 30) + timedelta(days=num)
        return d.strftime('%d/%m/%Y') if abs(num - int(num)) < 1e-9 else d.strftime('%d/%m/%Y %H:%M')
    return str(int(num)) if num == int(num) else text


def _rows_from_matrix(matrix) -> list[dict]:
    matrix = [r for r in matrix if any((x or '').strip() for x in r)]
    if not matrix:
        return []
    headers = [normalize_header(h) for h in matrix[0]]
    if 'title' not in headers or 'action_date' not in headers:
        raise ValueError('Δεν βρέθηκαν οι υποχρεωτικές στήλες «ημερομηνία» και «τίτλος» στην πρώτη γραμμή του αρχείου.')
    rows = []
    for n, raw in enumerate(matrix[1:], start=2):
        item = {'_line': n}
        for i, h in enumerate(headers):
            if h and h not in item:
                item[h] = (raw[i] if i < len(raw) else '').strip()
        rows.append(item)
    return rows


def read_import(name: str, raw: bytes) -> list[dict]:
    suffix = (name or '').lower().rsplit('.', 1)[-1]
    if suffix == 'xls':
        raise ValueError('Η παλιά μορφή .xls δεν υποστηρίζεται. Αποθηκεύστε το αρχείο ως .xlsx ή CSV.')
    if suffix == 'xlsx' or raw[:2] == b'PK':
        return read_xlsx(raw)
    return read_csv(raw)


def excel_time(value: str) -> str:
    """Ώρα που ήρθε ως κλάσμα ημέρας του Excel (π.χ. 0.375 = 09:00) χωρίς μορφοποίηση ώρας."""
    v = (value or '').strip()
    if re.fullmatch(r'0?\.\d+', v):
        minutes = round(float(v) * 24 * 60)
        return f'{minutes // 60:02d}:{minutes % 60:02d}'
    if re.fullmatch(r'\d{1,2}:\d{2}:\d{2}', v):
        return v[:-3]
    return v


def parse_bool(value: str, default: bool) -> bool:
    v = core.fold(value or '')
    if not v:
        return default
    if v in {'1', 'true', 'yes', 'y', 'ναι', 'nai', 'ν'}:
        return True
    if v in {'0', 'false', 'no', 'n', 'οχι', 'oxi', 'ο'}:
        return False
    return default


def match_choice(value: str, choices, default: str) -> str:
    v = core.fold(value or '')
    if not v:
        return default
    for c in choices:
        if core.fold(c) == v:
            return c
    return ''


def plan_import(db: core.Database, rows: list[dict]) -> dict:
    """Ελέγχει τις γραμμές χωρίς να αλλάξει τίποτα. Επιστρέφει έγκυρες εγγραφές,
    διπλότυπα και σφάλματα ανά γραμμή, για προεπισκόπηση πριν από την εισαγωγή."""
    cats = db.categories()
    skip_dup = db.get_bool('skip_duplicate_imports', True)
    records, errors, duplicates, warnings = [], [], [], []
    seen = set()
    for row in rows:
        n = row.get('_line', '?')
        title = (row.get('title') or '').strip()
        if not title and not (row.get('action_date') or '').strip():
            continue
        try:
            if not title:
                raise ValueError('λείπει ο τίτλος.')
            try:
                action_date = core.parse_date_to_iso((row.get('action_date') or '').split(' ')[0])
            except ValueError:
                raise ValueError('η ημερομηνία πρέπει να είναι ΗΗ/ΜΜ/ΕΕΕΕ ή ΕΕΕΕ-ΜΜ-ΗΗ.')
            try:
                start = core.normalize_time(excel_time(row.get('start_time', '')))
                end = core.normalize_time(excel_time(row.get('end_time', '')))
            except ValueError:
                raise ValueError('οι ώρες πρέπει να είναι ΩΩ:ΛΛ.')
            category = match_choice(row.get('category', ''), cats, core.DEFAULT_ACTION_CATEGORY if core.DEFAULT_ACTION_CATEGORY in cats else cats[0])
            if not category:
                warnings.append(f'Γραμμή {n}: η κατηγορία «{row.get("category")}» δεν υπάρχει· μπαίνει στο «Άλλο».')
                category = 'Άλλο'
            status = match_choice(row.get('status', ''), core.STATUSES, core.STATUSES[0]) or core.STATUSES[0]
            flag = match_choice(row.get('calendar_flag', ''), core.CALENDAR_FLAGS, core.CALENDAR_FLAGS[0]) or core.CALENDAR_FLAGS[0]
            cfg = core.category_config_for(category, db.category_config())
            data = {'action_date': action_date, 'title': title, 'category': category, 'start_time': start, 'end_time': end,
                    'class_group': row.get('class_group', ''), 'location': row.get('location', ''), 'status': status,
                    'calendar_flag': flag, 'description': row.get('description', ''),
                    'export_google': parse_bool(row.get('export_google', ''), bool(cfg.get('google', True))),
                    'export_website': parse_bool(row.get('export_website', ''), bool(cfg.get('website', True)))}
            rec = db.clean_action(data)
        except ValueError as ex:
            msg = str(ex)
            errors.append(f'Γραμμή {n}: ' + (msg[0].lower() + msg[1:] if msg else 'μη έγκυρη γραμμή.'))
            continue
        key = (rec['action_date'], rec['title'].casefold(), rec['start_time'])
        if skip_dup and (key in seen or db.action_exists(rec['action_date'], rec['title'], rec['start_time'])):
            duplicates.append({'line': n, 'date': rec['action_date'], 'title': rec['title']})
            continue
        seen.add(key)
        rec['_line'] = n
        records.append(rec)
    return {'records': records, 'errors': errors, 'duplicates': duplicates, 'warnings': warnings}


# ------------------------------------------------------------------ εξαγωγές
def _csv_bytes(header, rows) -> bytes:
    buf = io.StringIO(newline='')
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode('utf-8-sig')


def app_csv(rows) -> bytes:
    """Πλήρες CSV (κατάλληλο για επανεισαγωγή)."""
    return _csv_bytes(['ημερομηνία', 'τίτλος', 'περιγραφή', 'τάξη/τμήμα', 'ώρα έναρξης', 'ώρα λήξης', 'κατηγορία', 'τοποθεσία',
                       'κατάσταση', 'calendar', 'export_google', 'export_website'],
                      [[core.iso_to_display(r['action_date']), r['title'], r['description'], r['class_group'], r['start_time'],
                        r['end_time'], r['category'], r['location'], r['status'], r['calendar_flag'],
                        '1' if r['export_google'] else '0', '1' if r['export_website'] else '0'] for r in rows])


def website_csv(rows) -> bytes:
    """Δημόσιος πίνακας ιστοσελίδας (π.χ. Ninja Tables)."""
    return _csv_bytes(['Ημερομηνία', 'Τίτλος δράσης', 'Σύντομη περιγραφή', 'Τάξη / Τμήμα', 'Ώρα έναρξης', 'Κατηγορία', 'Τοποθεσία', 'Κατάσταση'],
                      [[core.iso_to_display(r['action_date']), r['title'], r['description'], r['class_group'], r['start_time'],
                        r['category'], r['location'], r['status']] for r in rows])


def _us_date(iso: str) -> str:
    try:
        return datetime.strptime(iso, '%Y-%m-%d').strftime('%m/%d/%Y')
    except ValueError:
        return iso


def google_csv(rows) -> bytes:
    """Μορφή εισαγωγής του Google Calendar (αγγλικές επικεφαλίδες, ημερομηνίες ΜΜ/ΗΗ/ΕΕΕΕ)."""
    out = []
    for r in rows:
        st = r['start_time']
        et = r['end_time'] or core.default_end_time(st)
        out.append([r['title'], _us_date(r['action_date']), st, _us_date(r['action_date']), et if st else '',
                    'False' if st else 'True', r['description'], r['location']])
    return _csv_bytes(['Subject', 'Start Date', 'Start Time', 'End Date', 'End Time', 'All Day Event', 'Description', 'Location'], out)


def _ics_escape(text: str) -> str:
    return (text or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\r\n', '\\n').replace('\n', '\\n')


def _ics_fold(line: str) -> str:
    """RFC 5545: γραμμές έως 75 octets, συνέχεια με CRLF + κενό (χωρίς να κόβονται χαρακτήρες UTF-8)."""
    out, cur, size = [], '', 0
    for ch in line:
        n = len(ch.encode('utf-8'))
        if size + n > (75 if not out else 74):
            out.append(cur); cur, size = '', 0
        cur += ch; size += n
    out.append(cur)
    return '\r\n '.join(out)


ICS_TZ = ('BEGIN:VTIMEZONE', 'TZID:Europe/Athens', 'BEGIN:DAYLIGHT', 'TZOFFSETFROM:+0200', 'TZOFFSETTO:+0300', 'TZNAME:EEST',
          'DTSTART:19700329T030000', 'RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU', 'END:DAYLIGHT', 'BEGIN:STANDARD',
          'TZOFFSETFROM:+0300', 'TZOFFSETTO:+0200', 'TZNAME:EET', 'DTSTART:19701025T040000', 'RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU',
          'END:STANDARD', 'END:VTIMEZONE')


def ics(rows, calendar_name: str = '', stamp: datetime | None = None) -> bytes:
    """Αρχείο .ics με ζώνη ώρας Ελλάδας. Το UID είναι σταθερό ανά δράση, ώστε μια νέα
    εισαγωγή να ενημερώνει τα ίδια γεγονότα αντί να τα διπλασιάζει."""
    stamp = (stamp or datetime.utcnow()).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//School Actions Desktop//EL', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
    if calendar_name:
        lines.append('X-WR-CALNAME:' + _ics_escape(calendar_name))
    lines.append('X-WR-TIMEZONE:Europe/Athens')
    lines.extend(ICS_TZ)
    for r in rows:
        d = r['action_date'].replace('-', '')
        st = r['start_time']
        lines += ['BEGIN:VEVENT', f"UID:school-action-{r['id']}@local", 'DTSTAMP:' + stamp]
        if st:
            et = r['end_time'] or core.default_end_time(st)
            lines += [f'DTSTART;TZID=Europe/Athens:{d}T{st.replace(":", "")}00', f'DTEND;TZID=Europe/Athens:{d}T{et.replace(":", "")}00']
        else:
            nxt = (datetime.strptime(r['action_date'], '%Y-%m-%d') + timedelta(days=1)).strftime('%Y%m%d')
            lines += [f'DTSTART;VALUE=DATE:{d}', f'DTEND;VALUE=DATE:{nxt}']
        lines.append('SUMMARY:' + _ics_escape(r['title']))
        if r['description']:
            lines.append('DESCRIPTION:' + _ics_escape(r['description']))
        if r['location']:
            lines.append('LOCATION:' + _ics_escape(r['location']))
        if r['category']:
            lines.append('CATEGORIES:' + _ics_escape(r['category']))
        if r['status'] == 'Ακυρώθηκε':
            lines.append('STATUS:CANCELLED')
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    return ('\r\n'.join(_ics_fold(x) for x in lines) + '\r\n').encode('utf-8')


EXPORTS = {
    # τύπος: (ρύθμιση λειτουργίας, κανόνας κατηγορίας, συνάρτηση, πρόθεμα αρχείου, επέκταση, mime)
    'app_csv': ('enable_csv', 'app_csv', app_csv, 'draseis_sxoleiou_app', 'csv', 'text/csv; charset=utf-8'),
    'website': ('enable_website_export', 'website', website_csv, 'draseis_sxoleiou_pinakas_istoselidas', 'csv', 'text/csv; charset=utf-8'),
    'google': ('enable_google_calendar_export', 'google', google_csv, 'draseis_sxoleiou_google_calendar', 'csv', 'text/csv; charset=utf-8'),
    'ics': ('enable_ics_export', 'ics', None, 'draseis_sxoleiou_calendar', 'ics', 'text/calendar; charset=utf-8'),
}


def export(db: core.Database, kind: str, rows: list[dict]) -> dict:
    """Επιστρέφει {'data', 'filename', 'mime', 'count', 'skipped', 'pending_ids'}."""
    if kind not in EXPORTS:
        raise ValueError('Άγνωστος τύπος εξαγωγής.')
    feature, rule, fn, prefix, ext, mime = EXPORTS[kind]
    if not db.get_bool(feature, True):
        raise ValueError('Η λειτουργία αυτή είναι απενεργοποιημένη από τις Ρυθμίσεις.')
    cfg = db.category_config()
    keep = [r for r in rows if core.row_allows(r, rule, cfg)]
    if not keep:
        raise ValueError('Δεν υπάρχουν δράσεις για εξαγωγή. Οι κατηγορίες ή οι δράσεις που δεν επιτρέπουν αυτή την εξαγωγή παραλείπονται.')
    data = ics(keep, db.school_name()) if kind == 'ics' else fn(keep)
    pending = [r['id'] for r in keep if r['calendar_flag'] != 'Περάστηκε' and r['status'] != 'Ακυρώθηκε'] if kind in ('google', 'ics') else []
    return {'data': data, 'filename': f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}", 'mime': mime,
            'count': len(keep), 'skipped': len(rows) - len(keep), 'pending_ids': pending}
