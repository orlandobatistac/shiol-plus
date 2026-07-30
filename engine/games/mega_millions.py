"""
SHIOL+ v9 -- Mega Millions Game Definition
Template listo para activar. Mismo patron que powerball.py.
"""

GAME = {
    'id':           'mega_millions',
    'name':         'Mega Millions',
    'active':       True,       # activado (ADR-0001, Fase de activación de Mega Millions)

    'white_count':  5,
    'white_max':    70,
    'extra_max':    25,
    'extra_name':   'Mega Ball',
    'ticket_cost':  2.00,

    'draw_days':    ['Tuesday', 'Friday'],
    'draw_time_et': '23:00',

    'cron_primary': ['0 5 * * 3', '0 5 * * 6'],
    'cron_backup':  ['0 9 * * 3', '0 9 * * 6'],

    # nc_lottery_csv quedo 404 (verificado 2026-07-04); ny_data_api es primaria si se activa este juego.
    'data_sources': ['ny_data_api', 'nc_lottery_csv', 'megamillions_com'],
    'ny_dataset_id': '5xaw-6ayf',
    # A diferencia de Powerball, este dataset de Socrata trae la bola extra
    # en un campo separado, NO embebida en 'winning_numbers' (verificado
    # contra la API real: 'winning_numbers' solo trae las 5 blancas). Bug
    # real que bloqueaba la activación -- ver fetch_draw.py::_from_ny_data.
    'ny_extra_ball_field': 'mega_ball',
    'nc_csv_url':   'https://nclottery.com/Content/uploads/DrawingResultsCSV/megamillions.csv',
    'nc_csv_date_format': '%m/%d/%Y',
    'nc_csv_columns': {
        'date': 0,
        'n1': 1, 'n2': 2, 'n3': 3, 'n4': 4, 'n5': 5,
        'extra': 6,
    },

    'prize_table': {
        (5, 1): ('jackpot',   0),
        (5, 0): ('match5',    1_000_000),
        (4, 1): ('match4+mb', 10_000),
        (4, 0): ('match4',    500),
        (3, 1): ('match3+mb', 200),
        (3, 0): ('match3',    10),
        (2, 1): ('match2+mb', 10),
        (1, 1): ('match1+mb', 4),
        (0, 1): ('match0+mb', 2),
    },

    'compatible_strategies': 'all',

    'description': 'Mega Millions -- sorteos mar/vie. Blancas 1-70, Mega Ball 1-25.',
    'logo_color':  '#003087',
}
