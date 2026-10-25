"""Αναφορές / εκτυπώσεις σε HTML (προεπισκόπηση μέσα στην εφαρμογή, εκτύπωση ή PDF)."""
from __future__ import annotations

import html
from datetime import date, datetime

import core

REPORT_TYPES = [
    ['all', 'Συνολική λίστα δράσεων'],
    ['all_by_month', 'Συνολική λίστα ανά μήνα'],
    ['scheduled', 'Προγραμματισμένες δράσεις'],
    ['completed', 'Ολοκληρωμένες δράσεις'],
    ['by_category', 'Ανά κατηγορία'],
    ['calendar', 'Έλεγχος Calendar'],
    ['guide', 'Οδηγός Ημερών & Επετείων'],
    ['filters', 'Τρέχοντα φίλτρα διαχείρισης'],
]

CSS = """
:root{--primary:#2F6F73;--gold:#D4A017;--text:#2E2E2E;--muted:#5F6B76;--border:#E5E5E5;--bg:#F7F7F5}
*{box-sizing:border-box}body{font-family:"Segoe UI",Arial,sans-serif;color:var(--text);background:var(--bg);margin:0;padding:24px}
.print-toolbar{max-width:1180px;margin:0 auto 14px;background:#fff;border:1px solid var(--border);border-radius:12px;padding:10px 12px;display:flex;align-items:center;gap:10px}
.print-toolbar button{border:0;border-radius:9px;padding:9px 14px;font-family:inherit;font-weight:700;cursor:pointer;background:var(--primary);color:#fff}
.print-toolbar .hint{margin-left:auto;color:var(--muted);font-size:12px}
.report{max-width:1180px;margin:0 auto;background:#fff;border:1px solid var(--border);border-radius:14px;padding:26px}
h1{margin:0;color:var(--primary);font-size:22px}h2{margin:6px 0 0;color:#34495E;font-size:17px;font-weight:600}
.meta{margin:10px 0 18px;color:var(--muted);font-size:12.5px}.summary{display:flex;gap:12px;margin:0 0 18px;flex-wrap:wrap}
.box{border-left:5px solid var(--gold);background:#FAFAF8;padding:8px 14px;border-radius:10px;min-width:150px;font-size:12.5px}.box b{display:block;font-size:20px;color:#34495E}
table{width:100%;border-collapse:collapse;font-size:12px}th{background:#EEF3F3;color:#34495E;text-align:left;padding:8px;border-bottom:2px solid var(--primary);white-space:nowrap}
td{padding:8px;border-bottom:1px solid var(--border);vertical-align:top}tr:nth-child(even) td{background:#FCFCFB}
tr{page-break-inside:avoid}thead{display:table-header-group}
tr.internal-use td{background:#FFF0DE!important;border-bottom:1px solid #E6B980}
.internal-badge{display:inline-block;color:#8A4B00;background:#FFE2B8;border:1px solid #E6B980;border-radius:999px;padding:1px 8px;font-size:10.5px;font-weight:800;margin-bottom:3px}
tr.academic-milestone td{background:#FFF8D8!important;border-bottom:1px solid #D4A017}
.milestone-badge{display:inline-block;color:#34495E;background:#FFF1B8;border:1px solid #D4A017;border-radius:999px;padding:1px 8px;font-size:10.5px;font-weight:800;margin-bottom:3px}
.month-row td{background:#EEF3F3!important;color:var(--primary);font-weight:700;font-size:14px;border-top:2px solid var(--primary);padding:9px 8px}
td span.d{color:var(--muted);font-size:11.5px;white-space:pre-line}.note{margin:18px 0 0;border-left:4px solid var(--gold);background:#FAFAF8;padding:10px 14px;color:var(--muted);font-size:12.5px}
.entry{border-bottom:1px solid var(--border);padding:10px 0;page-break-inside:avoid}.entry h3{margin:0 0 6px;color:#34495E;font-size:14.5px}.entry ol{margin:0;padding-left:22px}.entry li{line-height:1.55;margin:0 0 6px}
.footer{margin-top:16px;color:var(--muted);font-size:11px;text-align:right}
@page{size:A4 landscape;margin:12mm}
@media print{body{background:#fff;padding:0}.print-toolbar{display:none!important}.report{border:0;border-radius:0;padding:0;max-width:none}}
"""


