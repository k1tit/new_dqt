import os
import runpy
import sys
_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'add_table.py')
if not os.path.isfile(_SCRIPT):
    print(f'ОШИБКА: не найден {_SCRIPT}')
    sys.exit(1)
runpy.run_path(_SCRIPT, run_name='__main__')