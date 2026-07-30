"""
Random Baseline Strategy
Control científico — aleatorio puro. Benchmark contra el que medir todas las demás.
"""
import random
import pandas as pd
from typing import List, Dict
from .base import BaseStrategy


class RandomBaselineStrategy(BaseStrategy):

    def __init__(self, lottery_config: Dict):
        super().__init__('random_baseline', lottery_config)

    def generate(self, draws: pd.DataFrame, count: int = 10) -> List[Dict]:
        return [
            self._safe_ticket(
                sorted(random.sample(range(1, self.white_max + 1), self.white_count)),
                self._random_extra(),
                0.50
            )
            for _ in range(count)
        ]
