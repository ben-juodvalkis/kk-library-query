# kk-library-query

Search your Komplete Kontrol / Kontakt preset library from the command line, by
text, product, bank, type and character tags.

Native Instruments' browser keeps everything it knows about your installed
presets in a SQLite file called `komplete.db3`. This tool reads that file, on
your own machine, read-only. It doesn't change it, copy it, or send it anywhere.

One Python file, no dependencies beyond Python 3.8+.

```sh
python3 kkquery.py where                          # which database was found
python3 kkquery.py search "glass pad"             # free text, every word as a prefix
python3 kkquery.py search --type Bass --character Dark --character Warm
python3 kkquery.py search --product "Massive X" --kind instrument --format csv > massive.csv
python3 kkquery.py list types                     # every type tag, with counts
python3 kkquery.py list characters
```

Example output (made-up presets):

```
name        brand               product        bank      types               characters    kind
Glass Pad   Native Instruments  Example Synth  Factory   Synth Pad / Basic   Warm, Bright  instrument
Low Rumble  Native Instruments  Example Synth  Factory   Bass / Synth Bass   Warm, Dark    instrument
```

Filters are case-insensitive, and `%` works as a wildcard (`--product "Example%"`).
Repeat `--type` or `--character` to require several. `--format json` includes the
full file path of each preset.

## Where the database is

The tool looks in these places and uses the most recently modified match. Pass
`--db` to choose one yourself.

| System  | Location                                                                 |
| ------- | ------------------------------------------------------------------------ |
| macOS   | `~/Library/Application Support/Native Instruments/<app>/komplete.db3`    |
| macOS   | `~/Library/Application Support/Native Instruments/<app>/Browser Data/komplete.db3` (older) |
| Windows | `%LOCALAPPDATA%\Native Instruments\<app>\komplete.db3`                   |

`<app>` has been `Komplete Kontrol` and `Kontakt 8`, depending on what's installed
and which version wrote it. The Windows path is untested.

## How the database is laid out

Worked out by reading the file's own schema. Native Instruments doesn't document
it and can change it in any update.

| Table                   | What it holds                                                                    |
| ----------------------- | -------------------------------------------------------------------------------- |
| `k_sound_info`          | One row per preset: `name`, `author`, `comment`, `vendor`, `file_name` (full path), `file_ext`, `device_type_flags`, `bank_chain_id` |
| `k_bank_chain`          | Where the preset sits in the browser: `bcvendor` (brand), `entry1` (product), `entry2` (bank), `entry3` (sub-bank) |
| `k_category`            | Type tags: `category`, `subcategory`, `subsubcategory`                           |
| `k_sound_info_category` | Links presets to type tags (many to many)                                        |
| `k_mode`                | Character tags: Warm, Dark, Percussive, Sparse…                                  |
| `k_sound_info_mode`     | Links presets to character tags (many to many)                                   |
| `k_content_path`        | Library folders the browser scans                                                |
| `v_sound_info`          | NI's own view joining the above into one row per preset                          |
| `f_sound_info`          | NI's own FTS5 full-text index over that view; `search` uses it when present     |

`device_type_flags` is a bit field. The browser's own triggers read bit 1 as
instrument, 4 as one-shot and 8 as loop. Multis (`.nkm`), tools (`.nkt`) and
Leap kits (`.nkl`) are told apart by file extension instead.

Brand comes from `k_bank_chain.bcvendor` when it's set and is otherwise Native
Instruments, which is how NI's own view works it out.

## What this doesn't do

It doesn't load presets into Komplete Kontrol or Kontakt, and it doesn't read
the preset files themselves. It only reads the browser's index.

## Not affiliated

This is an independent project. It is not made, endorsed or supported by Native
Instruments. Komplete Kontrol, Kontakt and Native Instruments are their
trademarks, used here only to say what the tool works with. Check your own
licence terms before using it; you use it at your own risk.

## Licence

MIT. See [LICENSE](LICENSE).
