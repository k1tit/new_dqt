EXCEL_SYMBOLS = {'SUCCESS': chr(9989), 'ERROR': chr(10060), 'WARNING': chr(9888), 'INFO': chr(8505), 'SKIP': chr(9197), 'ROCKET': chr(128640), 'GEAR': chr(9881), 'MAGNIFYING_GLASS': chr(128269), 'CHECKMARK': chr(10003), 'CHART_UP': chr(128200), 'CHART_DOWN': chr(128201), 'CLIPBOARD': chr(128203), 'FILE_FOLDER': chr(128193), 'PAGE': chr(128196), 'TABLE': chr(128188), 'COLUMN': chr(128209), 'BOOKS': chr(128218), 'SAVE': chr(128190), 'TARGET': chr(127919), 'PALETTE': chr(127912), 'CELEBRATION': chr(127881), 'BAR_CHART': chr(128202), 'MEMO': chr(128221)}
TERMINAL_SYMBOLS = {'SUCCESS': '[OK]', 'ERROR': '[ERROR]', 'WARNING': '[WARN]', 'INFO': '[INFO]', 'SKIP': '[SKIP]', 'ROCKET': '[START]', 'GEAR': '[PROC]', 'MAGNIFYING_GLASS': '[CHECK]', 'CHECKMARK': '[DONE]', 'CHART_UP': '[STAT+]', 'CHART_DOWN': '[STAT-]', 'CLIPBOARD': '[CLIP]', 'FILE_FOLDER': '[DIR]', 'PAGE': '[FILE]', 'TABLE': '[TABLE]', 'COLUMN': '[COL]', 'BOOKS': '[DATA]', 'SAVE': '[SAVE]', 'TARGET': '[TARGET]', 'PALETTE': '[STYLE]', 'CELEBRATION': '[DONE]', 'BAR_CHART': '[CHART]', 'MEMO': '[NOTE]'}


def ts(key: str) -> str:
    return TERMINAL_SYMBOLS.get(key, '')


def xs(key: str) -> str:
    return EXCEL_SYMBOLS.get(key, '')

class Symbols:

    @staticmethod
    def get_excel(symbol_name):
        return EXCEL_SYMBOLS.get(symbol_name, '')

    @staticmethod
    def get_terminal(symbol_name):
        return TERMINAL_SYMBOLS.get(symbol_name, '')

    @staticmethod
    def print_with_symbol(symbol_name, message, end='\n'):
        sym = TERMINAL_SYMBOLS.get(symbol_name, '')
        print(f'{sym} {message}', end=end)