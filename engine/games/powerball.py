"""
SHIOL+ v9 -- Powerball Game Definition
Contrato completo del juego: reglas, prizes, fuentes de datos, crons.
"""

GAME = {
    'id':           'powerball',
    'name':         'Powerball',
    'active':       True,

    'white_count':  5,
    'white_max':    69,
    'extra_max':    26,
    'extra_name':   'Powerball',
    'ticket_cost':  2.00,

    'draw_days':    ['Monday', 'Wednesday', 'Saturday'],
    'draw_time_et': '22:59',

    'cron_primary': ['0 5 * * 2', '0 5 * * 4', '0 5 * * 0'],
    'cron_backup':  ['0 9 * * 2', '0 9 * * 4', '0 9 * * 0'],

    # Prioridad de fuentes (sesion 33, 2026-07-22): nc_web primero (mismo dia),
    # ny_data_api fallback historico, powerball.com y musl_api como ultima opcion.
    'nc_web_url':   'https://nclottery.com/powerball',
    'data_sources': ['nc_web', 'ny_data_api', 'nc_lottery_csv', 'powerball_com', 'musl_api'],
    'ny_dataset_id': 'd6yy-54nr',
    # None = 'winning_numbers' del dataset de Socrata trae los 6 números
    # juntos (5 blancas + Powerball). Ver engine/pipeline/fetch_draw.py.
    'ny_extra_ball_field': None,
    'nc_csv_url':   'https://nclottery.com/Content/uploads/DrawingResultsCSV/powerball.csv',
    'nc_csv_date_format': '%m/%d/%Y',
    'nc_csv_columns': {
        'date': 0,
        'n1': 1, 'n2': 2, 'n3': 3, 'n4': 4, 'n5': 5,
        'extra': 6,
    },

    'prize_table': {
        (5, 1): ('jackpot',   0),
        (5, 0): ('match5',    1_000_000),
        (4, 1): ('match4+pb', 50_000),
        (4, 0): ('match4',    100),
        (3, 1): ('match3+pb', 100),
        (3, 0): ('match3',    7),
        (2, 1): ('match2+pb', 7),
        (1, 1): ('match1+pb', 4),
        (0, 1): ('match0+pb', 4),
    },

    'compatible_strategies': 'all',

    'description': 'Powerball -- sorteos lun/mie/sab. Blancas 1-69, Powerball 1-26.',
    'logo_color':  '#c8102e',
}
