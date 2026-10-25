"""Πυρήνας: σταθερές, κανόνες κατηγοριών, σχολικά έτη, Οδηγός Ημερών και βάση δεδομένων.

Η βάση SQLite έχει το ίδιο σχήμα με την έκδοση Desktop v1.7.x (school_actions.db),
ώστε παλιά αρχεία δεδομένων και αντίγραφα να ανοίγουν αυτούσια.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import unicodedata
from datetime import date, datetime, timedelta

VERSION = '2.2.0'
APP_NAME = 'Πρόγραμμα Δράσεων Σχολείου'
APP_AUTHOR = 'Αρχική ιδέα – επιμέλεια: Σταμάτης Κοκολόγος | Υλοποίηση: Σταμάτης Κοκολόγος, με αξιοποίηση εργαλείων τεχνητής νοημοσύνης'
DB_NAME = 'school_actions.db'

# ------------------------------------------------------------------ σταθερές
def normalize_categories(categories) -> list[str]:
    """Καθαρίζει τη λίστα κατηγοριών και κρατά πάντα το «Άλλο» στο τέλος."""
    clean: list[str] = []
    for item in categories or []:
        value = (item or '').strip()
        if not value or value == 'Άλλο':
            continue
        if value not in clean:
            clean.append(value)
    clean.append('Άλλο')
    return clean


CATEGORIES = normalize_categories([
    'Θεσμοθετημένες Σχολικές Ημέρες',
    'Εθνικές Επέτειοι',
    'Ευρωπαϊκές & Διεθνείς Ημέρες',
    'Σχολική Ζωή & Δράσεις',
    'Ενημέρωση & Οργάνωση',
    'Εσωτερική Αξιολόγηση',
    'Άλλο',
])
DEFAULT_ACTION_CATEGORY = 'Σχολική Ζωή & Δράσεις'

CATEGORY_REPLACEMENTS = {
    'Εθνικές Επέτειοι & Σχολικές Εορτές': 'Εθνικές Επέτειοι',
    'Περιβάλλον': 'Σχολική Ζωή & Δράσεις',
    'Πολιτισμός': 'Σχολική Ζωή & Δράσεις',
    'Αγωγή Υγείας & Ευημερία': 'Σχολική Ζωή & Δράσεις',
    'Συμπερίληψη & Δικαιώματα': 'Σχολική Ζωή & Δράσεις',
}

STATUSES = ['Προγραμματισμένη', 'Ολοκληρώθηκε', 'Ακυρώθηκε', 'Σε εκκρεμότητα']
CALENDAR_FLAGS = ['Δεν περάστηκε', 'Περάστηκε']
DEFAULT_CURRENT_SCHOOL_YEAR = '2025-2026'
INTERNAL_USE_CATEGORY = 'Εσωτερική Αξιολόγηση'

EXPORT_TYPES = ('app_csv', 'website', 'google', 'ics', 'reports')
CATEGORY_CONFIG_DEFAULTS = {
    'internal': False,
    'app_csv': True,    # Γενικό CSV εφαρμογής / backup / επανεισαγωγή
    'website': True,    # Δημόσια εξαγωγή για πίνακα ιστοσελίδας
    'google': True,     # Google Calendar CSV
    'ics': True,        # Αρχείο ημερολογίου ICS
    'reports': True,    # Εκτυπώσεις / αναφορές
    'icon': '',
    'color': '',        # χρώμα ένδειξης (#RRGGBB)· κενό = αυτόματο
}

# Χρώματα κατηγοριών (ευανάγνωστα σε λευκό φόντο, ξεχωρίζουν μεταξύ τους)
CATEGORY_COLORS = ['#2F6F73', '#3B6FD4', '#7A4FC9', '#C2417A', '#C98A0B', '#3F8F4A', '#D0632B', '#5B6B7A', '#1E8FA8', '#9A5B2E']
CATEGORY_DEFAULT_COLORS = {
    'Θεσμοθετημένες Σχολικές Ημέρες': '#3B6FD4',
    'Εθνικές Επέτειοι': '#1E8FA8',
    'Ευρωπαϊκές & Διεθνείς Ημέρες': '#7A4FC9',
    'Σχολική Ζωή & Δράσεις': '#3F8F4A',
    'Ενημέρωση & Οργάνωση': '#C98A0B',
    'Εσωτερική Αξιολόγηση': '#D0632B',
    'Άλλο': '#5B6B7A',
}

CATEGORY_ICON_CHOICES = [
    ['', 'Χωρίς ειδικό εικονίδιο'],
    ['🔒', 'Εσωτερικής χρήσης'],
    ['📌', 'Ορόσημο / προθεσμία'],
    ['🏫', 'Σχολική ημέρα'],
    ['🇬🇷', 'Εθνική επέτειος'],
    ['🌍', 'Ευρωπαϊκή / διεθνής ημέρα'],
    ['✨', 'Δράση σχολικής ζωής'],
    ['ℹ️', 'Ενημέρωση'],
    ['📝', 'Οργάνωση / προγραμματισμός'],
    ['📅', 'Ημερολογιακή υπενθύμιση'],
    ['⭐', 'Σημαντική δράση'],
    ['⚠️', 'Προσοχή / ειδική επισήμανση'],
]

CATEGORY_DEFAULT_ICONS = {
    'Εσωτερική Αξιολόγηση': '🔒',
    'Ενημέρωση & Οργάνωση': '📌',
    'Θεσμοθετημένες Σχολικές Ημέρες': '🏫',
    'Εθνικές Επέτειοι': '🇬🇷',
    'Ευρωπαϊκές & Διεθνείς Ημέρες': '🌍',
    'Σχολική Ζωή & Δράσεις': '✨',
    'Άλλο': '',
}

FEATURES = {  # ρυθμίσεις λειτουργιών (κλειδί βάσης: προεπιλογή)
    'enable_csv': True,
    'enable_website_export': True,
    'enable_google_calendar_export': True,
    'enable_ics_export': True,
    'auto_backup_before_import': True,
    'skip_duplicate_imports': True,
    'auto_backup_before_delete': True,
    'check_updates_on_startup': True,
}


# ------------------------------------------------------------------ κατηγορίες
def default_category_config(category: str) -> dict:
    cfg = dict(CATEGORY_CONFIG_DEFAULTS)
    cat = (category or '').strip()
    cfg['icon'] = CATEGORY_DEFAULT_ICONS.get(cat, '')
    if cat.casefold() == INTERNAL_USE_CATEGORY.casefold():
        cfg.update({'internal': True, 'website': False, 'google': False, 'ics': False, 'reports': True, 'icon': '🔒'})
    return cfg


def normalize_category_config(categories, raw_config=None) -> dict:
    """Επιστρέφει πλήρεις ρυθμίσεις εξαγωγών για όλες τις κατηγορίες."""
    raw_config = raw_config if isinstance(raw_config, dict) else {}
    cleaned = {}
    for category in normalize_categories(categories):
        existing = raw_config.get(category) if isinstance(raw_config.get(category), dict) else {}
        cfg = default_category_config(category)
        for key in CATEGORY_CONFIG_DEFAULTS:
            if key in existing:
                if key == 'icon':
                    cfg[key] = str(existing.get(key) or '')[:4]
                elif key == 'color':
                    c = str(existing.get(key) or '').strip()
                    cfg[key] = c if (len(c) == 7 and c.startswith('#') and all(x in '0123456789abcdefABCDEF' for x in c[1:])) else ''
                else:
                    cfg[key] = bool(existing.get(key))
        if category.casefold() == INTERNAL_USE_CATEGORY.casefold():
            # Η κατηγορία εσωτερικής αξιολόγησης παραμένει πάντα ασφαλής.
            cfg.update({'internal': True, 'website': False, 'google': False, 'ics': False})
            cfg['icon'] = cfg.get('icon') or '🔒'
        if cfg['internal'] and not cfg['icon']:
            cfg['icon'] = '🔒'
        cleaned[category] = cfg
    used = {c['color'] for c in cleaned.values() if c['color']}
    free = [c for c in CATEGORY_COLORS if c not in used] or CATEGORY_COLORS
    for i, (name, cfg) in enumerate(cleaned.items()):  # αυτόματο χρώμα όπου δεν έχει οριστεί
        if not cfg['color']:
            cfg['color'] = CATEGORY_DEFAULT_COLORS.get(name) or free[i % len(free)]
    return cleaned


def category_config_for(category: str, config: dict | None = None) -> dict:
    category = (category or '').strip()
    if config and isinstance(config.get(category), dict):
        cfg = dict(default_category_config(category))
        cfg.update(config[category])
        return cfg
    return default_category_config(category)


def is_internal(category: str, config: dict | None = None) -> bool:
    return bool(category_config_for(category, config).get('internal', False))


def category_allows(category: str, export_type: str, config: dict | None = None) -> bool:
    return bool(category_config_for(category, config).get(export_type, True))


def category_icon(category: str, config: dict | None = None) -> str:
    cfg = category_config_for(category, config)
    return (cfg.get('icon') or ('🔒' if cfg.get('internal') else '')).strip()


def category_label(category: str, config: dict | None = None) -> str:
    icon = category_icon(category, config)
    return f'{icon} {category}' if icon else (category or '')


def canonical_category(category: str, title: str = '') -> str:
    """Η επίσημη/καθαρή κατηγορία για τις προτεινόμενες ημέρες του Οδηγού."""
    value = (category or '').strip()
    title_cf = (title or '').strip().casefold()
    if value in CATEGORIES:
        return value
    if value in CATEGORY_REPLACEMENTS:
        if any(t in title_cf for t in ('παγκόσμια', 'ευρωπαϊκή', 'διεθνής', 'διεθνείς')):
            return 'Ευρωπαϊκές & Διεθνείς Ημέρες'
        return CATEGORY_REPLACEMENTS[value]
    return value or 'Άλλο'


def is_academic_milestone(category: str, title: str = '') -> bool:
    if (category or '').strip() != 'Ενημέρωση & Οργάνωση':
        return False
    t = (title or '').casefold()
    return 'τριμήν' in t or 'λήξη 1ου' in t or 'λήξη 2ου' in t or 'λήξη 3ου' in t


def row_allows(row: dict, export_type: str, config: dict | None = None) -> bool:
    """Κανόνες κατηγορίας + επιλογές ανά δράση."""
    if not category_allows(row.get('category', ''), export_type, config):
        return False
    if export_type == 'google' and not row.get('export_google', True):
        return False
    if export_type == 'website' and not row.get('export_website', True):
        return False
    return True


# ------------------------------------------------------------------ ημερομηνίες / σχολικά έτη
MONTHS = {1: 'Ιανουάριος', 2: 'Φεβρουάριος', 3: 'Μάρτιος', 4: 'Απρίλιος', 5: 'Μάιος', 6: 'Ιούνιος',
          7: 'Ιούλιος', 8: 'Αύγουστος', 9: 'Σεπτέμβριος', 10: 'Οκτώβριος', 11: 'Νοέμβριος', 12: 'Δεκέμβριος'}


def school_year_of(d: date) -> str:
    start = d.year if d.month >= 9 else d.year - 1
    return f'{start}-{start + 1}'


def current_school_year_label(today: date | None = None) -> str:
    return school_year_of(today or date.today())


def valid_school_year_label(value: str) -> bool:
    value = (value or '').strip()
    if len(value) != 9 or value[4] != '-':
        return False
    try:
        return int(value[5:]) == int(value[:4]) + 1
    except ValueError:
        return False


def school_year_for_iso_date(value: str, fallback: str | None = None) -> str:
    """Σεπτέμβριος–Δεκέμβριος: έτος έναρξης· Ιανουάριος–Αύγουστος: προηγούμενο."""
    try:
        return school_year_of(datetime.strptime((value or '').strip(), '%Y-%m-%d').date())
    except ValueError:
        return fallback if valid_school_year_label(fallback or '') else current_school_year_label()


def school_year_bounds(school_year: str) -> tuple[date, date]:
    start = int(school_year.split('-')[0]) if valid_school_year_label(school_year) else int(current_school_year_label()[:4])
    return date(start, 9, 1), date(start + 1, 9, 1)


def school_year_months(school_year: str) -> list[str]:
    """Μήνες σχολικού έτους (ΕΕΕΕ-ΜΜ), από Σεπτέμβριο έως Αύγουστο."""
    start = school_year_bounds(school_year)[0].year
    return [f'{start}-{m:02d}' for m in range(9, 13)] + [f'{start + 1}-{m:02d}' for m in range(1, 9)]


def guide_item_iso_date(item: dict, school_year: str) -> str:
    start = school_year_bounds(school_year)[0].year
    month, day = int(item['month']), int(item['day'])
    year = start if month >= 9 else start + 1
    if month == 2 and day == 29:
        try:
            return date(year, 2, 29).isoformat()
        except ValueError:
            return date(year, 2, 28).isoformat()
    return date(year, month, day).isoformat()


def guide_sort_key(item: dict):
    month = int(item['month'])
    return (month if month >= 9 else month + 12, int(item['day']), item.get('title', ''))


def iso_to_display(value: str) -> str:
    try:
        return datetime.strptime((value or '').strip(), '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        return value or ''


def month_label(value: str) -> str:
    try:
        dt = datetime.strptime((value or '').strip()[:10], '%Y-%m-%d')
        return f'{MONTHS[dt.month]} {dt.year}'
    except ValueError:
        return 'Χωρίς έγκυρη ημερομηνία'


def parse_date_to_iso(value: str) -> str:
    """Δέχεται ΗΗ/ΜΜ/ΕΕΕΕ, Η/Μ/ΕΕΕΕ, ΗΗ-ΜΜ-ΕΕΕΕ, ΗΗ.ΜΜ.ΕΕΕΕ ή ΕΕΕΕ-ΜΜ-ΗΗ."""
    value = (value or '').strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y', '%Y/%m/%d', '%d/%m/%y'):
        try:
            return datetime.strptime(value, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    raise ValueError('Η ημερομηνία πρέπει να έχει μορφή ΗΗ/ΜΜ/ΕΕΕΕ, π.χ. 14/05/2026.')


def normalize_time(value: str) -> str:
    """'9:00', '09.00', '0900' → '09:00'. Κενό → ''. Μη έγκυρη → ValueError."""
    v = (value or '').strip().replace('.', ':')
    if not v:
        return ''
    if v.isdigit() and len(v) in (3, 4):
        v = v[:-2] + ':' + v[-2:]
    if v.count(':') == 2:  # 09:00:00
        v = v.rsplit(':', 1)[0]
    try:
        return datetime.strptime(v, '%H:%M').strftime('%H:%M')
    except ValueError:
        raise ValueError('Οι ώρες πρέπει να έχουν μορφή ΩΩ:ΛΛ, π.χ. 09:30.')


def fold(text: str) -> str:
    """Για αναζήτηση: πεζά, χωρίς τόνους/διαλυτικά (ά→α, ϊ→ι), τελικό ς→σ."""
    s = unicodedata.normalize('NFD', (text or '').casefold())
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').replace('ς', 'σ').strip()


def default_end_time(start_time: str) -> str:
    try:
        return (datetime.strptime(start_time, '%H:%M') + timedelta(hours=1)).strftime('%H:%M')
    except ValueError:
        return start_time or ''


# ------------------------------------------------------------------ Οδηγός Ημερών
DAY_GUIDE_ITEMS = [
    {"day": 1, "month": 9, "title": "Έναρξη σχολικού έτους", "category": "Ενημέρωση & Οργάνωση", "description": "Ενδεικτική καταγραφή έναρξης του σχολικού έτους και αρχικής οργάνωσης της σχολικής μονάδας."},
    {"day": 11, "month": 9, "title": "Αγιασμός - Έναρξη διδακτικού έτους", "category": "Ενημέρωση & Οργάνωση", "description": "Ενδεικτική δράση για τον Αγιασμό και την επίσημη έναρξη του διδακτικού έτους."},
    {"day": 21, "month": 9, "title": "Παγκόσμια Ημέρα Ειρήνης", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση για την ειρήνη, τη συνεργασία και τη δημοκρατική συνύπαρξη."},
    {"day": 26, "month": 9, "title": "Ευρωπαϊκή Ημέρα Γλωσσών", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση για τη γλωσσική πολυμορφία, την επικοινωνία και τον ευρωπαϊκό πολιτισμό."},
    {"day": 26, "month": 9, "title": "Πανελλήνια Ημέρα Σχολικού Αθλητισμού - Ευρωπαϊκή Ημέρα Αθλητισμού", "category": "Θεσμοθετημένες Σχολικές Ημέρες", "description": "Ενδεικτική αθλητική δράση για την άσκηση, τη συνεργασία, τη συμπερίληψη και το ευ αγωνίζεσθαι."},
    {"day": 1, "month": 10, "title": "Παγκόσμια Ημέρα για την Τρίτη Ηλικία", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση διαγενεακής επικοινωνίας, σεβασμού και σύνδεσης με την τοπική κοινότητα."},
    {"day": 5, "month": 10, "title": "Παγκόσμια Ημέρα Εκπαιδευτικού", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση αναγνώρισης του εκπαιδευτικού έργου και της σχολικής κοινότητας."},
    {"day": 10, "month": 10, "title": "Παγκόσμια Ημέρα Ψυχικής Υγείας", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση για την ψυχική υγεία, τη φροντίδα του εαυτού, την ενσυναίσθηση και την υποστήριξη."},
    {"day": 20, "month": 10, "title": "Συλλογικός Προγραμματισμός - Εσωτερική Αξιολόγηση", "category": "Εσωτερική Αξιολόγηση", "description": "Προθεσμία: έως 20 Οκτωβρίου. Συλλογικός Προγραμματισμός Σχολικής Μονάδας. Καταγραφή Σχεδίων δράσης και υπεύθυνων συντονιστών/στριών ομάδας, με ευθύνη Διευθυντή/τριας ή Προϊσταμένου/ης σχολικής μονάδας."},
    {"day": 28, "month": 10, "title": "Εθνική Επέτειος 28ης Οκτωβρίου", "category": "Εθνικές Επέτειοι", "description": "Ενδεικτική σχολική γιορτή ή δράση ιστορικής μνήμης για την Εθνική Επέτειο της 28ης Οκτωβρίου."},
    {"day": 17, "month": 11, "title": "Επέτειος Πολυτεχνείου", "category": "Εθνικές Επέτειοι", "description": "Ενδεικτική σχολική δράση για τη δημοκρατία, την ελευθερία και την ιστορική μνήμη."},
    {"day": 20, "month": 11, "title": "Παγκόσμια Ημέρα για τα δικαιώματα του Παιδιού", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση για τα δικαιώματα του παιδιού, την ισότητα, τη φροντίδα και τη συμμετοχή."},
    {"day": 3, "month": 12, "title": "Παγκόσμια Ημέρα Ατόμων με Αναπηρία", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση ευαισθητοποίησης για την προσβασιμότητα, τη συμπερίληψη και τον σεβασμό των δικαιωμάτων."},
    {"day": 10, "month": 12, "title": "Λήξη 1ου τριμήνου", "category": "Ενημέρωση & Οργάνωση", "description": "Εκπαιδευτικό/διοικητικό ορόσημο: λήξη 1ου τριμήνου. Προτείνεται έλεγχος εκκρεμοτήτων, ενημερώσεων και σχετικού προγραμματισμού."},
    {"day": 10, "month": 12, "title": "Σχεδιασμός Δράσης - Εσωτερική Αξιολόγηση", "category": "Εσωτερική Αξιολόγηση", "description": "Προθεσμία: έως 10 Δεκεμβρίου. Υποβολή σχεδίων δράσης, με ευθύνη του/της Συντονιστή/στριας Ομάδας Δράσης."},
    {"day": 27, "month": 1, "title": "Ημέρα Μνήμης του Ολοκαυτώματος", "category": "Θεσμοθετημένες Σχολικές Ημέρες", "description": "Ενδεικτική δράση μνήμης, ιστορικής προσέγγισης και καλλιέργειας δημοκρατικής συνείδησης."},
    {"day": 30, "month": 1, "title": "Τριών Ιεραρχών", "category": "Θεσμοθετημένες Σχολικές Ημέρες", "description": "Ενδεικτική σχολική δράση για τους Τρεις Ιεράρχες και τη σημασία της παιδείας."},
    {"day": 1, "month": 2, "title": "Πανελλήνια Ημέρα Φιλάθλου", "category": "Θεσμοθετημένες Σχολικές Ημέρες", "description": "Ενδεικτική δράση για τον υγιή αθλητισμό, το φίλαθλο πνεύμα και τον σεβασμό."},
    {"day": 9, "month": 2, "title": "Παγκόσμια Ημέρα Ελληνικής Γλώσσας", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση για την ελληνική γλώσσα, τη φιλαναγνωσία και τη γλωσσική καλλιέργεια."},
    {"day": 9, "month": 2, "title": "Παγκόσμια Ημέρα Ασφαλούς Πλοήγησης", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση ενημέρωσης για την ασφαλή και υπεύθυνη χρήση του διαδικτύου."},
    {"day": 6, "month": 3, "title": "Πανελλήνια Σχολική Ημέρα κατά της Βίας στο Σχολείο", "category": "Θεσμοθετημένες Σχολικές Ημέρες", "description": "Ενδεικτική δράση πρόληψης της σχολικής βίας, ενίσχυσης της συνεργασίας και καλλιέργειας θετικού σχολικού κλίματος."},
    {"day": 10, "month": 3, "title": "Λήξη 2ου τριμήνου", "category": "Ενημέρωση & Οργάνωση", "description": "Εκπαιδευτικό/διοικητικό ορόσημο: λήξη 2ου τριμήνου. Προτείνεται έλεγχος εκκρεμοτήτων, ενημερώσεων και σχετικού προγραμματισμού."},
    {"day": 18, "month": 3, "title": "Παγκόσμια Ημέρα Ανακύκλωσης", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική περιβαλλοντική δράση για την ανακύκλωση, τη μείωση απορριμμάτων και την υπεύθυνη κατανάλωση."},
    {"day": 21, "month": 3, "title": "Παγκόσμια Ημέρα κατά του Ρατσισμού και των Φυλετικών Διακρίσεων", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση για την ισότητα, τον σεβασμό, τη συμπερίληψη και την αποδοχή της διαφορετικότητας."},
    {"day": 22, "month": 3, "title": "Παγκόσμια Ημέρα Νερού", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση για τη σημασία του νερού, την προστασία των φυσικών πόρων και την αειφορία."},
    {"day": 25, "month": 3, "title": "Εθνική Επέτειος 25ης Μαρτίου", "category": "Εθνικές Επέτειοι", "description": "Ενδεικτική σχολική γιορτή ή δράση ιστορικής μνήμης για την Εθνική Επέτειο της 25ης Μαρτίου."},
    {"day": 2, "month": 4, "title": "Παγκόσμια Ημέρα Παιδικού Βιβλίου", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση φιλαναγνωσίας, δημιουργικής γραφής ή παρουσίασης παιδικού βιβλίου."},
    {"day": 4, "month": 4, "title": "Πανελλήνια Σχολική Ημέρα Φιλοζωίας", "category": "Θεσμοθετημένες Σχολικές Ημέρες", "description": "Ενδεικτική δράση ευαισθητοποίησης για τη φροντίδα, την προστασία και τον σεβασμό των ζώων."},
    {"day": 19, "month": 5, "title": "Ημέρα εθνικής μνήμης της γενοκτονίας των Ελλήνων του Πόντου", "category": "Εθνικές Επέτειοι", "description": "Ενδεικτική δράση ιστορικής μνήμης και ενημέρωσης."},
    {"day": 2, "month": 6, "title": "Υλοποίηση και Αποτίμηση Δράσης - Εσωτερική Αξιολόγηση", "category": "Εσωτερική Αξιολόγηση", "description": "Προθεσμία: έως 2 Ιουνίου. Υποβολή κειμένων για την υλοποίηση και αποτίμηση της δράσης, με ευθύνη του/της Συντονιστή/τριας της Ομάδας Δράσης."},
    {"day": 5, "month": 6, "title": "Παγκόσμια Ημέρα Περιβάλλοντος", "category": "Ευρωπαϊκές & Διεθνείς Ημέρες", "description": "Ενδεικτική δράση για την προστασία του περιβάλλοντος, την οικολογική συνείδηση και την αειφορία."},
    {"day": 10, "month": 6, "title": "Λήξη 3ου τριμήνου", "category": "Ενημέρωση & Οργάνωση", "description": "Εκπαιδευτικό/διοικητικό ορόσημο: λήξη 3ου τριμήνου. Προτείνεται έλεγχος εκκρεμοτήτων, ενημερώσεων και σχετικού προγραμματισμού."},
    {"day": 25, "month": 6, "title": "Ετήσια Έκθεση Αξιολόγησης Σχολικής Μονάδας", "category": "Εσωτερική Αξιολόγηση", "description": "Προθεσμία: έως 25 Ιουνίου. Υποβολή ετήσιας έκθεσης αξιολόγησης σχολικής μονάδας, με ευθύνη του/της Διευθυντή/τριας."},
]


def clean_guide_item(item: dict) -> dict:
    """Έλεγχος μίας ημέρας οδηγού. ValueError με ελληνικό μήνυμα αν δεν είναι έγκυρη."""
    try:
        day, month = int(item.get('day')), int(item.get('month'))
        date(2028, month, day)  # δίσεκτο έτος: δεκτή και η 29/2
    except (TypeError, ValueError):
        raise ValueError('Συμπληρώστε έγκυρη ημέρα και μήνα.')
    title = str(item.get('title', '')).strip()
    if not title:
        raise ValueError('Συμπληρώστε τίτλο ημέρας/επετείου.')
    return {'day': day, 'month': month, 'title': title,
            'category': canonical_category(str(item.get('category', '')).strip() or 'Άλλο', title),
            'description': str(item.get('description', '')).strip()}


def merge_guide_items_with_defaults(existing_items) -> list[dict]:
    """Συγχωνεύει τον οδηγό του χρήστη με τις προτεινόμενες ημέρες (χωρίς διπλότυπα)."""
    merged, seen = [], set()
    for item in list(existing_items or []) + DAY_GUIDE_ITEMS:
        try:
            clean = clean_guide_item(item)
        except ValueError:
            continue
        key = (clean['day'], clean['month'], clean['title'].casefold())
        if key not in seen:
            seen.add(key); merged.append(clean)
    return sorted(merged, key=guide_sort_key)


# ------------------------------------------------------------------ κωδικός Ημερολογίου
PBKDF2_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ROUNDS)
    return 'pbkdf2_sha256$%d$%s$%s' % (PBKDF2_ROUNDS, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, dk = stored.split('$')
        if algo != 'pbkdf2_sha256':
            return False
        calc = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


# ------------------------------------------------------------------ βάση δεδομένων
ACTION_FIELDS = ('action_date', 'title', 'category', 'start_time', 'end_time', 'class_group', 'location',
                 'status', 'calendar_flag', 'export_google', 'export_website', 'description', 'school_year')


def now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')


def is_valid_database(path) -> bool:
    """Ελέγχει ότι ένα αρχείο είναι βάση της εφαρμογής (πίνακας actions)."""
    try:
        with open(path, 'rb') as f:
            if f.read(16) != b'SQLite format 3\x00':
                return False
        from pathlib import Path
        con = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
        try:
            cols = {r[1] for r in con.execute('PRAGMA table_info(actions)')}
        finally:
            con.close()
        return {'action_date', 'title', 'category'} <= cols
    except Exception:
        return False


class Database:
    """Πρόσβαση στη βάση. Όλες οι κλήσεις γίνονται με κλείδωμα (η υπηρεσία είναι πολυνηματική)."""

    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        # Χωρίς WAL: η βάση μπορεί να βρίσκεται σε κοινόχρηστο φάκελο δικτύου.
        self.conn.execute('PRAGMA journal_mode=DELETE')
        self.conn.execute('PRAGMA foreign_keys=OFF')
        with self.lock:
            self.init_db()

    # ---------------------------------------------------------- σχήμα / μετάβαση
    def init_db(self) -> None:
        cur = self.conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_date TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                start_time TEXT,
                end_time TEXT,
                class_group TEXT,
                location TEXT,
                status TEXT NOT NULL DEFAULT 'Προγραμματισμένη',
                calendar_flag TEXT NOT NULL DEFAULT 'Δεν περάστηκε',
                export_google INTEGER NOT NULL DEFAULT 1,
                export_website INTEGER NOT NULL DEFAULT 1,
                description TEXT,
                school_year TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")
        cols = [r[1] for r in cur.execute('PRAGMA table_info(actions)').fetchall()]
        if 'school_year' not in cols:
            cur.execute('ALTER TABLE actions ADD COLUMN school_year TEXT')
        if 'export_google' not in cols:
            cur.execute('ALTER TABLE actions ADD COLUMN export_google INTEGER NOT NULL DEFAULT 1')
        if 'export_website' not in cols:
            cur.execute('ALTER TABLE actions ADD COLUMN export_website INTEGER NOT NULL DEFAULT 1')
        cur.execute("""CREATE TABLE IF NOT EXISTS life_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_date TEXT NOT NULL,
                description TEXT NOT NULL,
                source_action_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")
        cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_life_log_source_action
                ON life_log(source_action_id) WHERE source_action_id IS NOT NULL""")
        cur.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_actions_date ON actions(action_date)')
        defaults = {'school_name': 'Σχολική μονάδα', 'enable_calendar': '1', 'life_log_protection_enabled': '1',
                    'life_log_password': '', 'current_school_year': current_school_year_label()}
        defaults.update({k: '1' if v else '0' for k, v in FEATURES.items()})
        for k, v in defaults.items():
            cur.execute('INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)', (k, v))
        cur.execute('INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)', ('school_years', current_school_year_label()))

        # Κωδικός Ημερολογίου: οι παλιές εκδόσεις τον κρατούσαν ως απλό κείμενο.
        plain = (self._get(cur, 'life_log_password') or '').strip()
        if plain:
            cur.execute("INSERT INTO settings(key,value) VALUES('life_log_password_hash', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (hash_password(plain),))
            cur.execute("UPDATE settings SET value='' WHERE key='life_log_password'")

        # Σχολικό έτος σε δράσεις που δεν το έχουν, και ενημέρωση της λίστας ετών.
        years = set(y for y in (self._get(cur, 'school_years') or '').splitlines() if valid_school_year_label(y))
        for row in cur.execute('SELECT id, action_date, school_year FROM actions').fetchall():
            sy = row['school_year'] or ''
            if not valid_school_year_label(sy):
                sy = school_year_for_iso_date(row['action_date'])
                cur.execute('UPDATE actions SET school_year=? WHERE id=?', (sy, row['id']))
            years.add(sy)
        years.add(current_school_year_label())
        cur.execute("UPDATE settings SET value=? WHERE key='school_years'", ('\n'.join(sorted(years)),))

        # Κατηγορίες: κρατάμε σειρά και επιλογές του χρήστη. Μια προτεινόμενη κατηγορία
        # προστίθεται μόνο μία φορά (αν ο χρήστης τη διαγράψει, δεν ξαναεμφανίζεται).
        if self._get(cur, 'categories') is None:
            merged = list(CATEGORIES)
        else:
            existing = normalize_categories((self._get(cur, 'categories') or '').splitlines())
            offered = set((self._get(cur, 'categories_offered') or '').splitlines())
            merged = normalize_categories(existing + [c for c in CATEGORIES if c not in existing and c not in offered])
        cur.execute("INSERT INTO settings(key,value) VALUES('categories_offered', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ('\n'.join(CATEGORIES),))
        cur.execute("INSERT INTO settings(key,value) VALUES('categories', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ('\n'.join(merged),))
        for old, new in CATEGORY_REPLACEMENTS.items():
            cur.execute('UPDATE actions SET category=? WHERE category=?', (new, old))
        ph = ','.join('?' for _ in merged)
        cur.execute(f"UPDATE actions SET category='Άλλο' WHERE category NOT IN ({ph})", merged)
        try:
            raw_cfg = json.loads(self._get(cur, 'category_config') or '{}')
        except ValueError:
            raw_cfg = {}
        cfg = normalize_category_config(merged, raw_cfg)
        cur.execute("INSERT INTO settings(key,value) VALUES('category_config', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (json.dumps(cfg, ensure_ascii=False),))
        self._enforce_category_rules(cur, cfg)

        # Οδηγός Ημερών: συγχώνευση νέων προτεινόμενων ημερών (εκτός αν ο χρήστης τις διέγραψε).
        try:
            guide = json.loads(self._get(cur, 'guide_items') or '[]')
        except ValueError:
            guide = []
        if self._get(cur, 'guide_items') is None:
            guide = merge_guide_items_with_defaults([])
        else:
            removed = self._removed_guide_keys(cur)
            gkey = lambda g: (g['day'], g['month'], g['title'].casefold())
            own = {gkey(clean_guide_item(x)) for x in (guide if isinstance(guide, list) else []) if self._valid_guide(x)}
            guide = [g for g in merge_guide_items_with_defaults(guide if isinstance(guide, list) else [])
                     if gkey(g) in own or gkey(g) not in removed]
        cur.execute("INSERT INTO settings(key,value) VALUES('guide_items', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (json.dumps(guide, ensure_ascii=False),))
        self.conn.commit()

    @staticmethod
    def _get(cur, key):
        row = cur.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def _valid_guide(item) -> bool:
        try:
            clean_guide_item(item)
            return True
        except (ValueError, AttributeError):
            return False

    def _removed_guide_keys(self, cur) -> set:
        try:
            return {tuple(x[:2]) + (x[2],) for x in json.loads(self._get(cur, 'guide_removed') or '[]')}
        except Exception:
            return set()

    @staticmethod
    def _enforce_category_rules(cur, cfg: dict) -> None:
        for name, c in cfg.items():
            if not c.get('website', True):
                cur.execute('UPDATE actions SET export_website=0 WHERE category=?', (name,))
            if not c.get('google', True):
                cur.execute('UPDATE actions SET export_google=0 WHERE category=?', (name,))
            if not c.get('google', True) and not c.get('ics', True):
                cur.execute("UPDATE actions SET calendar_flag='Δεν περάστηκε' WHERE category=?", (name,))

    # ---------------------------------------------------------- ρυθμίσεις
    def get_setting(self, key: str, default: str = '') -> str:
        with self.lock:
            v = self._get(self.conn, key)
        return default if v is None else v

    def set_setting(self, key: str, value: str) -> None:
        with self.lock:
            self.conn.execute('INSERT INTO settings(key,value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
            self.conn.commit()

    def get_bool(self, key: str, default: bool = True) -> bool:
        return self.get_setting(key, '1' if default else '0') == '1'

    def set_bool(self, key: str, value: bool) -> None:
        self.set_setting(key, '1' if value else '0')

    def school_name(self) -> str:
        return self.get_setting('school_name', 'Σχολική μονάδα') or 'Σχολική μονάδα'

    def features(self) -> dict:
        return {k: self.get_bool(k, v) for k, v in FEATURES.items()}

    def set_features(self, values: dict) -> None:
        for k in FEATURES:
            if k in values:
                self.set_bool(k, bool(values[k]))
        f = self.features()
        self.set_bool('enable_calendar', f['enable_google_calendar_export'] or f['enable_ics_export'])

    # ---------------------------------------------------------- σχολικά έτη
    def school_years(self) -> list[str]:
        years = {y.strip() for y in self.get_setting('school_years', '').splitlines() if valid_school_year_label(y.strip())}
        years.add(current_school_year_label())
        years.add(self.current_school_year(_raw=True))
        return sorted(y for y in years if y)

    def set_school_years(self, years) -> None:
        clean = sorted({y.strip() for y in years if valid_school_year_label((y or '').strip())})
        self.set_setting('school_years', '\n'.join(clean))

    def current_school_year(self, _raw=False) -> str:
        v = self.get_setting('current_school_year', '').strip()
        if valid_school_year_label(v):
            return v
        return '' if _raw else current_school_year_label()

    def set_current_school_year(self, value: str) -> None:
        value = (value or '').strip()
        if not valid_school_year_label(value):
            raise ValueError('Το σχολικό έτος πρέπει να έχει μορφή 2026-2027.')
        years = self.school_years()
        if value not in years:
            self.set_school_years(years + [value])
        self.set_setting('current_school_year', value)

    def add_school_year(self, value: str) -> None:
        value = (value or '').strip()
        if not valid_school_year_label(value):
            raise ValueError('Το σχολικό έτος πρέπει να έχει μορφή 2026-2027.')
        self.set_school_years(self.school_years() + [value])

    # ---------------------------------------------------------- κατηγορίες
    def categories(self) -> list[str]:
        return normalize_categories(self.get_setting('categories', '\n'.join(CATEGORIES)).splitlines())

    def category_config(self) -> dict:
        try:
            raw = json.loads(self.get_setting('category_config', '') or '{}')
        except ValueError:
            raw = {}
        return normalize_category_config(self.categories(), raw)

    def save_categories(self, categories, config: dict | None = None, renames: dict | None = None) -> None:
        """Αποθηκεύει λίστα, ιδιότητες και μετονομασίες κατηγοριών.
        Δράσεις κατηγορίας που αφαιρέθηκε μεταφέρονται στο «Άλλο»."""
        cats = normalize_categories(categories)
        with self.lock:
            cur = self.conn.cursor()
            for old, new in (renames or {}).items():
                new = (new or '').strip()
                if old and new and old != new and old != 'Άλλο':
                    cur.execute('UPDATE actions SET category=? WHERE category=?', (new, old))
            ph = ','.join('?' for _ in cats)
            cur.execute(f"UPDATE actions SET category='Άλλο' WHERE category NOT IN ({ph})", cats)
            cfg = normalize_category_config(cats, config if config is not None else self.category_config())
            cur.execute("INSERT INTO settings(key,value) VALUES('categories', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ('\n'.join(cats),))
            cur.execute("INSERT INTO settings(key,value) VALUES('category_config', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (json.dumps(cfg, ensure_ascii=False),))
            self._enforce_category_rules(cur, cfg)
            self.conn.commit()

    def ensure_category(self, category: str) -> None:
        category = (category or '').strip()
        if category and category not in self.categories():
            self.save_categories(self.categories()[:-1] + [category])

    # ---------------------------------------------------------- δράσεις
    def _row(self, r, cfg=None) -> dict:
        d = dict(r)
        d['export_google'] = str(d.get('export_google', 1)).strip() not in ('0', 'False', 'false', '')
        d['export_website'] = str(d.get('export_website', 1)).strip() not in ('0', 'False', 'false', '')
        for k in ('start_time', 'end_time', 'class_group', 'location', 'description', 'school_year'):
            d[k] = d.get(k) or ''
        cfg = cfg if cfg is not None else self.category_config()
        d['internal'] = is_internal(d['category'], cfg)
        d['icon'] = category_icon(d['category'], cfg)
        d['milestone'] = is_academic_milestone(d['category'], d['title'])
        return d

    def list_actions(self, f: dict | None = None) -> list[dict]:
        """Φίλτρα: search, category, status, calendar, school_year, date_from, date_to, ids."""
        f = f or {}
        sql, params = 'SELECT * FROM actions WHERE 1=1', []
        search = fold(f.get('search') or '')
        for key, col in (('category', 'category'), ('status', 'status'), ('calendar', 'calendar_flag'), ('school_year', 'school_year')):
            v = f.get(key)
            if v and v not in ('Όλες', 'Όλα', '*'):
                if isinstance(v, list):
                    if not v:
                        continue
                    sql += f' AND {col} IN ({",".join("?" for _ in v)})'; params += v
                else:
                    sql += f' AND {col} = ?'; params.append(v)
        if f.get('overdue'):  # παρελθούσα ημερομηνία χωρίς σήμανση ολοκλήρωσης/ακύρωσης
            sql += " AND action_date < ? AND status IN ('Προγραμματισμένη', 'Σε εκκρεμότητα')"; params.append(date.today().isoformat())
        if f.get('upcoming'):
            sql += " AND action_date >= ? AND status NOT IN ('Ολοκληρώθηκε', 'Ακυρώθηκε')"; params.append(date.today().isoformat())
        if f.get('today'):
            sql += ' AND action_date = ?'; params.append(date.today().isoformat())
        if f.get('date_from'):
            sql += ' AND action_date >= ?'; params.append(f['date_from'])
        if f.get('date_to'):
            sql += ' AND action_date <= ?'; params.append(f['date_to'])
        if f.get('ids') is not None:
            ids = [int(i) for i in f['ids']]
            if not ids:
                return []
            sql += f' AND id IN ({",".join("?" for _ in ids)})'; params += ids
        sql += " ORDER BY action_date ASC, COALESCE(start_time,'') ASC, id ASC"
        cfg = self.category_config()
        with self.lock:
            rows = self.conn.execute(sql, params).fetchall()
        out = [self._row(r, cfg) for r in rows]
        if search:  # χωρίς διάκριση πεζών/κεφαλαίων και τόνων (το LIKE της SQLite δεν το κάνει για ελληνικά)
            words = search.split()
            out = [r for r in out if all(w in fold(' '.join((r['title'], r['description'], r['class_group'], r['location']))) for w in words)]
        return out

    def get_action(self, action_id: int) -> dict | None:
        with self.lock:
            r = self.conn.execute('SELECT * FROM actions WHERE id=?', (int(action_id),)).fetchone()
        return self._row(r) if r else None

    def clean_action(self, data: dict) -> dict:
        """Έλεγχος και κανονικοποίηση δράσης σύμφωνα με τους κανόνες κατηγορίας."""
        title = (data.get('title') or '').strip()
        if not title:
            raise ValueError('Συμπληρώστε τίτλο δράσης.')
        action_date = parse_date_to_iso(data.get('action_date') or '')
        start_time = normalize_time(data.get('start_time') or '')
        end_time = normalize_time(data.get('end_time') or '')
        if start_time and end_time and end_time < start_time:
            raise ValueError('Η ώρα λήξης είναι πριν από την ώρα έναρξης.')
        cats = self.categories()
        category = (data.get('category') or '').strip() or DEFAULT_ACTION_CATEGORY
        if category not in cats:
            category = 'Άλλο'
        status = data.get('status') if data.get('status') in STATUSES else STATUSES[0]
        flag = data.get('calendar_flag') if data.get('calendar_flag') in CALENDAR_FLAGS else CALENDAR_FLAGS[0]
        cfg = self.category_config()
        feats = self.features()
        eg = bool(data.get('export_google', True)) and category_allows(category, 'google', cfg)
        ew = bool(data.get('export_website', True)) and category_allows(category, 'website', cfg)
        if not (eg or category_allows(category, 'ics', cfg)) or not (feats['enable_google_calendar_export'] or feats['enable_ics_export']):
            flag = 'Δεν περάστηκε'
        sy = (data.get('school_year') or '').strip()
        if not valid_school_year_label(sy):
            sy = school_year_for_iso_date(action_date)
        return {'action_date': action_date, 'title': title, 'category': category, 'start_time': start_time,
                'end_time': end_time, 'class_group': (data.get('class_group') or '').strip(),
                'location': (data.get('location') or '').strip(), 'status': status, 'calendar_flag': flag,
                'export_google': 1 if eg else 0, 'export_website': 1 if ew else 0,
                'description': (data.get('description') or '').strip(), 'school_year': sy}

    def save_action(self, data: dict) -> int:
        rec = self.clean_action(data)
        now = now_iso()
        with self.lock:
            if data.get('id'):
                aid = int(data['id'])
                cur = self.conn.execute('UPDATE actions SET ' + ', '.join(f'{k}=?' for k in ACTION_FIELDS) + ', updated_at=? WHERE id=?',
                                        [rec[k] for k in ACTION_FIELDS] + [now, aid])
                if not cur.rowcount:
                    raise ValueError('Η δράση δεν βρέθηκε (ίσως διαγράφηκε).')
            else:
                cur = self.conn.execute('INSERT INTO actions(' + ','.join(ACTION_FIELDS) + ',created_at,updated_at) VALUES(' + ','.join('?' for _ in ACTION_FIELDS) + ',?,?)',
                                        [rec[k] for k in ACTION_FIELDS] + [now, now])
                aid = int(cur.lastrowid)
            self.conn.commit()
        self._remember_year(rec['school_year'])
        return aid

    def _remember_year(self, sy: str) -> None:
        if valid_school_year_label(sy) and sy not in self.school_years():
            self.set_school_years(self.school_years() + [sy])

    def insert_many(self, records: list[dict]) -> int:
        now = now_iso()
        with self.lock:
            self.conn.executemany('INSERT INTO actions(' + ','.join(ACTION_FIELDS) + ',created_at,updated_at) VALUES(' + ','.join('?' for _ in ACTION_FIELDS) + ',?,?)',
                                  [[r[k] for k in ACTION_FIELDS] + [now, now] for r in records])
            self.conn.commit()
        for sy in {r['school_year'] for r in records}:
            self._remember_year(sy)
        return len(records)

    def restore_actions(self, rows) -> int:
        """Αναίρεση διαγραφής: επανεισαγωγή δράσεων με τα αρχικά τους στοιχεία και αναγνωριστικά."""
        n = 0
        with self.lock:
            for r in rows or []:
                rec = self.clean_action(r)
                cur = self.conn.execute('INSERT OR IGNORE INTO actions(id,' + ','.join(ACTION_FIELDS) + ',created_at,updated_at) VALUES(?,' +
                                        ','.join('?' for _ in ACTION_FIELDS) + ',?,?)',
                                        [int(r['id'])] + [rec[k] for k in ACTION_FIELDS] + [r.get('created_at') or now_iso(), now_iso()])
                n += cur.rowcount or 0
            self.conn.commit()
        return n

    def delete_actions(self, ids) -> int:
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        with self.lock:
            cur = self.conn.execute(f'DELETE FROM actions WHERE id IN ({",".join("?" for _ in ids)})', ids)
            self.conn.commit()
            return int(cur.rowcount or 0)

    def bulk_update(self, ids, status: str | None = None, calendar_flag: str | None = None) -> dict:
        """Μαζική αλλαγή κατάστασης ή σήμανσης Calendar. Η σήμανση Calendar αγνοείται
        για δράσεις που δεν εξάγονται σε ημερολόγιο (κανόνες κατηγορίας ή επιλογή δράσης)."""
        if status is not None and status not in STATUSES:
            raise ValueError('Άγνωστη κατάσταση.')
        if calendar_flag is not None and calendar_flag not in CALENDAR_FLAGS:
            raise ValueError('Άγνωστη σήμανση Calendar.')
        rows = self.list_actions({'ids': ids})
        cfg = self.category_config()
        skipped = 0
        targets = []
        for r in rows:
            if calendar_flag is not None and not (row_allows(r, 'google', cfg) or category_allows(r['category'], 'ics', cfg)):
                skipped += 1
                continue
            targets.append(r['id'])
        now = now_iso()
        with self.lock:
            for aid in targets:
                if status is not None:
                    self.conn.execute('UPDATE actions SET status=?, updated_at=? WHERE id=?', (status, now, aid))
                if calendar_flag is not None:
                    self.conn.execute('UPDATE actions SET calendar_flag=?, updated_at=? WHERE id=?', (calendar_flag, now, aid))
            self.conn.commit()
        return {'updated': len(targets), 'skipped': skipped}

    def action_exists(self, action_date: str, title: str, start_time: str = '') -> bool:
        with self.lock:
            row = self.conn.execute("""SELECT id FROM actions WHERE action_date=? AND lower(trim(title))=lower(trim(?))
                                       AND COALESCE(start_time,'')=COALESCE(?, '') LIMIT 1""",
                                    (action_date, title, start_time or '')).fetchone()
        if row:
            return True
        # Το lower() της SQLite δεν αλλάζει ελληνικά: δεύτερος έλεγχος σε Python.
        with self.lock:
            rows = self.conn.execute("SELECT title FROM actions WHERE action_date=? AND COALESCE(start_time,'')=?",
                                     (action_date, start_time or '')).fetchall()
        t = title.strip().casefold()
        return any((r[0] or '').strip().casefold() == t for r in rows)

    def dashboard(self, today: date | None = None) -> dict:
        today = today or date.today()
        t = today.isoformat()
        rows = self.list_actions()
        cfg = self.category_config()
        upcoming = [r for r in rows if r['action_date'] >= t and r['status'] not in ('Ολοκληρώθηκε', 'Ακυρώθηκε')]
        in30 = (today + timedelta(days=30)).isoformat()
        return {
            'total': len(rows),
            'upcoming': len(upcoming),
            'upcoming30': sum(1 for r in upcoming if r['action_date'] <= in30),
            'done': sum(1 for r in rows if r['status'] == 'Ολοκληρώθηκε'),
            'today': sum(1 for r in rows if r['action_date'] == t),
            'calendar_pending': sum(1 for r in rows if row_allows(r, 'google', cfg) and r['calendar_flag'] != 'Περάστηκε' and r['status'] != 'Ακυρώθηκε'),
            'cancelled': sum(1 for r in rows if r['status'] == 'Ακυρώθηκε'),
            'overdue': sum(1 for r in rows if r['action_date'] < t and r['status'] in ('Προγραμματισμένη', 'Σε εκκρεμότητα')),
            'next': upcoming[:6],
        }

    # ---------------------------------------------------------- Οδηγός Ημερών
    def guide_items(self) -> list[dict]:
        try:
            data = json.loads(self.get_setting('guide_items', '') or '[]')
        except ValueError:
            data = []
        out = []
        for item in data if isinstance(data, list) else []:
            try:
                out.append(clean_guide_item(item))
            except ValueError:
                continue
        return sorted(out, key=guide_sort_key)

    def set_guide_items(self, items) -> None:
        self.set_setting('guide_items', json.dumps(sorted(items, key=guide_sort_key), ensure_ascii=False))

    def save_guide_item(self, item: dict, original: dict | None = None) -> None:
        new = clean_guide_item(item)
        items = self.guide_items()
        key = lambda x: (int(x['day']), int(x['month']), str(x['title']).strip())
        if original:
            items = [x for x in items if key(x) != key(original)]
        if any(key(x) == key(new) for x in items):
            raise ValueError('Υπάρχει ήδη ημέρα με τον ίδιο τίτλο και την ίδια ημερομηνία.')
        items.append(new)
        self.set_guide_items(items)
        self.ensure_category(new['category'])

    def delete_guide_item(self, item: dict) -> None:
        k = (int(item['day']), int(item['month']), str(item['title']).strip())
        self.set_guide_items([x for x in self.guide_items() if (x['day'], x['month'], x['title']) != k])
        try:
            removed = json.loads(self.get_setting('guide_removed', '[]') or '[]')
        except ValueError:
            removed = []
        removed.append([k[0], k[1], k[2].casefold()])
        self.set_setting('guide_removed', json.dumps(removed, ensure_ascii=False))

    def reset_guide(self) -> None:
        self.set_setting('guide_removed', '[]')
        self.set_guide_items(merge_guide_items_with_defaults([]))

    # ---------------------------------------------------------- Ημερολόγιο Σχολικής Ζωής
    def lifelog_has_password(self) -> bool:
        return bool(self.get_setting('life_log_password_hash', ''))

    def lifelog_protected(self) -> bool:
        return self.get_bool('life_log_protection_enabled', True)

    def lifelog_set_password(self, password: str) -> None:
        if len(password or '') < 4:
            raise ValueError('Ο κωδικός πρέπει να έχει τουλάχιστον 4 χαρακτήρες.')
        self.set_setting('life_log_password_hash', hash_password(password))
        self.set_setting('life_log_password', '')
        self.set_bool('life_log_protection_enabled', True)

    def lifelog_check(self, password: str) -> bool:
        return verify_password(password or '', self.get_setting('life_log_password_hash', ''))

    def lifelog_list(self, search: str = '', date_from: str = '', date_to: str = '') -> list[dict]:
        sql, params = 'SELECT * FROM life_log WHERE 1=1', []
        if date_from:
            sql += ' AND log_date >= ?'; params.append(date_from)
        if date_to:
            sql += ' AND log_date <= ?'; params.append(date_to)
        sql += ' ORDER BY log_date ASC, id ASC'
        with self.lock:
            rows = [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        words = fold(search or '').split()
        return [r for r in rows if all(w in fold(r['description']) for w in words)] if words else rows

    def lifelog_save(self, data: dict) -> int:
        log_date = parse_date_to_iso(data.get('log_date') or '')
        desc = (data.get('description') or '').strip()
        if not desc:
            raise ValueError('Συμπληρώστε περιγραφή καταγραφής.')
        now = now_iso()
        with self.lock:
            if data.get('id'):
                self.conn.execute('UPDATE life_log SET log_date=?, description=?, updated_at=? WHERE id=?', (log_date, desc, now, int(data['id'])))
                lid = int(data['id'])
            else:
                lid = int(self.conn.execute('INSERT INTO life_log(log_date, description, source_action_id, created_at, updated_at) VALUES(?,?,?,?,?)',
                                            (log_date, desc, None, now, now)).lastrowid)
            self.conn.commit()
        return lid

    def lifelog_insert_many(self, records) -> int:
        now = now_iso()
        n = 0
        with self.lock:
            for r in records or []:
                desc = str(r.get('description') or '').strip()
                if not desc:
                    continue
                self.conn.execute('INSERT INTO life_log(log_date, description, source_action_id, created_at, updated_at) VALUES(?,?,?,?,?)',
                                  (parse_date_to_iso(r['log_date']), desc, None, now, now))
                n += 1
            self.conn.commit()
        return n

    def lifelog_years(self) -> list[str]:
        with self.lock:
            dates = [r[0] for r in self.conn.execute('SELECT DISTINCT log_date FROM life_log').fetchall()]
        return sorted({school_year_for_iso_date(d) for d in dates if d})

    def lifelog_suggest(self, target_iso: str, search: str = '', window: int = 10, limit: int = 40) -> dict:
        """Καταγραφές προηγούμενων σχολικών ετών: της ίδιας περιόδου (± window ημέρες) ή όσες ταιριάζουν στην αναζήτηση."""
        try:
            target = datetime.strptime(parse_date_to_iso(target_iso), '%Y-%m-%d').date()
        except ValueError:
            target = date.today()
        sy_start = school_year_bounds(school_year_of(target))[0].isoformat()
        with self.lock:
            rows = [dict(r) for r in self.conn.execute('SELECT * FROM life_log WHERE log_date < ? ORDER BY log_date DESC, id ASC', (sy_start,)).fetchall()]

        def offset(iso: str) -> int:
            d = datetime.strptime(iso, '%Y-%m-%d').date()
            best = None
            for y in (target.year - 1, target.year, target.year + 1):
                try:
                    diff = (d.replace(year=y) - target).days
                except ValueError:  # 29 Φεβρουαρίου
                    diff = (date(y, 2, 28) - target).days
                if best is None or abs(diff) < abs(best):
                    best = diff
            return best

        words = fold(search or '').split()
        items = {}
        for r in rows:
            off = offset(r['log_date'])
            if not words and abs(off) > window:
                continue
            for line in [x.strip() for x in str(r['description']).split('\n') if x.strip()]:
                if words and not all(w in fold(line) for w in words):
                    continue
                key = re.sub(r'\d+', '#', re.sub(r'[\s.,;:·\-‐–]+', ' ', fold(line))).strip()
                rank = (abs(off), -int(r['log_date'][:4]))
                it = items.get(key)
                if it is None:
                    items[key] = {'text': line, 'log_date': r['log_date'], 'offset': off, 'id': r['id'],
                                  'school_year': school_year_for_iso_date(r['log_date']), 'times': 1, '_rank': rank, '_dates': {r['log_date']}}
                else:
                    if r['log_date'] not in it['_dates']:
                        it['times'] += 1
                        it['_dates'].add(r['log_date'])
                    if rank < it['_rank']:
                        it.update(text=line, log_date=r['log_date'], offset=off, id=r['id'],
                                  school_year=school_year_for_iso_date(r['log_date']), _rank=rank)
        out = sorted(items.values(), key=lambda it: (it['_rank'], -it['times']) if not words else (-it['times'], it['_rank']))
        for it in out:
            it.pop('_rank'); it.pop('_dates')
        return {'items': out[:limit], 'total': len(out), 'has_history': bool(rows)}

    def lifelog_restore(self, rows) -> int:
        n = 0
        with self.lock:
            for r in rows or []:
                cur = self.conn.execute('INSERT OR IGNORE INTO life_log(id, log_date, description, source_action_id, created_at, updated_at) VALUES(?,?,?,?,?,?)',
                                        (int(r['id']), parse_date_to_iso(r['log_date']), str(r['description']), r.get('source_action_id'),
                                         r.get('created_at') or now_iso(), now_iso()))
                n += cur.rowcount or 0
            self.conn.commit()
        return n

    def lifelog_delete(self, ids) -> None:
        ids = [int(i) for i in ids]
        with self.lock:
            self.conn.execute(f'DELETE FROM life_log WHERE id IN ({",".join("?" for _ in ids)})', ids)
            self.conn.commit()

    def lifelog_transfer_completed(self) -> int:
        with self.lock:
            rows = self.conn.execute("""SELECT * FROM actions WHERE status='Ολοκληρώθηκε'
                   AND id NOT IN (SELECT source_action_id FROM life_log WHERE source_action_id IS NOT NULL)
                   ORDER BY action_date ASC, start_time ASC, id ASC""").fetchall()
        count = 0
        now = now_iso()
        with self.lock:
            for r in rows:
                title = (r['title'] or '').strip()
                sentence = 'Πραγματοποιήθηκε σχολική δράση' + (f' με τίτλο «{title}»' if title else '')
                details = []
                if (r['class_group'] or '').strip():
                    details.append(f"με συμμετοχή: {r['class_group'].strip()}")
                if (r['location'] or '').strip():
                    details.append(f"στον χώρο: {r['location'].strip()}")
                if (r['start_time'] or '').strip():
                    details.append('ώρα: ' + r['start_time'].strip() + (f" - {r['end_time'].strip()}" if (r['end_time'] or '').strip() else ''))
                if details:
                    sentence += ', ' + ', '.join(details)
                sentence += '.'
                if (r['description'] or '').strip():
                    sentence += ' ' + r['description'].strip()
                try:
                    self.conn.execute('INSERT INTO life_log(log_date, description, source_action_id, created_at, updated_at) VALUES(?,?,?,?,?)',
                                      (r['action_date'], sentence, int(r['id']), now, now))
                    count += 1
                except sqlite3.IntegrityError:
                    pass
            self.conn.commit()
        return count

    # ---------------------------------------------------------- αντίγραφα
    def backup_to(self, target) -> None:
        """Συνεπές αντίγραφο της βάσης (SQLite backup API)."""
        tmp = str(target) + '.tmp'
        with self.lock:
            dst = sqlite3.connect(tmp)
            try:
                self.conn.backup(dst)
            finally:
                dst.close()
        os.replace(tmp, target)

    def close(self) -> None:
        with self.lock:
            try:
                self.conn.close()
            except Exception:
                pass
