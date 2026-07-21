"""SHIOL+ v9 -- North Carolina Cash 5 game definition."""

GAME = {
    'id': 'cash5',
    'name': 'NC Cash 5',
    'active': True,
    'white_count': 5,
    'white_max': 43,
    'has_extra_ball': False,
    'extra_max': None,
    'extra_name': None,
    'ticket_cost': 1.00,
    'draw_days': ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'],
    'draw_time_et': '23:22',
    'cron_primary': ['0 5 * * *'],
    'cron_backup': ['0 9 * * *'],
    'data_sources': ['nc_lottery_csv'],
    'nc_csv_url': 'https://nclottery.com/cash5-download',
    'nc_csv_date_format': '%m/%d/%Y',
    'nc_csv_columns': {
        'date': 0,
        'n1': 1, 'n2': 2, 'n3': 3, 'n4': 4, 'n5': 5,
        'dp': 6,
    },
    'prize_table': {
        (5, 0): ('jackpot', 0),
        (4, 0): ('match4', 250),
        (3, 0): ('match3', 5),
        (2, 0): ('match2', 1),
    },
    'compatible_strategies': 'all',
    'description': 'NC Cash 5 -- sorteos diarios. Cinco bolas del 1 al 43.',
    'logo_color': '#0b7a3e',
}
