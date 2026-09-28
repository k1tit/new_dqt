# MAKT text corruption in the monthly extract — request for UTF-8 re-export

**Raised by:** Data Quality team
**Scope:** table `MAKT`, column `MAKTX` (material description). Other text columns in the same extract are likely affected and must be re-checked after the re-export.
**Ask:** re-deliver the extract with UTF-8 encoding. No fix is possible on the consumer side.

## 1. Summary

A subset of `MAKTX` values in the delivered extract contains text that was damaged by
code page mis-decoding **before** it reached the Data Quality pipeline. The damage is not a
rendering or font issue: the stored characters themselves are wrong, so the original
description is no longer readable by a human or a machine.

Two distinct generations of damage are present, which means the same source text passed
through two different broken conversions — one of them possibly on a second ingestion of an
already damaged file.

A full scan of the loaded August extract found **33 damaged `MAKTX` values out of 711,650
rows**. 27 of them were produced by code pages the Data Quality loader never uses. The
remaining 6 use code pages the loader does contain, but a whole-file misread is inconsistent
with the other 711,617 rows staying intact, including valid Armenian and Greek text. The
damage is therefore in the extract as delivered.

This report shows the measured counts, the byte-level derivation, and what is required from
the source side.

## 2. Evidence

Measured on `db_august.db`, table `MAKT`, column `MAKTX`, all 711,650 rows
(`scripts/export_encoding_errors.py`). Counts by the conversion that reproduces the stored
value:

| Rows | Conversion | What it did to the original UTF-8 |
| --- | --- | --- |
| 13 | cp1252 | Western European misread, e.g. `Æ` (U+00C6) stored as `Ã†` |
| 10 | cp866 | DOS/OEM Cyrillic misread, e.g. `РЗ` stored as `╨а╨Ч` |
| 5 | cp1251 | Windows Cyrillic misread, e.g. `°` stored as `В°`, `£` stored as `ВЈ` |
| 4 | cp1252, then cp866 | the cp866 result above, re-read a second time |
| 1 | latin-1 | single-byte misread that kept C1 control characters |

Representative reversals from that scan (byte-correct, not a business rewrite):

| Value as delivered | Reconstructed original | Conversion |
| --- | --- | --- |
| `Hour satko Ã† 15` | `Hour satko Æ 15` | cp1252 |
| `Hour Glass Ã† 8 mm` | `Hour Glass Æ 8 mm` | cp1252 |
| `DICOLUBE ╨Т.╨Р. (PROD.)` | `DICOLUBE В.А. (PROD.)` | cp866 |
| `╨а╨Ч-STABISIP NA` | `РЗ-STABISIP NA` | cp866 |
| `POSTER В°1` | `POSTER °1` | cp1251 |
| `UMBRELLA 4*4ВЈ SPRITE` | `UMBRELLA 4*4£ SPRITE` | cp1251 |
| `Silicate reagent Ñ‚Ð”Ð¦ 2429600` | `Silicate reagent № 2429600` | cp1252, then cp866 |

The full `MANDT` / `MATNR` / `SPRAS` list is the CSV written by the same run.

Byte-level derivation of the double-encoded `№` case. `№` is U+2116, UTF-8 `E2 84 96`.

| Value as delivered | Original text | Conversion that produced it |
| --- | --- | --- |
| `Silicate reagent тДЦ 2429600` | `Silicate reagent № 2429600` | UTF-8 bytes read as **cp866** |
| `Silicate reagent Ñ‚Ð”Ð¦ 2429600` | `Silicate reagent № 2429600` | same as above, then re-read as **cp1252** |
| `╨а╨Ч-STABISIP NA` | `РЗ-STABISIP NA` | UTF-8 bytes read as **cp866** |
| `Additive to ink 8152-4â•¨Ðµ0.8L` | `Additive to ink 8152-4Х0.8L` | UTF-8 bytes read as **cp866**, then **cp1252** |

Generation 1 — the UTF-8 bytes of `№` decoded by candidate single-byte code pages:

| Code page | Result | Code points |
| --- | --- | --- |
| cp866 | `тДЦ` | U+0442 U+0414 U+0426 |
| cp1125 | `тДЦ` | U+0442 U+0414 U+0426 |
| cp1252 | `â„–` | U+00E2 U+201E U+2013 |
| cp1251 | `в„–` | U+0432 U+201E U+2013 |
| latin-1 | `â\x84\x96` | U+00E2 U+0084 U+0096 |
| cp437 | `Γäû` | U+0393 U+00E4 U+00FB |

Only **cp866** and **cp1125** (DOS/OEM Cyrillic) reproduce the delivered value `тДЦ`.

Generation 2 — the UTF-8 bytes of the already damaged `тДЦ` (`D1 82 D0 94 D0 A6`) decoded again:

| Code page | Result |
| --- | --- |
| cp1252 | `Ñ‚Ð”Ð¦` — matches the delivered value |
| latin-1 | `Ñ\x82Ð\x94Ð¦` — C1 control characters, does not match |
| cp1251 | `С‚Р”Р¦` — does not match |
| cp866 | `╤В╨Ф╨ж` — does not match |

