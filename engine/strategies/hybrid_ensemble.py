"""
Hybrid Ensemble Strategy
70% XGBoost + 30% Co-occurrence — combina señal ML con señal estadística.
"""
import pandas as pd
from typing import List, Dict
from .base import BaseStrategy
from .xgboost_ml import XGBoostMLStrategy
from .cooccurrence import CooccurrenceStrategy


class HybridEnsembleStrategy(BaseStrategy):

    def __init__(self, lottery_config: Dict):
        super().__init__('hybrid_ensemble', lottery_config)
        self._xgb = XGBoostMLStrategy(lottery_config)
        self._coo = CooccurrenceStrategy(lottery_config)

    def generate(self, draws: pd.DataFrame, count: int = 10) -> List[Dict]:
        xgb_count = max(1, int(count * 0.7))
        coo_count = count - xgb_count

        tickets = []

        xgb_tickets = self._xgb.generate(draws, xgb_count)
        for t in xgb_tickets:
            t['confidence'] = round(min(0.88, t['confidence'] + 0.05), 4)
        tickets.extend(xgb_tickets)

        if coo_count > 0:
            coo_tickets = self._coo.generate(draws, coo_count)
            for t in coo_tickets:
                t['confidence'] = round(min(0.88, t['confidence'] + 0.05), 4)
            tickets.extend(coo_tickets)

        return tickets
