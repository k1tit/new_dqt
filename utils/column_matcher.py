import pandas as pd
'Утилиты для поиска соответствия колонок'
'Маппер для поиска колонок в таблицах - ИСПРАВЛЕННАЯ ВЕРСИЯ'

class ColumnMatcher:

    def __init__(self):
        self.cache = {}

    def find_column_match(self, available_columns, target_column):
        cols_key = ','.join(sorted(available_columns))
        cache_key = f'{cols_key}:{target_column}'
        if cache_key in self.cache:
            return self.cache[cache_key]
        target_lower = target_column.lower().strip()
        target_variants = [target_lower, target_lower.replace('_', ''), target_lower.replace('_', ' '), target_lower.replace(' ', '_')]
        for col in available_columns:
            col_lower = col.lower()
            if col_lower == target_lower:
                self.cache[cache_key] = col
                return col
            col_simple = col_lower.replace('_', '').replace(' ', '')
            target_simple = target_lower.replace('_', '').replace(' ', '')
            if col_simple == target_simple:
                self.cache[cache_key] = col
                return col
            if target_simple in col_simple and len(target_simple) > 3:
                self.cache[cache_key] = col
                return col
        self.cache[cache_key] = None
        return None

    def find_match(self, available_columns, target_column):
        return self.find_column_match(available_columns, target_column)

    def match_column(self, available_columns, target_column):
        return self.find_column_match(available_columns, target_column)