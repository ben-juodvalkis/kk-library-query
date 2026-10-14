#!/usr/bin/env python3
"""Search the Komplete Kontrol / Kontakt browser database from the command line.

Reads the `komplete.db3` SQLite file that Native Instruments' browser keeps on
your own machine, read-only. Nothing is modified and nothing is copied.

    python3 kkquery.py where
    python3 kkquery.py search "warm pad" --character Dark --limit 20
    python3 kkquery.py search --product "Kontakt 8 Factory Content" --type Piano
    python3 kkquery.py list types
"""

import argparse
import csv
import glob
import json
import os
import sqlite3
import sys
from urllib.parse import quote

__version__ = "0.1.0"

# device_type_flags bits, as used by the browser's own triggers in komplete.db3
KIND_BITS = {"instrument": 1, "one-shot": 4, "loop": 8}

# Kinds without a flag bit are told apart by file extension
KIND_EXTENSIONS = {
    "multi": ("nkm",),
    "tool": ("nkt",),
    "leap": ("nkl",),
}

COLUMNS = ["name", "brand", "product", "bank", "subbank", "types", "characters", "kind", "author", "file"]


def candidate_paths():
    """Places the browser database lives, newest Native Instruments layouts first."""
    roots = []
    if sys.platform == "darwin":
        roots.append(os.path.expanduser("~/Library/Application Support/Native Instruments"))
    elif os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.append(os.path.join(local, "Native Instruments"))
    patterns = []
    for root in roots:
        patterns.append(os.path.join(root, "*", "komplete.db3"))
        patterns.append(os.path.join(root, "*", "Browser Data", "komplete.db3"))
    found = []
    for pattern in patterns:
        found.extend(glob.glob(pattern))
    return sorted(set(found), key=os.path.getmtime, reverse=True)


def find_database(explicit=None):
    if explicit:
        if not os.path.exists(explicit):
            sys.exit(f"No database at {explicit}")
        return explicit
    found = candidate_paths()
    if not found:
        sys.exit("Couldn't find komplete.db3. Pass its location with --db.")
    if len(found) > 1:
        print(f"Using {found[0]} (newest of {len(found)}; pick another with --db)", file=sys.stderr)
    return found[0]