Only **cp1252** reproduces the delivered value `Ñ‚Ð”Ð¦`.

## 3. Why this is not a whole-table misread by the Data Quality pipeline

The DQ CSV loader attempts exactly four code pages, in this order, and keeps the first one
that decodes the **whole file**: `utf-8-sig`, `utf-8`, `cp1251`, `latin-1`. It never uses
cp866 or cp1252.

* The 13 cp1252 rows, the 10 cp866 rows and the 4 double-encoded rows (27 of 33) cannot be
  produced by that list. For the double-encoded `Ñ‚Ð”Ð¦` case specifically, the loader's
  `latin-1` yields C1 control characters (U+0082, U+0094) and its `cp1251` yields `С‚Р”Р¦`.
  Neither matches what was delivered.
* The 5 cp1251 rows and the 1 latin-1 row do use code pages the loader contains. Producing
  them would require the UTF-8 decode of an entire file to fail, after which every non-ASCII
  character in that file would be damaged the same way. That did not happen: 711,617 of
  711,650 rows are intact, including Armenian (`Թարթիչ`) and Greek (`ΚΑΦΕΣ`) descriptions,
  which a cp1251 or latin-1 read of a UTF-8 file would have destroyed.
* Excel files are not a possible origin either: `.xlsx` is read through openpyxl, and the XML
  payload inside an `.xlsx` container is always UTF-8, so no code page guessing takes place.

Conclusion: the 27 rows are upstream of the DQ pipeline. The other 6 are damaged the same
way cell by cell and are not the result of the loader falling through on this table. The
residual risk is a separate small file loaded through the fallback; the loader still should
stop guessing and log the code page it chose.

## 4. Most likely root cause

The three single-byte code pages point at three different save paths applied to correct UTF-8:

* **cp866** (10 rows) is DOS/OEM Cyrillic. It appears when a UTF-8 file is re-saved from Excel
  as **"CSV (MS-DOS)"** or **"Text (OEM)"** on a Cyrillic locale, or a download step is set to
  an OEM code page.
* **cp1252** (13 rows, the largest group) is the Western European default. It appears when the
  same file is opened or saved by a tool whose default is Windows-1252, which is what produces
  `Æ` → `Ã†`.
* **cp1251** (5 rows) is Windows Cyrillic, the same class of mistake on a Cyrillic locale
  (`°` → `В°`, `£` → `ВЈ`).

The 4 rows with `cp1252` on top of `cp866` mean an already damaged file was processed again.

## 5. What is required from the source side

1. Re-export `MAKT` with **UTF-8** encoding.
   * SAP `GUI_DOWNLOAD` / `GUI_UPLOAD`: code page **4110** (UTF-8).
   * SAP GUI list export: choose the spreadsheet or unconverted format and save as UTF-8.
   * If Excel is part of the chain: save as **"CSV UTF-8 (comma delimited)"**, never
     "CSV (MS-DOS)" or "Text (OEM)".
2. Do not open and re-save the delivered file in any intermediate tool.
3. Confirm which encoding the export job is configured with, so the same issue does not
   recur in the next monthly delivery.

## 6. Why we will not repair the values ourselves

Reversing the damage is possible for the patterns above, but it is a heuristic and it is not
safe to apply to stored data:

* Generation 1 damage turns a symbol into a sequence of plausible Cyrillic letters
  (`№` becomes `тДЦ`). Such a value is indistinguishable from legitimate Cyrillic text
  without knowing the source code page, so any automated repair risks silently rewriting
  valid descriptions.
* The extract is the system of record for the DQ process. Values must stay exactly as
  delivered so that findings remain traceable to the source.

Damaged rows will therefore continue to be reported as data quality findings until a clean
extract is delivered.

## 7. Note on non-English descriptions (separate issue, not corruption)

Descriptions such as `Թարթիչ կողային ATEGO` (Armenian), `ΚΑΦΕΣ ΦΙΛΤΡΟΥ` (Greek) or
`РЗ-STABISIP NA` (Cyrillic) are stored correctly — these are valid Unicode code points with
no loss of information. They are reported by the uppercase rule only because those scripts
have letter case, and they represent a different problem: a non-English description
maintained under the English language key `SPRAS = 'E'`. This must not be confused with the
encoding damage described above.

## 8. Reproducing the analysis

```python
raw = '№'.encode('utf-8')
print(raw.decode('cp866'))        # тДЦ
print('тДЦ'.encode('utf-8').decode('cp1252'))  # Ñ‚Ð”Ð¦
print('╨а╨Ч-STABISIP NA'.encode('cp866').decode('utf-8'))  # РЗ-STABISIP NA
```

## 9. Scope of this measurement

Counted on 23 Sep 2026 against `db_august.db`: 711,650 `MAKT` rows, 33 damaged `MAKTX`
values, broken down in section 2. The per-material list (`MANDT`, `MATNR`, `SPRAS`, delivered
value, reconstructed original, codec chain) is the export produced by:

```text
python scripts/export_encoding_errors.py --table MAKT --columns MAKTX --format xlsx
```

Other text columns in the same extract have not been scanned yet. Run the same script with
`--all-tables` before treating `MAKT` as the only affected table.