def _page(title: str, school: str, body: str, toolbar: bool, portrait: bool = False) -> str:
    bar = ('<div class="print-toolbar"><button onclick="window.print()">Εκτύπωση</button>'
           '<span class="hint">Για PDF: Εκτύπωση → «Αποθήκευση ως PDF»</span></div>') if toolbar else ''
    css = CSS + ('@page{size:A4 portrait;margin:14mm}' if portrait else '')
    return (f'<!doctype html><html lang="el"><head><meta charset="utf-8"><title>{html.escape(title)} - {html.escape(school)}</title>'
            f'<style>{css}</style></head><body>{bar}<div class="report">{body}'
            f'<div class="footer">{html.escape(core.APP_NAME)} • έκδοση {core.VERSION}</div></div></body></html>')


def _month_bounds(value: str):
    """'2026-03' → (date(2026,3,1), date(2026,4,1))."""
    y, m = (int(x) for x in value.split('-')[:2])
    start = date(y, m, 1)
    end = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return start, end


def select_rows(db: core.Database, opt: dict):
    """Επιλογή δράσεων και υπότιτλος σύμφωνα με τις επιλογές της σελίδας Εκτυπώσεις."""
    kind = opt.get('type', 'all')
    title = dict(REPORT_TYPES).get(kind, 'Συνολική λίστα δράσεων')
    parts = []
    cfg = db.category_config()
    if kind == 'filters':
        f = opt.get('filters') or {}
        rows = db.list_actions(f)
        desc = [f"Αναζήτηση: «{f['search']}»" if f.get('search') else '',
                f"Κατηγορία: {f['category']}" if f.get('category') not in (None, '', 'Όλες') else '',
                f"Κατάσταση: {f['status']}" if f.get('status') not in (None, '', 'Όλες') else '',
                f"Calendar: {f['calendar']}" if f.get('calendar') not in (None, '', 'Όλες') else '',
                f"Σχολικό έτος: {f['school_year']}" if f.get('school_year') not in (None, '', 'Όλα') else '']
        parts = [x for x in desc if x] or ['Χωρίς φίλτρα']
        rows = [r for r in rows if core.category_allows(r['category'], 'reports', cfg)]
        return rows, title, ' • '.join(parts)
    f = {}
    status = opt.get('status') or 'Όλες'
    category = opt.get('category') or 'Όλες'
    if kind == 'scheduled':
        status = 'Προγραμματισμένη'
    elif kind == 'completed':
        status = 'Ολοκληρώθηκε'
    elif kind == 'all_by_month':
        title = 'Συνολική λίστα δράσεων ανά μήνα'
    elif kind == 'calendar':
        title = 'Έλεγχος Calendar - Δράσεις που δεν περάστηκαν'
        f['calendar'] = 'Δεν περάστηκε'
    f['status'] = status
    f['category'] = category
    rows = db.list_actions(f)
    if kind == 'calendar':
        rows = [r for r in rows if r['status'] != 'Ακυρώθηκε' and (core.row_allows(r, 'google', cfg) or core.category_allows(r['category'], 'ics', cfg))]
    sy = opt.get('school_year') or db.current_school_year()
    months = core.school_year_months(sy)
    m_from = opt.get('from_month') if opt.get('from_month') in months else months[0]
    m_to = opt.get('to_month') if opt.get('to_month') in months else months[-1]
    start, _ = _month_bounds(m_from)
    _, end = _month_bounds(m_to)
    if start >= end:
        raise ValueError('Ο μήνας έναρξης πρέπει να είναι πριν ή ίδιος με τον μήνα λήξης.')
    rows = [r for r in rows if start.isoformat() <= r['action_date'] < end.isoformat()]
    parts.append(f'Σχολικό έτος: {sy}')
    parts.append('Περίοδος: ' + (core.month_label(m_from + '-01') if m_from == m_to else f"{core.month_label(m_from + '-01')} έως {core.month_label(m_to + '-01')}"))
    cats = [c for c in (opt.get('categories') or []) if c]
    all_cats = db.categories()
    if kind == 'by_category' and category == 'Όλες' and (not cats or set(cats) == set(all_cats)):
        raise ValueError('Επιλέξτε συγκεκριμένη κατηγορία ή μία/περισσότερες κατηγορίες στη λίστα «Κατηγορίες προς εκτύπωση».')
    if cats and set(cats) != set(all_cats):
        rows = [r for r in rows if r['category'] in cats]
        parts.append('Κατηγορίες: ' + ', '.join(cats))
    before = len(rows)
    rows = [r for r in rows if core.category_allows(r['category'], 'reports', cfg)]
    if len(rows) != before:
        parts.append('Εξαιρέθηκαν κατηγορίες μη διαθέσιμες για αναφορές')
    if opt.get('include_internal', True):
        parts.append('Εσωτερικές δράσεις: Συμπεριλαμβάνονται')
    else:
        rows = [r for r in rows if not r['internal']]
        parts.append('Εσωτερικές δράσεις: Δεν συμπεριλαμβάνονται')
    if category != 'Όλες':
        parts.append(f'Κατηγορία: {category}')
    if status != 'Όλες':
        parts.append(f'Κατάσταση: {status}')
    if kind == 'calendar':
        parts.append('Calendar: Δεν περάστηκε')
    if kind == 'by_category':  # ομαδοποίηση κατά κατηγορία, με τη σειρά των κατηγοριών
        order = {c: i for i, c in enumerate(all_cats)}
        rows.sort(key=lambda r: (order.get(r['category'], 99), r['action_date'], r['start_time']))
    return rows, title, ' • '.join(parts)


