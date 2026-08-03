"""
SHIOL+ v9 — Game Registry
Punto central de todos los juegos registrados.
Agregar un juego nuevo = importarlo aquí.
"""
from .powerball     import GAME as POWERBALL
from .mega_millions import GAME as MEGA_MILLIONS
from .cash5         import GAME as CASH5
from .pick3         import GAME as PICK3
from .pick4         import GAME as PICK4

# Registry completo — orden importa para el dashboard
ALL_GAMES = {
    'powerball':     POWERBALL,
    'mega_millions': MEGA_MILLIONS,
    'cash5':         CASH5,
    'pick3':         PICK3,
    'pick4':         PICK4,
}

# Solo juegos activos
ACTIVE_GAMES = {k: v for k, v in ALL_GAMES.items() if v.get('active')}


def get_game(game_id: str) -> dict:
    """Retorna la definición completa de un juego."""
    if game_id not in ALL_GAMES:
        raise ValueError(
            f"Juego '{game_id}' no encontrado. "
            f"Disponibles: {list(ALL_GAMES.keys())}"
        )
    return ALL_GAMES[game_id]


def get_lottery_config(game_id: str) -> dict:
    """
    Retorna el subconjunto de config que esperan las estrategias.
    Compatible con BaseStrategy.__init__.
    """
    g = get_game(game_id)
    return {
        'white_count': g['white_count'],
        'white_min':   g.get('white_min', 1),
        'white_max':   g['white_max'],
        'extra_max':   g['extra_max'],
        'extra_name':  g['extra_name'],
        'has_extra_ball': g.get('has_extra_ball', True),
        'game_type': g.get('game_type', 'lotto'),
        'allow_duplicates': g.get('allow_duplicates', False),
    }
