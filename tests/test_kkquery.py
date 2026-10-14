"""Tests against a small, made-up database with the same tables as komplete.db3."""

import argparse
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kkquery  # noqa: E402

SCHEMA = """
CREATE TABLE k_bank_chain (id INTEGER PRIMARY KEY, bcvendor TEXT, entry1 TEXT NOT NULL, entry2 TEXT, entry3 TEXT);
CREATE TABLE k_sound_info (id INTEGER PRIMARY KEY, name TEXT NOT NULL, author TEXT, comment TEXT, vendor TEXT,
  device_type_flags INTEGER NOT NULL DEFAULT 0, bank_chain_id INTEGER, file_name TEXT NOT NULL, file_ext TEXT);
CREATE TABLE k_category (id INTEGER PRIMARY KEY, category TEXT, subcategory TEXT, subsubcategory TEXT);
CREATE TABLE k_sound_info_category (sound_info_id INTEGER, category_id INTEGER);
CREATE TABLE k_mode (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE k_sound_info_mode (sound_info_id INTEGER, mode_id INTEGER);
CREATE VIRTUAL TABLE f_sound_info USING fts5(name, author, brand, product, bank, subbank, type, character, comment);
"""

# Invented presets; none of these names come from a real library.
DATA = """
INSERT INTO k_bank_chain VALUES (1, '', 'Example Synth', 'Factory', ''), (2, 'Some Maker', 'Example Keys', 'Uprights', 'Felt');
INSERT INTO k_sound_info VALUES
  (1, 'Glass Pad', 'A. Author', '', 'Native Instruments', 1, 1, '/x/Glass Pad.nksn', 'nksn'),
  (2, 'Low Rumble', 'A. Author', '', 'Native Instruments', 1, 1, '/x/Low Rumble.nksn', 'nksn'),
  (3, 'Soft Felt', 'B. Author', 'quiet upright', '', 1, 2, '/x/Soft Felt.nki', 'nki'),
  (4, 'Hit 01', '', '', '', 4, NULL, '/x/Hit 01.wav', 'wav'),
  (5, 'Groove 90', '', '', '', 8, NULL, '/x/Groove 90.wav', 'wav'),
  (6, 'Stack', '', '', '', 0, 1, '/x/Stack.nkm', 'nkm');
INSERT INTO k_category VALUES (1, 'Synth Pad', 'Basic', NULL), (2, 'Bass', 'Synth Bass', NULL), (3, 'Piano', 'Upright', NULL);
INSERT INTO k_sound_info_category VALUES (1, 1), (2, 2), (3, 3);
INSERT INTO k_mode VALUES (1, 'Warm'), (2, 'Dark'), (3, 'Bright');
INSERT INTO k_sound_info_mode VALUES (1, 1), (1, 3), (2, 1), (2, 2), (3, 1);
INSERT INTO f_sound_info (rowid, name, author, product, type, character, comment) VALUES
  (1, 'Glass Pad', 'A. Author', 'Example Synth', 'Synth Pad', 'Warm, Bright', ''),
  (2, 'Low Rumble', 'A. Author', 'Example Synth', 'Bass', 'Warm, Dark', ''),
  (3, 'Soft Felt', 'B. Author', 'Example Keys', 'Piano', 'Warm', 'quiet upright');
"""


def args(**kw):
    base = dict(text=None, product=None, bank=None, brand=None, type=None, character=None, kind=None, limit=50)
    base.update(kw)
    return argparse.Namespace(**base)


class KKQueryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "komplete.db3")
        conn = sqlite3.connect(cls.path)
        conn.executescript(SCHEMA + DATA)
        conn.commit()
        conn.close()
        cls.conn = kkquery.connect(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def names(self, **kw):
        return [r["name"] for r in kkquery.search(self.conn, args(**kw))]

    def test_text_search_uses_prefixes(self):
        self.assertEqual(self.names(text="rumb"), ["Low Rumble"])
        self.assertEqual(self.names(text="quiet"), ["Soft Felt"])

    def test_character_tags_combine(self):
        self.assertEqual(self.names(character=["Warm"]), ["Glass Pad", "Low Rumble", "Soft Felt"])
        self.assertEqual(self.names(character=["warm", "dark"]), ["Low Rumble"])

    def test_type_matches_category_or_subcategory(self):
        self.assertEqual(self.names(type=["Bass"]), ["Low Rumble"])
        self.assertEqual(self.names(type=["upright"]), ["Soft Felt"])

    def test_product_bank_and_brand(self):
        self.assertEqual(self.names(product="Example Keys"), ["Soft Felt"])
        self.assertEqual(self.names(bank="Felt"), ["Soft Felt"])
        self.assertEqual(self.names(brand="Some Maker"), ["Soft Felt"])
        self.assertEqual(self.names(product="Example%", character=["Bright"]), ["Glass Pad"])

    def test_kinds(self):
        self.assertEqual(self.names(kind="one-shot"), ["Hit 01"])
        self.assertEqual(self.names(kind="loop"), ["Groove 90"])
        self.assertEqual(self.names(kind="multi"), ["Stack"])

    def test_rows_carry_types_and_characters(self):
        row = kkquery.search(self.conn, args(text="glass"))[0]
        self.assertEqual(row["types"], "Synth Pad / Basic")
        self.assertEqual(set(row["characters"].split(", ")), {"Warm", "Bright"})
        self.assertEqual(row["product"], "Example Synth")
        self.assertEqual(row["kind"], "instrument")

    def test_lists(self):
        values = [r["value"] for r in self.conn.execute(kkquery.LISTS["characters"])]
        self.assertEqual(values, ["Bright", "Dark", "Warm"])

    def test_database_opens_read_only(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.conn.execute("DELETE FROM k_mode")

    def test_fts_query_escapes_quotes(self):
        self.assertEqual(kkquery.fts_query('say "hi"'), '"say"* """hi"""*')


if __name__ == "__main__":
    unittest.main()