def actions_report(db: core.Database, opt: dict, toolbar: bool = False) -> dict:
    if opt.get('type') == 'guide':
        return guide_report(db, opt.get('school_year') or db.current_school_year(), opt.get('category') or 'Όλες', toolbar)
    rows, title, subtitle = select_rows(db, opt)
    if not rows:
        raise ValueError('Δεν υπάρχουν δράσεις για τα επιλεγμένα κριτήρια.')
    kind = opt.get('type', 'all')
    grouped = 'month' if kind in ('all_by_month', 'by_month') else ('category' if kind == 'by_category' else None)
    with_cal = kind == 'calendar'
    cfg = db.category_config()
    cols = 9 if with_cal else 8
    body, n, group = [], 0, None
    for r in rows:
        key = core.month_label(r['action_date']) if grouped == 'month' else (core.category_label(r['category'], cfg) if grouped == 'category' else None)
        if key and key != group:
            group = key
            body.append(f'<tr class="month-row"><td colspan="{cols}">{html.escape(key)}</td></tr>')
        n += 1
        tm = r['start_time'] + (f" - {r['end_time']}" if r['end_time'] else '') if r['start_time'] else r['end_time']
        if r['internal']:
            cls, badge = ' class="internal-use"', '<span class="internal-badge">🔒 ΕΣΩΤΕΡΙΚΗΣ ΧΡΗΣΗΣ</span><br>'
        elif r['milestone']:
            cls, badge = ' class="academic-milestone"', '<span class="milestone-badge">📌 ΕΚΠΑΙΔΕΥΤΙΚΟ ΟΡΟΣΗΜΟ</span><br>'
        else:
            cls, badge = '', ''
        body.append(f'<tr{cls}><td>{n}</td><td style="white-space:nowrap">{core.iso_to_display(r["action_date"])}</td><td style="white-space:nowrap">{html.escape(tm)}</td>'
                    f'<td>{badge}<strong>{html.escape(r["title"])}</strong>' + (f'<br><span class="d">{html.escape(r["description"])}</span>' if r['description'] else '') + '</td>'
                    f'<td>{html.escape(core.category_label(r["category"], cfg))}</td><td>{html.escape(r["class_group"])}</td>'
                    f'<td>{html.escape(r["location"])}</td><td>{html.escape(r["status"])}</td>'
                    + (f'<td>{html.escape(r["calendar_flag"])}</td>' if with_cal else '') + '</tr>')
    by_status = {s: sum(1 for r in rows if r['status'] == s) for s in core.STATUSES}
    boxes = f'<div class="box">Πλήθος δράσεων<b>{len(rows)}</b></div>' + ''.join(
        f'<div class="box">{html.escape(s)}<b>{c}</b></div>' for s, c in by_status.items() if c and kind not in ('scheduled', 'completed'))
    school = db.school_name()
    content = (f'<h1>{html.escape(school)}</h1><h2>{html.escape(title)}</h2>'
               f'<div class="meta">{html.escape(subtitle)} • Δημιουργία: {datetime.now().strftime("%d/%m/%Y %H:%M")}</div>'
               f'<div class="summary">{boxes}</div><table><thead><tr><th>Α/Α</th><th>Ημερομηνία</th><th>Ώρα</th><th>Τίτλος / Περιγραφή</th>'
               f'<th>Κατηγορία</th><th>Τάξη/Τμήμα</th><th>Τοποθεσία</th><th>Κατάσταση</th>' + ('<th>Calendar</th>' if with_cal else '')
               + f'</tr></thead><tbody>{"".join(body)}</tbody></table>')
    return {'html': _page(title, school, content, toolbar), 'count': len(rows), 'title': title, 'subtitle': subtitle,
            'filename': f"anafora_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"}


