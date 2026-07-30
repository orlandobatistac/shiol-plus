"""
Coverage Optimizer Strategy
Maximiza la cobertura del espacio de números — evita repetir números entre tickets.
"""
import random
from typing import List, Dict
import pandas as pd
from .base import BaseStrategy


class CoverageOptimizerStrategy(BaseStrategy):

    def __init__(self, lottery_config: Dict):
        super().__init__('coverage_optimizer', lottery_config)

    def generate(self, draws: pd.DataFrame, count: int = 10) -> List[Dict]:
        tickets = []
        used = set()

        for _ in range(count):
            available = [n for n in range(1, self.white_max + 1) if n not in used]

            if len(available) < self.white_count:
                used = set()
                available = list(range(1, self.white_max + 1))

            numbers = sorted(random.sample(available, self.white_count))
            used.update(numbers)
            extra = random.randint(1, self.extra_max)
            tickets.append(self._safe_ticket(numbers, extra, 0.70))

        return tickets
