import re
import pandas as pd
from .base_validator import BaseValidator

class SpecialCharactersValidator(BaseValidator):

    def validate(self, df, column_name, special_characters_ref=None, **kwargs):
        if column_name not in df.columns:
            return (0, 0, None)
        if special_characters_ref is None:
            special_characters_ref = ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '_', '+', '=', '{', '}', '[', ']', '|', '\\', ':', ';', '"', "'", '<', '>', '?', '/', '~', '`']

        def has_special_chars(text):
            if pd.isna(text) or text == '':
                return False
            text_str = str(text)
            return any((char in text_str for char in special_characters_ref))
        check_mask = df[column_name].notna() & (df[column_name].astype(str).str.strip() != '')
        error_mask = check_mask & df[column_name].apply(has_special_chars)
        error_count = error_mask.sum()
        total_rows = check_mask.sum()
        error_df = self._prepare_error_dataframe(df, error_mask, 'CONFORMITY', f'Special characters found in column {column_name}')
        if error_df is not None and self.error_saver:
            self._save_errors_if_needed(error_df)
        return (total_rows, error_count, error_df)

class ConsecutiveSpacesValidator(BaseValidator):

    def validate(self, df, column_name, **kwargs):
        if column_name not in df.columns:
            return (0, 0, None)
        check_mask = df[column_name].notna() & (df[column_name].astype(str).str.strip() != '')
        check_mask = check_mask & (df[column_name].astype(str).str.strip().str.upper() != 'RESERVED')
        error_mask = check_mask & df[column_name].astype(str).str.contains('\\s{2,}', regex=True)
        error_count = error_mask.sum()
        total_rows = check_mask.sum()
        error_df = self._prepare_error_dataframe(df, error_mask, 'CONFORMITY', f'Consecutive spaces found in column {column_name}')
        if error_df is not None and self.error_saver:
            self._save_errors_if_needed(error_df)
        return (total_rows, error_count, error_df)

class UppercaseValidator(BaseValidator):

    def validate(self, df, column_name, country_column=None, excluded_countries=None, **kwargs):
        if column_name not in df.columns:
            return (0, 0, None)
        check_mask = df[column_name].notna() & (df[column_name].astype(str).str.strip() != '')
        non_reserved = df[column_name].astype(str).str.strip().str.upper() != 'RESERVED'
        check_mask = check_mask & non_reserved
        if country_column and country_column in df.columns and excluded_countries:
            excluded_upper = {str(c).strip().upper() for c in excluded_countries}
            excluded_mask = df[country_column].astype(str).str.strip().str.upper().isin(excluded_upper)
            check_mask = check_mask & ~excluded_mask
        error_mask = check_mask & (df[column_name].astype(str).str.strip() != df[column_name].astype(str).str.strip().str.upper())
        error_count = error_mask.sum()
        total_rows = check_mask.sum()
        error_df = self._prepare_error_dataframe(df, error_mask, 'CONFORMITY', f'Text should be in uppercase in column {column_name}')
        if error_df is not None and self.error_saver:
            self._save_errors_if_needed(error_df)
        return (total_rows, error_count, error_df)