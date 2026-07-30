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


def evaluate_ticket(ticket: Dict, draw: Dict, prize_table: Dict = None) -> Dict:
    """
    Evalúa un ticket contra el draw real.

    Args:
        ticket:      {'numbers': [int,...], 'extra': int, ...}
        draw:        {'n1':int, 'n2':int, 'n3':int, 'n4':int, 'n5':int, 'pb':int}
        prize_table: dict del game config — si None usa Powerball por defecto
    """
    prize_table = prize_table or _POWERBALL_PRIZE_TABLE

    winning_whites = {draw['n1'], draw['n2'], draw['n3'], draw['n4'], draw['n5']}
    winning_extra  = draw.get('pb') or draw.get('extra')

    white_matches = len(set(ticket['numbers']) & winning_whites)
    # En juegos sin bola adicional ambos valores son None; eso significa
    # "no aplica", no un acierto de bola extra.
    extra_match   = 0 if ticket.get('extra') is None else int(ticket['extra'] == winning_extra)

    level, amount = prize_table.get((white_matches, extra_match), ('no_prize', 0))

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

    evaluated   = [evaluate_ticket(t, draw, prize_table) for t in tickets]
    total_prize = sum(t['prize_amount'] for t in evaluated)
    total_cost  = len(tickets) * cost_per_ticket
    roi         = (total_prize - total_cost) / total_cost if total_cost > 0 else 0.0

    return {
        'tickets_count':   len(evaluated),
        'matches_3':       sum(1 for t in evaluated if t['matches_white'] == 3 and t['matches_extra'] == 0),
        'matches_4':       sum(1 for t in evaluated if t['matches_white'] == 4),
        'matches_5':       sum(1 for t in evaluated if t['matches_white'] == 5 and t['matches_extra'] == 0),
        'matches_jackpot': sum(1 for t in evaluated if t['prize_level'] == 'jackpot'),
        'total_prize':     total_prize,
        'roi':             round(roi, 4),
        'evaluated_tickets': evaluated,
    }
