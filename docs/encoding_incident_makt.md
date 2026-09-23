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

This report shows the byte-level derivation for each case, proves that the Data Quality
loader cannot be the origin, and lists what is required from the source side.

## 2. Evidence

Byte-level derivation of the four confirmed patterns. `№` is U+2116, whose UTF-8
representation is `E2 84 96`.

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

## 3. Why the Data Quality pipeline is not the origin

The DQ CSV loader attempts exactly four code pages, in this order:
`utf-8-sig`, `utf-8`, `cp1251`, `latin-1`.

Neither cp866, nor cp1125, nor cp1252 is among them:

* Generation 1 requires cp866 or cp1125 — the loader never uses either, so it cannot
  produce `тДЦ` from a correct UTF-8 file.
* Generation 2 requires cp1252 specifically — the loader's `latin-1` yields C1 control
  characters (U+0082, U+0094) instead of `‚` and `”`, and its `cp1251` yields `С‚Р”Р¦`.
  Neither matches what was delivered.

Excel files are not a possible origin either: `.xlsx` is read through openpyxl, and the XML
payload inside an `.xlsx` container is always UTF-8, so no code page guessing takes place.

Conclusion: both generations of damage occurred upstream of the DQ pipeline.

## 4. Most likely root cause

cp866 is the DOS/OEM Cyrillic code page. In practice it appears in exactly one common
workflow: a correct UTF-8 file is opened in Excel and re-saved as **"CSV (MS-DOS)"** or
**"Text (OEM)"** on a Cyrillic locale, or a download step is configured with an OEM code page
instead of UTF-8.

The cp1252 layer on top indicates that an already damaged file was later processed again by a
tool defaulting to Windows-1252.

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

## 9. Open item

The exact number of affected rows and the full `MATNR` list are not included yet: they
require a query against the loaded monthly database, which was not available when this
report was written. They will be attached as soon as the database is accessible.
