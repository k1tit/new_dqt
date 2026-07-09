import pandas as pd
from datetime import datetime
from .base_validator import BaseValidator

class DateValidator(BaseValidator):

    def validate(self, df, column_name, technical_definition=None, **kwargs):
        if column_name not in df.columns:
            return (0, 0, None)
        total_rows = len(df)
        error_mask = df[column_name].isna()
        error_count = error_mask.sum()
        error_df = self._prepare_error_dataframe(df, error_mask, 'CONFORMITY', f'Invalid date in {column_name}')
        if error_df is not None and self.error_saver:
            self._save_errors_if_needed(error_df)
        return (total_rows, error_count, error_df)