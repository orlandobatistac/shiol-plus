"""
Frequency Weighted Strategy
Pondera números por su frecuencia histórica de aparición.
"""
import random
import numpy as np
import pandas as pd
from typing import List, Dict
from .base import BaseStrategy


class FrequencyWeightedStrategy(BaseStrategy):

    def __init__(self, lottery_config: Dict):
        super().__init__('frequency_weighted', lottery_config)

    def generate(self, draws: pd.DataFrame, count: int = 10) -> List[Dict]:
        wb_probs = self._white_ball_probs(draws)
        extra_probs = self._extra_probs(draws) if self.has_extra_ball else None
        tickets = []

        for _ in range(count):
            try:
                numbers = sorted(np.random.choice(
                    range(1, self.white_max + 1),
                    size=self.white_count,
                    replace=False,
                    p=wb_probs
                ).tolist())
                extra = (int(np.random.choice(range(1, self.extra_max + 1), p=extra_probs))
                         if self.has_extra_ball else None)
                tickets.append(self._safe_ticket(numbers, extra, 0.72))
            except Exception:
                numbers = sorted(random.sample(range(1, self.white_max + 1), self.white_count))
                extra = self._random_extra()
                tickets.append(self._safe_ticket(numbers, extra, 0.50))

        return tickets

    def _white_ball_probs(self, draws: pd.DataFrame) -> np.ndarray:
        freq = np.zeros(self.white_max)
        for col in ['n1', 'n2', 'n3', 'n4', 'n5']:
            if col in draws.columns:
                for n in draws[col].dropna():
                    if 1 <= int(n) <= self.white_max:
                        freq[int(n) - 1] += 1
        total = freq.sum()
        return freq / total if total > 0 else np.ones(self.white_max) / self.white_max

    def _extra_probs(self, draws: pd.DataFrame) -> np.ndarray:
        freq = np.zeros(self.extra_max)
        if 'pb' in draws.columns:
            valid = draws[(draws['pb'] >= 1) & (draws['pb'] <= self.extra_max)]
            for n in valid['pb']:
                freq[int(n) - 1] += 1
        total = freq.sum()
        return freq / total if total > 0 else np.ones(self.extra_max) / self.extra_max
