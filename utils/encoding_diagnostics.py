"""Детектор текста, испорченного неверной кодировкой (mojibake).

Логика: round-trip репар. Значение перекодируется обратно в однобайтовую кодировку
и читается как UTF-8. Результат принимается только если он объективно «чище»
исходного по двум метрикам:

  1. marker_score  — символы, которых не бывает в нормальном тексте номенклатуры:
                     псевдографика U+2500..U+257F, C1-контролы U+0080..U+009F,
                     U+FFFD, а также пары вида `Ã`/`Ð`/`Ñ`/`â` + ещё один не-ASCII;
  2. script_transitions — число переключений письменности между буквами.

Порог — строгое улучшение пары (marker_score, script_transitions). Это даёт нулевой
процент ложных срабатываний на валидном тексте (армянский, греческий, кириллица,
венгерский, чешский, `№`, `45µM`), потому что корректный текст либо вообще не
кодируется в однобайтовую кодировку, либо его байты не являются валидным UTF-8,
либо репар не улучшает метрики.

Модуль ничего не меняет в данных: он только сообщает, что значение испорчено,
и показывает наиболее вероятный оригинал для перезапроса выгрузки.
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from typing import Iterable, List, Optional, Sequence, Tuple

import pandas as pd

MOJIBAKE_CODECS: Tuple[str, ...] = ('cp1252', 'latin-1', 'cp866', 'cp1125', 'cp1251', 'cp437')
MARKER_RANGES: Tuple[Tuple[int, int], ...] = ((0x2500, 0x257F), (0x0080, 0x009F))
MARKER_LEADS = frozenset('ÃÐÑÂâãÅå')
MARKER_WEIGHT = 5
MAX_REPAIR_ROUNDS = 4


def _is_marker_codepoint(cp: int) -> bool:
    if cp == 0xFFFD:
        return True
    return any(lo <= cp <= hi for lo, hi in MARKER_RANGES)


def marker_score(text: str) -> int:
    """Вес символов, характерных только для испорченной перекодировки."""
    score = 0
    last = len(text) - 1
    for i, ch in enumerate(text):
        if _is_marker_codepoint(ord(ch)):
            score += MARKER_WEIGHT
        elif ch in MARKER_LEADS and i < last and ord(text[i + 1]) > 0x7F:
            score += MARKER_WEIGHT
    return score


@lru_cache(maxsize=8192)
def _script_of(ch: str) -> str:
    if not ch.isalpha():
        return ''
    try:
        return unicodedata.name(ch).split()[0]
    except ValueError:
        return 'UNKNOWN'


def script_transitions(text: str) -> int:
    """Сколько раз подряд идущие буквы меняют письменность."""
    scripts = [s for s in (_script_of(ch) for ch in text) if s]
    return sum(1 for a, b in zip(scripts, scripts[1:]) if a != b)


def _quality(text: str) -> Tuple[int, int]:
    return (marker_score(text), script_transitions(text))


def _repair_once(text: str, codecs: Sequence[str]) -> Tuple[Optional[str], Optional[str]]:
    current = _quality(text)
    for enc in codecs:
        try:
            raw = text.encode(enc)
        except UnicodeEncodeError:
            continue
        try:
            candidate = raw.decode('utf-8')
        except UnicodeDecodeError:
            continue
        if candidate == text:
            continue
        if _quality(candidate) < current:
            return candidate, enc
    return None, None


def repair_text(
    text: str,
    codecs: Sequence[str] = MOJIBAKE_CODECS,
    max_rounds: int = MAX_REPAIR_ROUNDS,
) -> Tuple[str, List[str]]:
    """Возвращает (наиболее вероятный оригинал, цепочка кодировок порчи).

    Пустая цепочка означает, что значение не выглядит испорченным.
    """
    chain: List[str] = []
    current = text
    for _ in range(max(1, int(max_rounds))):
        candidate, enc = _repair_once(current, codecs)
        if candidate is None or enc is None:
            break
        chain.append(enc)
        current = candidate
    return current, chain


def looks_damaged(value: object) -> bool:
    text = '' if value is None else str(value)
    if not text or text.isascii():
        return False
    return bool(repair_text(text)[1])


def _damaged_fragment(before: str, after: str) -> Tuple[str, str]:
    """Минимальный различающийся фрагмент: обрезает общий префикс и суффикс."""
    start = 0
    limit = min(len(before), len(after))
    while start < limit and before[start] == after[start]:
        start += 1
    end_before, end_after = len(before), len(after)
    while end_before > start and end_after > start and before[end_before - 1] == after[end_after - 1]:
        end_before -= 1
        end_after -= 1
    return (before[start:end_before], after[start:end_after])


def codepoints(text: str) -> str:
    return ' '.join(f'U+{ord(ch):04X}' for ch in text)


def inspect_value(value: object) -> Optional[dict]:
    """Диагностика одного значения. None — значение не выглядит испорченным."""
    text = '' if value is None else str(value)
    if not text or text.isascii():
        return None
    repaired, chain = repair_text(text)
    if not chain:
        return None
    fragment, fragment_fixed = _damaged_fragment(text, repaired)
    return {
        'value_as_delivered': text,
        'suggested_original': repaired,
        'codec_chain': ' -> '.join(chain),
        'damaged_fragment': fragment,
        'fragment_suggested': fragment_fixed,
        'fragment_codepoints': codepoints(fragment),
        'marker_score': marker_score(text),
        'script_transitions': script_transitions(text),
    }


def non_ascii_mask(series: pd.Series) -> pd.Series:
    """Быстрый предфильтр: строки, где вообще есть не-ASCII символы."""
    return series.astype(str).str.contains(r'[^\x00-\x7F]', regex=True, na=False)


def inspect_frame(
    df: pd.DataFrame,
    columns: Iterable[str],
    key_columns: Sequence[str] = (),
    table: Optional[str] = None,
) -> List[dict]:
    """Диагностика набора колонок DataFrame. Возвращает список находок."""
    findings: List[dict] = []
    if df.empty:
        return findings
    keys = [c for c in key_columns if c in df.columns]
    for column in columns:
        if column not in df.columns:
            continue
        series = df[column]
        candidates = series[non_ascii_mask(series)]
        if candidates.empty:
            continue
        for idx, value in candidates.items():
            finding = inspect_value(value)
            if finding is None:
                continue
            row = {'table': table or '', 'column': column}
            for key in keys:
                row[key] = df.at[idx, key]
            row.update(finding)
            findings.append(row)
    return findings
