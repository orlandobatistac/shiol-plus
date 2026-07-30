"""
Range Balanced Strategy
Distribución 2 low / 2 mid / 1 high — aproxima la distribución típica de sorteos reales.
"""
import random
from typing import List, Dict
import pandas as pd
from .base import BaseStrategy


class RangeBalancedStrategy(BaseStrategy):

    def __init__(self, lottery_config: Dict):
        super().__init__('range_balanced', lottery_config)
        # Calcular rangos dinámicamente según white_max
        third = self.white_max // 3
        self.low_range  = (1, third)
        self.mid_range  = (third + 1, third * 2)
        self.high_range = (third * 2 + 1, self.white_max)

    def generate(self, draws: pd.DataFrame, count: int = 10) -> List[Dict]:
        tickets = []
        for _ in range(count):
            try:
                low  = random.sample(range(self.low_range[0],  self.low_range[1]  + 1), 2)
                mid  = random.sample(range(self.mid_range[0],  self.mid_range[1]  + 1), 2)
                high = random.sample(range(self.high_range[0], self.high_range[1] + 1), 1)
                numbers = low + mid + high
                extra = random.randint(1, self.extra_max)
                tickets.append(self._safe_ticket(numbers, extra, 0.68))
            except ValueError:
                numbers = sorted(random.sample(range(1, self.white_max + 1), self.white_count))
                extra = random.randint(1, self.extra_max)
                tickets.append(self._safe_ticket(numbers, extra, 0.50))
        return tickets
