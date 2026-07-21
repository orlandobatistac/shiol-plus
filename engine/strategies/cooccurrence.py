"""
Co-occurrence Strategy
Usa pares de números que aparecen juntos con frecuencia superior a la esperada.
"""
import random
from itertools import combinations
from typing import List, Dict, Tuple
import pandas as pd
from .base import BaseStrategy


class CooccurrenceStrategy(BaseStrategy):

    def __init__(self, lottery_config: Dict):
        super().__init__('cooccurrence', lottery_config)

    def generate(self, draws: pd.DataFrame, count: int = 10) -> List[Dict]:
        strong_pairs = self._get_strong_pairs(draws)
        tickets = []

        for _ in range(count):
            if strong_pairs:
                pair = random.choice(strong_pairs)
                numbers = list(pair)
            else:
                numbers = random.sample(range(1, self.white_max + 1), 2)

            available = [n for n in range(1, self.white_max + 1) if n not in numbers]
            numbers.extend(random.sample(available, self.white_count - len(numbers)))
            extra = self._random_extra()
            tickets.append(self._safe_ticket(numbers, extra, 0.65))

        return tickets

    def _get_strong_pairs(self, draws: pd.DataFrame, threshold: float = 1.2) -> List[Tuple]:
        """
        Encuentra pares con co-ocurrencia > threshold * esperado.
        threshold=1.2 → aparecen 20% más de lo esperado.
        """
        if draws.empty or len(draws) < 20:
            return []

        pair_counts: Dict[Tuple, int] = {}
        number_cols = [c for c in ['n1', 'n2', 'n3', 'n4', 'n5'] if c in draws.columns]

        for _, row in draws.iterrows():
            nums = [int(row[c]) for c in number_cols if pd.notna(row[c])]
            for pair in combinations(sorted(nums), 2):
                pair_counts[pair] = pair_counts.get(pair, 0) + 1

        total_draws = len(draws)
        # Probabilidad esperada de cualquier par específico en 5 bolas de 69
        # = C(5,2) / C(69,2) ≈ 10 / 2346
        p_expected = 10 / (self.white_max * (self.white_max - 1) / 2)
        expected_count = p_expected * total_draws

        strong = [
            pair for pair, cnt in pair_counts.items()
            if cnt >= expected_count * threshold and cnt >= 3
        ]

        # Ordenar por frecuencia y devolver top 50
        strong.sort(key=lambda p: pair_counts[p], reverse=True)
        return strong[:50]
