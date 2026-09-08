"""Профили отчётов DQ: customer vs material (одна БД, разные rules + output)."""
from __future__ import annotations

import os
from typing import Any

REPORT_PROFILES: dict[str, dict[str, Any]] = {
    'customer': {
        'id': 'customer',
        'title': 'Customer / Equipment',
        'rules_rel': os.path.join('json files', 'rules.json'),
        'output_rel': 'quality_reports',
        'report_prefix': 'quality_check_report',
    },
    'material': {
        'id': 'material',
        'title': 'Material',
        'rules_rel': os.path.join('json files', 'material_rules.json'),
        'output_rel': 'Material report',
        'report_prefix': 'material_check_report',
    },
}

REPORT_CHOICES = ('customer', 'material', 'all')


def resolve_profile(project_root: str, profile_id: str) -> dict[str, Any]:
    pid = str(profile_id or '').strip().lower()
    if pid not in REPORT_PROFILES:
        raise ValueError(f'Неизвестный профиль отчёта: {profile_id!r}. Допустимо: {", ".join(REPORT_PROFILES)}')
    base = REPORT_PROFILES[pid]
    return {
        **base,
        'rules_file': os.path.join(project_root, base['rules_rel']),
        'output_dir': os.path.join(project_root, base['output_rel']),
    }


def list_profiles_help() -> str:
    lines = ['Доступные отчёты:']
    for pid, p in REPORT_PROFILES.items():
        lines.append(f"  {pid:10} — {p['title']}  (rules: {p['rules_rel']}, out: {p['output_rel']})")
    lines.append('  all        — оба отчёта подряд (одна БД)')
    return '\n'.join(lines)