def connect(path):
    conn = sqlite3.connect(f"file:{quote(os.path.abspath(path))}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None


def fts_query(text):
    """Turn free text into an FTS5 query: every word must match, as a prefix."""
    words = [w for w in text.split() if w]
    return " ".join('"%s"*' % w.replace('"', '""') for w in words)


BASE_SELECT = """
SELECT
  s.id,
  s.name,
  CASE WHEN coalesce(b.bcvendor, '') != '' THEN b.bcvendor ELSE coalesce(s.vendor, '') END AS brand,
  coalesce(b.entry1, '') AS product,
  coalesce(b.entry2, '') AS bank,
  coalesce(b.entry3, '') AS subbank,
  (SELECT group_concat(c.category || coalesce(' / ' || nullif(c.subcategory, ''), '')
                       || coalesce(' / ' || nullif(c.subsubcategory, ''), ''), '; ')
     FROM k_sound_info_category sc JOIN k_category c ON c.id = sc.category_id
    WHERE sc.sound_info_id = s.id) AS types,
  (SELECT group_concat(m.name, ', ')
     FROM k_sound_info_mode sm JOIN k_mode m ON m.id = sm.mode_id
    WHERE sm.sound_info_id = s.id) AS characters,
  s.device_type_flags,
  s.file_ext,
  coalesce(s.author, '') AS author,
  s.file_name AS file
FROM k_sound_info s
LEFT JOIN k_bank_chain b ON b.id = s.bank_chain_id
"""


def kind_of(flags, ext):
    ext = (ext or "").lower()
    for kind, exts in KIND_EXTENSIONS.items():
        if ext in exts:
            return kind
    for kind, bit in KIND_BITS.items():
        if flags & bit:
            return kind
    return ""


def build_search(args, use_fts):
    where, params = [], []
    if args.text:
        if use_fts:
            where.append("s.id IN (SELECT rowid FROM f_sound_info WHERE f_sound_info MATCH ?)")
            params.append(fts_query(args.text))
        else:
            for word in args.text.split():
                where.append("(s.name LIKE ? OR s.comment LIKE ? OR s.author LIKE ?)")
                params += [f"%{word}%"] * 3
    if args.product:
        where.append("b.entry1 LIKE ?")
        params.append(args.product)
    if args.bank:
        where.append("(b.entry2 LIKE ? OR b.entry3 LIKE ?)")
        params += [args.bank, args.bank]
    if args.brand:
        where.append("(CASE WHEN coalesce(b.bcvendor, '') != '' THEN b.bcvendor ELSE s.vendor END) LIKE ?")
        params.append(args.brand)
    for t in args.type or []:
        where.append(
            "EXISTS (SELECT 1 FROM k_sound_info_category sc JOIN k_category c ON c.id = sc.category_id"
            " WHERE sc.sound_info_id = s.id AND (c.category LIKE ? OR c.subcategory LIKE ? OR c.subsubcategory LIKE ?))"
        )
        params += [t, t, t]
    for ch in args.character or []:
        where.append(
            "EXISTS (SELECT 1 FROM k_sound_info_mode sm JOIN k_mode m ON m.id = sm.mode_id"
            " WHERE sm.sound_info_id = s.id AND m.name LIKE ?)"
        )
        params.append(ch)
    if args.kind:
        if args.kind in KIND_BITS:
            where.append("(s.device_type_flags & ?) != 0")
            params.append(KIND_BITS[args.kind])
        else:
            exts = KIND_EXTENSIONS[args.kind]
            where.append("lower(s.file_ext) IN (%s)" % ",".join("?" * len(exts)))
            params += list(exts)
    sql = BASE_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY s.name COLLATE NOCASE LIMIT ?"
    params.append(args.limit)
    return sql, params


def search(conn, args):
    use_fts = has_table(conn, "f_sound_info")
    sql, params = build_search(args, use_fts)
    rows = []
    for r in conn.execute(sql, params):
        row = {k: r[k] for k in ("name", "brand", "product", "bank", "subbank", "author", "file")}
        row["types"] = r["types"] or ""
        row["characters"] = r["characters"] or ""
        row["kind"] = kind_of(r["device_type_flags"] or 0, r["file_ext"])
        rows.append(row)
    return rows


LISTS = {
    "products": ("SELECT entry1 AS value, count(*) AS n FROM k_sound_info s JOIN k_bank_chain b ON b.id = s.bank_chain_id"
                 " WHERE entry1 != '' GROUP BY entry1 ORDER BY entry1 COLLATE NOCASE"),
    "banks": ("SELECT entry1 || ' / ' || entry2 AS value, count(*) AS n FROM k_sound_info s JOIN k_bank_chain b"
              " ON b.id = s.bank_chain_id WHERE coalesce(entry2, '') != '' GROUP BY entry1, entry2"
              " ORDER BY value COLLATE NOCASE"),
    "brands": ("SELECT CASE WHEN coalesce(b.bcvendor, '') != '' THEN b.bcvendor ELSE coalesce(s.vendor, '') END AS value,"
               " count(*) AS n FROM k_sound_info s LEFT JOIN k_bank_chain b ON b.id = s.bank_chain_id"
               " GROUP BY value HAVING value != '' ORDER BY value COLLATE NOCASE"),
    "types": ("SELECT c.category || coalesce(' / ' || nullif(c.subcategory, ''), '') AS value, count(*) AS n"
              " FROM k_sound_info_category sc JOIN k_category c ON c.id = sc.category_id"
              " GROUP BY value ORDER BY value COLLATE NOCASE"),
    "characters": ("SELECT m.name AS value, count(*) AS n FROM k_sound_info_mode sm JOIN k_mode m ON m.id = sm.mode_id"
                   " GROUP BY m.name ORDER BY m.name COLLATE NOCASE"),
}


def print_rows(rows, fmt, columns):
    if fmt == "json":
        json.dump(rows, sys.stdout, indent=2, ensure_ascii=False)
        print()
    elif fmt == "csv":
        w = csv.DictWriter(sys.stdout, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    else:
        if not rows:
            print("No matches.")
            return
        shown = [c for c in columns if c != "file"]
        widths = {c: min(32, max(len(c), *(len(str(r.get(c, ""))) for r in rows))) for c in shown}
        print("  ".join(c.ljust(widths[c]) for c in shown))
        for r in rows:
            print("  ".join(str(r.get(c, ""))[: widths[c]].ljust(widths[c]) for c in shown))


def main(argv=None):
    p = argparse.ArgumentParser(description="Search the Komplete Kontrol / Kontakt browser database (read-only).")
    p.add_argument("--db", help="path to komplete.db3 (found automatically on macOS and Windows)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("where", help="show which database files were found")

    s = sub.add_parser("search", help="find presets by text, product, type or character")
    s.add_argument("text", nargs="?", help="words to match in name, author, product, bank, type, character or comment")
    s.add_argument("--product", help="product, e.g. 'Massive X' (case-insensitive; % is a wildcard)")
    s.add_argument("--bank", help="bank or sub-bank")
    s.add_argument("--brand", help="maker, e.g. 'Native Instruments'")
    s.add_argument("--type", action="append", help="type or sub-type, e.g. Bass or 'Synth Lead'; repeat to require several")
    s.add_argument("--character", action="append", help="character tag, e.g. Dark or Warm; repeat to require several")
    s.add_argument("--kind", choices=sorted(list(KIND_BITS) + list(KIND_EXTENSIONS)))
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--format", choices=["table", "json", "csv"], default="table")

    l = sub.add_parser("list", help="list every product, bank, brand, type or character, with counts")
    l.add_argument("what", choices=sorted(LISTS))
    l.add_argument("--format", choices=["table", "json", "csv"], default="table")

    args = p.parse_args(argv)

    if args.command == "where":
        paths = [args.db] if args.db else candidate_paths()
        if not paths:
            print("No komplete.db3 found.")
        for path in paths:
            conn = connect(path)
            n = conn.execute("SELECT count(*) FROM k_sound_info").fetchone()[0]
            print(f"{path}  ({n:,} presets)")
        return

    conn = connect(find_database(args.db))
    if args.command == "search":
        print_rows(search(conn, args), args.format, COLUMNS)
    else:
        rows = [{"value": r["value"], "count": r["n"]} for r in conn.execute(LISTS[args.what])]
        print_rows(rows, args.format, ["value", "count"])


if __name__ == "__main__":
    main()
