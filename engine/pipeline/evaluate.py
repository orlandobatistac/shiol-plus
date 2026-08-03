"""
Evaluator — compara tickets generados vs resultado real y calcula premios.
Game-agnostic: recibe prize_table del game config.
"""
from typing import List, Dict

# Fallback: prize table de Powerball (para compatibilidad hacia atrás)
_POWERBALL_PRIZE_TABLE = {
    (5, 1): ('jackpot',     0),
    (5, 0): ('match5',      1_000_000),
    (4, 1): ('match4+pb',   50_000),
    (4, 0): ('match4',      100),
    (3, 1): ('match3+pb',   100),
    (3, 0): ('match3',      7),
    (2, 1): ('match2+pb',   7),
    (1, 1): ('match1+pb',   4),
    (0, 1): ('match0+pb',   4),
}


def evaluate_ticket(ticket: Dict, draw: Dict, prize_table: Dict = None, game: Dict = None) -> Dict:
    """
    Evalúa un ticket contra el draw real.

    Args:
        ticket:      {'numbers': [int,...], 'extra': int, ...}
        draw:        {'n1':int, 'n2':int, 'n3':int, 'n4':int, 'n5':int, 'pb':int}
        prize_table: dict del game config — si None usa Powerball por defecto
        game:        game config dict completo
    """
    prize_table = prize_table or (game.get('prize_table') if game else _POWERBALL_PRIZE_TABLE)
    is_digit = (game and game.get('game_type') == 'digit')

    if is_digit:
        digit_count = game.get('white_count', 3)
        draw_cols = [f'n{i+1}' for i in range(digit_count)]
        draw_digits = [draw[col] for col in draw_cols if col in draw and draw[col] is not None]

        # Positional matching para Straight (acierto exacto posicional)
        matches = 0
        for i, t_val in enumerate(ticket['numbers']):
            if i < len(draw_digits) and t_val == draw_digits[i]:
                matches += 1

        white_matches = matches
        extra_match = 0
        level, amount = prize_table.get(white_matches, prize_table.get((white_matches, 0), ('no_prize', 0.0)))
    else:
        winning_whites = {draw[c] for c in ['n1', 'n2', 'n3', 'n4', 'n5'] if c in draw and draw[c] is not None}
        winning_extra  = draw.get('pb') or draw.get('extra')

        white_matches = len(set(ticket['numbers']) & winning_whites)
        extra_match   = 0 if ticket.get('extra') is None else int(ticket['extra'] == winning_extra)

        level, amount = prize_table.get((white_matches, extra_match), ('no_prize', 0.0))

    return {
        **ticket,
        'matches_white': white_matches,
        'matches_extra': extra_match,
        'prize_level':   level,
        'prize_amount':  amount,
    }


def evaluate_strategy(tickets: List[Dict], draw: Dict,
                      game: Dict = None) -> Dict:
    """
    Evalúa todos los tickets de una estrategia y agrega resultados.

    Args:
        tickets: lista de tickets generados por una estrategia
        draw:    resultado real del sorteo
        game:    game config completo (contiene prize_table y ticket_cost)
    """
    prize_table     = game['prize_table']    if game else _POWERBALL_PRIZE_TABLE
    cost_per_ticket = game['ticket_cost']    if game else 2.0

    evaluated   = [evaluate_ticket(t, draw, prize_table, game) for t in tickets]
    total_prize = sum(t['prize_amount'] for t in evaluated)
    total_cost  = len(tickets) * cost_per_ticket
    roi         = (total_prize - total_cost) / total_cost if total_cost > 0 else 0.0

    return {
        'tickets_count':   len(evaluated),
        'matches_3':       sum(1 for t in evaluated if t['matches_white'] == 3 and t['matches_extra'] == 0),
        'matches_4':       sum(1 for t in evaluated if t['matches_white'] == 4),
        'matches_5':       sum(1 for t in evaluated if t['matches_white'] == 5 and t['matches_extra'] == 0),
        'matches_jackpot': sum(1 for t in evaluated if t['prize_level'] in ('jackpot', 'straight')),
        'total_prize':     total_prize,
        'roi':             round(roi, 4),
        'evaluated_tickets': evaluated,
    }
