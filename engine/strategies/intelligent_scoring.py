"""
Intelligent Scoring Strategy
Combina frecuencia histórica + decay temporal + gap analysis para scoring multi-criterio.
"""
import random
import numpy as np
import pandas as pd
from typing import List, Dict
from .base import BaseStrategy


class IntelligentScoringStrategy(BaseStrategy):

    def __init__(self, lottery_config: Dict, decay_rate: float = 0.05):
        super().__init__('intelligent_scoring', lottery_config)
        self.decay_rate = decay_rate

    def generate(self, draws: pd.DataFrame, count: int = 10) -> List[Dict]:
        wb_scores = self._compute_scores(draws)
        extra_probs = self._extra_probs(draws) if self.has_extra_ball else None
        tickets = []

        for _ in range(count):
            try:
                # Normalizar scores a probabilidades
                total = wb_scores.sum()
                probs = wb_scores / total if total > 0 else np.ones(self.white_max) / self.white_max

                numbers = sorted(np.random.choice(
                    range(1, self.white_max + 1),
                    size=self.white_count,
                    replace=False,
                    p=probs
                ).tolist())
                extra = (int(np.random.choice(range(1, self.extra_max + 1), p=extra_probs))
                         if self.has_extra_ball else None)
                tickets.append(self._safe_ticket(numbers, extra, 0.74))
            except Exception:
                numbers = sorted(random.sample(range(1, self.white_max + 1), self.white_count))
                extra = self._random_extra()
                tickets.append(self._safe_ticket(numbers, extra, 0.50))

        return tickets

    def _compute_scores(self, draws: pd.DataFrame) -> np.ndarray:
        """
        Score = frecuencia_temporal_decaida * bonus_gap
        - Frecuencia temporal: sorteos recientes pesan más (decay exponencial)
        - Gap bonus: números que no salen hace muchos sorteos reciben bonus
        """
        if draws.empty:
            return np.ones(self.white_max) / self.white_max

        draws = draws.sort_values('draw_date').reset_index(drop=True)
        n_draws = len(draws)
        number_cols = [c for c in ['n1', 'n2', 'n3', 'n4', 'n5'] if c in draws.columns]

        freq = np.zeros(self.white_max)
        gap = np.full(self.white_max, n_draws, dtype=float)  # sorteos desde última aparición

        for i, (_, row) in enumerate(draws.iterrows()):
            weight = np.exp(-self.decay_rate * (n_draws - 1 - i))
            for col in number_cols:
                n = int(row[col])
                if 1 <= n <= self.white_max:
                    freq[n - 1] += weight
                    gap[n - 1] = 0  # reset gap

            # Incrementar gap para los que no salieron
            for n_idx in range(self.white_max):
                if gap[n_idx] > 0:
                    gap[n_idx] += 1

        # Normalizar gap como bonus (gap alto → número "vencido" → bonus)
        gap_max = gap.max()
        gap_bonus = (gap / gap_max) * 0.3 + 0.7 if gap_max > 0 else np.ones(self.white_max)

        scores = freq * gap_bonus
        return scores

    def _extra_probs(self, draws: pd.DataFrame) -> np.ndarray:
        freq = np.zeros(self.extra_max)
        if 'pb' in draws.columns:
            for n in draws[(draws['pb'] >= 1) & (draws['pb'] <= self.extra_max)]['pb']:
                freq[int(n) - 1] += 1
        total = freq.sum()
        return freq / total if total > 0 else np.ones(self.extra_max) / self.extra_max
