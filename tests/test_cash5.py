import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from engine.games import get_game, get_lottery_config
from engine.games.register import _cash5_draws_from_csv
from engine.pipeline.evaluate import evaluate_ticket
from engine.strategies import ALL_STRATEGIES


class Cash5Tests(unittest.TestCase):
    def test_official_csv_contract(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'cash5.csv'
            path.write_text(
                '"Date","Ball 1","Ball 2","Ball 3","Ball 4","Ball 5","DP"\n'
                '"07/11/2026","13","17","19","21","29","0"\n'
                '"07/11/2026","6","15","16","20","42","1"\n'
                '"Official results control","","","","","",""\n',
                encoding='utf-8',
            )
            draws, double_play, invalid = _cash5_draws_from_csv(path)
        self.assertEqual(1, len(draws))
        self.assertEqual(1, double_play)
        self.assertEqual(1, invalid)
        self.assertEqual('2026-07-11', draws[0]['date'])
        self.assertEqual([13, 17, 19, 21, 29], draws[0]['numbers'])

    def test_all_strategies_generate_without_extra_ball(self):
        config = get_lottery_config('cash5')
        history = pd.DataFrame([
            {'draw_date': '2026-07-10', 'n1': 2, 'n2': 4, 'n3': 19,
             'n4': 21, 'n5': 34, 'pb': None}
        ])
        for name, strategy_class in ALL_STRATEGIES.items():
            tickets = strategy_class(config).generate(history, 2)
            self.assertEqual(2, len(tickets), name)
            for ticket in tickets:
                self.assertIsNone(ticket['extra'], name)
                self.assertEqual(5, len(set(ticket['numbers'])), name)
                self.assertTrue(all(1 <= number <= 43 for number in ticket['numbers']), name)

    def test_cash5_prizes_ignore_extra_ball(self):
        game = get_game('cash5')
        draw = {'n1': 1, 'n2': 2, 'n3': 3, 'n4': 4, 'n5': 5, 'pb': None}
        result = evaluate_ticket(
            {'numbers': [1, 2, 3, 10, 11], 'extra': None},
            draw,
            game['prize_table'],
        )
        self.assertEqual(3, result['matches_white'])
        self.assertEqual(0, result['matches_extra'])
        self.assertEqual(5, result['prize_amount'])


if __name__ == '__main__':
    unittest.main()
