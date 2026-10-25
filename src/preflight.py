"""Έλεγχος εκκίνησης: Python, SQLite, θέση δεδομένων. Γράφει διαγνωστικό στο %LOCALAPPDATA%\\ProgrammaDraseon\\diagnostics.txt."""
import os, platform, sqlite3, struct, sys, tempfile, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
lines = []
try:
    import core, exports, reports, storage, updater, server  # noqa: F401
    lines.append('Πρόγραμμα Δράσεων Σχολείου ' + core.VERSION)
    lines.append('Python: %s (%d-bit) σε %s' % (sys.version.split()[0], struct.calcsize('P') * 8, platform.platform()))
    lines.append('SQLite: ' + sqlite3.sqlite_version)
    with tempfile.TemporaryDirectory() as t:
        db = core.Database(Path(t) / 'test.db')
        db.save_action({'action_date': '2026-10-28', 'title': 'Δοκιμή'})
        assert len(db.list_actions({'search': 'δοκιμη'})) == 1
        exports.export(db, 'ics', db.list_actions())
        reports.actions_report(db, {'type': 'all', 'school_year': '2026-2027'})
        db.close()
    root, source = storage.data_root()
    lines.append('Φάκελος δεδομένων: %s (%s)' % (root, source))
    lines.append('Έγγραφα: %s' % storage.documents_dir())
    lines.append('Παράθυρο εφαρμογής: %s' % (server.find_browser() or 'προεπιλεγμένος browser'))
    lines.append('OK')
    text = '\n'.join(lines)
    print(text)
    code = 0
except Exception:
    text = '\n'.join(lines) + '\n' + traceback.format_exc()
    print(text)
    code = 1
try:
    import storage as _s
    (_s.machine_dir() / 'diagnostics.txt').write_text(text, encoding='utf-8')
except Exception:
    pass
sys.exit(code)
