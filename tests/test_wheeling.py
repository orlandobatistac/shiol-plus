import random
import unittest
from itertools import combinations

import pandas as pd

from engine.games import get_lottery_config
from engine.strategies import ALL_STRATEGIES
from engine.strategies.wheeling import WheelingStrategy


def _history_rows(numbers_cycle, pb_cycle, rows=60):
    """Histórico sintético rotando sobre un conjunto conocido de números."""
    out = []
    for i in range(rows):
        base = [numbers_cycle[(i * 5 + j) % len(numbers_cycle)] for j in range(5)]
        # garantizar 5 distintos
        base = sorted(set(base))
        while len(base) < 5:
            candidate = numbers_cycle[(i + len(base) * 7) % len(numbers_cycle)]
            if candidate not in base:
                base.append(candidate)
        base = sorted(base)[:5]
        out.append({'draw_date': f'2026-01-{(i % 28) + 1:02d}',
                    'n1': base[0], 'n2': base[1], 'n3': base[2],
                    'n4': base[3], 'n5': base[4],
                    'pb': pb_cycle[i % len(pb_cycle)] if pb_cycle else None})
    return pd.DataFrame(out)


class WheelingTests(unittest.TestCase):
    def setUp(self):
        random.seed(1234)

    def test_registered_as_strategy_9(self):
        self.assertIn('wheeling', ALL_STRATEGIES)
        self.assertIs(ALL_STRATEGIES['wheeling'], WheelingStrategy)

    def test_powerball_tickets_valid_and_within_hot_pool(self):
        config = get_lottery_config('powerball')
        # histórico usa SOLO los números 1..30 → el pool caliente ⊆ 1..30
        history = _history_rows(list(range(1, 31)), [1, 2, 3, 4])
        strategy = WheelingStrategy(config)
        tickets = strategy.generate(history, 20)

        self.assertEqual(20, len(tickets))
        for ticket in tickets:
            self.assertEqual(5, len(set(ticket['numbers'])))
            self.assertTrue(all(1 <= n <= 30 for n in ticket['numbers']),
                            f"números fuera del pool caliente: {ticket['numbers']}")
            self.assertTrue(1 <= ticket['extra'] <= 26)
        # sin tickets duplicados
        keys = {tuple(t['numbers']) for t in tickets}
        self.assertEqual(20, len(keys))

    def test_triple_coverage_is_high(self):
        """El wheel debe cubrir casi el máximo posible de triples distintos
        (20 tickets × C(5,3) = 200) — esa es su razón de existir."""
        config = get_lottery_config('powerball')
        history = _history_rows(list(range(1, 31)), [1, 2, 3, 4])
        tickets = WheelingStrategy(config).generate(history, 20)
        triples = set()
        for t in tickets:
            triples |= set(combinations(sorted(t['numbers']), 3))
        self.assertGreaterEqual(len(triples), 190)

    def test_extra_rotates_among_hot_extras(self):
        config = get_lottery_config('powerball')
        history = _history_rows(list(range(1, 31)), [7, 11, 13, 21])
        tickets = WheelingStrategy(config).generate(history, 8)
        extras = {t['extra'] for t in tickets}
        self.assertTrue(extras.issubset({7, 11, 13, 21}), extras)
        self.assertGreater(len(extras), 1)  # rota, no concentra en una sola

    def test_cash5_without_extra_ball(self):
        config = get_lottery_config('cash5')
        history = _history_rows(list(range(1, 20)), None)
        tickets = WheelingStrategy(config).generate(history, 20)
        self.assertEqual(20, len(tickets))
        for ticket in tickets:
            self.assertIsNone(ticket['extra'])
            self.assertEqual(5, len(set(ticket['numbers'])))
            self.assertTrue(all(1 <= n <= 43 for n in ticket['numbers']))

    def test_survives_tiny_history(self):
        config = get_lottery_config('powerball')
        history = pd.DataFrame([{'draw_date': '2026-07-10', 'n1': 2, 'n2': 4,
                                 'n3': 19, 'n4': 21, 'n5': 34, 'pb': 9}])
        tickets = WheelingStrategy(config).generate(history, 2)
        self.assertEqual(2, len(tickets))
        for ticket in tickets:
            self.assertEqual(5, len(set(ticket['numbers'])))


if __name__ == '__main__':
    unittest.main()
