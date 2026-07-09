import pandas as pd
import logging
from typing import Dict, Any

class ADRCHandler:

    def __init__(self, table_name: str, df: pd.DataFrame, memory_manager, checker):
        self.table_name = table_name
        self.df = df
        self.memory_manager = memory_manager
        self.checker = checker
        self.logger = logging.getLogger('ADRCHandler')

    def validate_rule(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        error_count, total_rows = self.checker._process_single_rule_without_save(rule, self.table_name, self.df, timestamp)
        rule_code = rule.get('rule_code', 'UNKNOWN')
        rule_description = rule.get('rule_description', 'Unknown rule')
        quality_category = rule.get('quality_category', 'Unknown')
        column_checked = rule.get('column_name_checked', '')
        is_suspicious = self.checker._check_if_suspicious(rule_code, error_count, total_rows)
        key = f'{rule_code}_{self.table_name}'
        error_file_status = 'Нет'
        error_df = None
        if key in self.checker.rule_errors:
            error_file_status = 'Есть' if self.checker.rule_errors[key].get('error_df') is not None and (not self.checker.rule_errors[key].get('error_df').empty) else 'Нет'
            error_df = self.checker.rule_errors[key].get('error_df', None)
        if total_rows == 0:
            status = 'ОШИБКА ВЫПОЛНЕНИЯ'
            status_color = 'red'
            last_err = getattr(self.checker, '_last_rule_error', None)
            skip_reason = getattr(self.checker, '_last_rule_skip_reason', None)
            if last_err:
                comments = f'Ошибка: {last_err}'
                self.checker._last_rule_error = None
            elif skip_reason:
                comments = f'Пропущено: {skip_reason}'
                self.checker._last_rule_skip_reason = None
            elif str(rule_code or '').strip().upper() == 'RCCONF_24.1':
                st = getattr(self.checker, '_last_kna1_join_stats', {}) or {}
                comments = (
                    f'Правило не оценило ни одной строки. JOIN ADRC.[Addr. No.]->BUT020.[Business Partner]->KNA1.KTOKD: '
                    f"ключей совпало {st.get('key_matched', '?')}/{st.get('rows_after_join', '?')}, "
                    f"KTOKD заполнен: {st.get('filled_ktokd', '?')}."
                )
            elif str(rule_code or '').strip().upper() == 'RCCONF_21.1':
                comments = 'Правило не оценило ни одной строки: POST_CODE1 пуст у всех записей ADRC или колонка не найдена.'
            else:
                comments = 'Правило не смогло оценить ни одной строки (total_rows=0).'
        elif error_count == 0:
            status = 'УСПЕШНО'
            status_color = 'green'
            comments = ''
        elif is_suspicious:
            status = 'ПОДОЗРИТЕЛЬНО'
            status_color = 'orange'
            comments = ''
        else:
            status = 'ОШИБКИ'
            status_color = 'red'
            comments = ''
        return {'rule_code': rule_code, 'rule_description': rule_description, 'quality_category': quality_category, 'table_name': self.table_name, 'column_checked': column_checked, 'total_records': total_rows, 'passed': total_rows - error_count, 'failed': error_count, 'error_count': error_count, 'success_rate_%': round((total_rows - error_count) / total_rows * 100, 2) if total_rows > 0 else 0, 'execution_time_sec': 0, 'status': status, 'status_color': status_color, 'error_file': error_file_status, 'comments': comments, 'error_df': error_df}