def guide_report(db: core.Database, school_year: str, category: str = 'Όλες', toolbar: bool = False) -> dict:
    items = db.guide_items()
    if category and category != 'Όλες':
        items = [i for i in items if i['category'] == category]
    if not items:
        raise ValueError('Δεν υπάρχουν ημέρες στον Οδηγό για τα επιλεγμένα κριτήρια.')
    cfg = db.category_config()
    subtitle = f'Σχολικό έτος: {school_year}' + (f' • Κατηγορία: {category}' if category and category != 'Όλες' else '')
    body, cur = [], None
    for n, it in enumerate(items, 1):
        iso = core.guide_item_iso_date(it, school_year)
        ml = core.month_label(iso)
        if ml != cur:
            cur = ml
            body.append(f'<tr class="month-row"><td colspan="4">{html.escape(ml)}</td></tr>')
        internal = core.is_internal(it['category'], cfg)
        milestone = core.is_academic_milestone(it['category'], it['title'])
        cls = ' class="internal-use"' if internal else (' class="academic-milestone"' if milestone else '')
        badge = '<span class="internal-badge">🔒 ΕΣΩΤΕΡΙΚΗΣ ΧΡΗΣΗΣ</span><br>' if internal else ('<span class="milestone-badge">📌 ΕΚΠΑΙΔΕΥΤΙΚΟ ΟΡΟΣΗΜΟ</span><br>' if milestone else '')
        body.append(f'<tr{cls}><td>{n}</td><td>{core.iso_to_display(iso)}</td><td>{badge}<strong>{html.escape(it["title"])}</strong>'
                    + (f'<br><span class="d">{html.escape(it["description"])}</span>' if it['description'] else '')
                    + f'</td><td>{html.escape(core.category_label(it["category"], cfg))}</td></tr>')
    school = db.school_name()
    content = (f'<h1>{html.escape(school)}</h1><h2>Οδηγός Ημερών &amp; Επετείων</h2>'
               f'<div class="meta">{html.escape(subtitle)} • Δημιουργία: {datetime.now().strftime("%d/%m/%Y %H:%M")}</div>'
               f'<div class="summary"><div class="box">Πλήθος ημερών<b>{len(items)}</b></div></div>'
               f'<table><thead><tr><th>Α/Α</th><th>Ημερομηνία</th><th>Ημέρα / Επέτειος</th><th>Κατηγορία</th></tr></thead><tbody>{"".join(body)}</tbody></table>'
               '<div class="note">Ο οδηγός λειτουργεί ως βοηθητικό εργαλείο σχεδιασμού. Κάθε σχολική μονάδα επιλέγει ποιες ημέρες θα αξιοποιήσει '
               'και μπορεί να προσαρμόσει τις εγγραφές της. Οι ημερομηνίες είναι ενδεικτικές· ελέγχετε πάντα τις ισχύουσες εγκυκλίους.</div>')
    return {'html': _page('Οδηγός Ημερών & Επετείων', school, content, toolbar, portrait=True), 'count': len(items),
            'title': 'Οδηγός Ημερών & Επετείων', 'subtitle': subtitle, 'filename': f"odigos_imeron_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"}


def lifelog_report(db: core.Database, rows: list[dict], subtitle: str = '', toolbar: bool = False) -> dict:
    if not rows:
        raise ValueError('Δεν υπάρχουν καταγραφές για εκτύπωση.')
    sections, cur, items = [], None, []

    def flush():
        if cur is not None:
            sections.append(f'<section class="entry"><h3>{html.escape(cur)}</h3><ol>{"".join(items)}</ol></section>')
    for r in rows:
        d = core.iso_to_display(r['log_date'])
        if d != cur:
            flush()
            cur, items = d, []
        items.append('<li>' + html.escape(r['description'] or '').replace('\n', '<br>') + '</li>')
    flush()
    school = db.school_name()
    content = (f'<h1>{html.escape(school)}</h1><h2>ΗΜΕΡΟΛΟΓΙΟ ΣΧΟΛΙΚΗΣ ΖΩΗΣ</h2>'
               f'<div class="meta">{html.escape(subtitle + " • " if subtitle else "")}Δημιουργία: {datetime.now().strftime("%d/%m/%Y %H:%M")} • Πλήθος καταγραφών: {len(rows)}</div>'
               + ''.join(sections))
    return {'html': _page('Ημερολόγιο Σχολικής Ζωής', school, content, toolbar, portrait=True), 'count': len(rows),
            'title': 'Ημερολόγιο Σχολικής Ζωής', 'filename': f"imerologio_scholikis_zois_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"}
