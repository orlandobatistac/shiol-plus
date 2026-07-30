"""
XGBoost ML Strategy
Entrena un modelo XGBoost sobre el histórico y usa sus probabilidades para samplear.
v9: el modelo se entrena fresh cada vez (no depende de .pkl pre-entrenado).
"""
import random
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
from .base import BaseStrategy


class XGBoostMLStrategy(BaseStrategy):

    def __init__(self, lottery_config: Dict):
        super().__init__('xgboost_ml', lottery_config)
        self._wb_probs: Optional[np.ndarray] = None
        self._extra_probs: Optional[np.ndarray] = None
        self._trained_on: Optional[int] = None   # len(draws) cuando fue entrenado

    def generate(self, draws: pd.DataFrame, count: int = 10) -> List[Dict]:
        # Re-entrenar si los datos cambiaron
        if self._trained_on != len(draws):
            self._train(draws)

        if self._wb_probs is None:
            # Fallback si XGBoost no disponible
            return self._random_fallback(count)

        tickets = []
        for _ in range(count):
            try:
                numbers = sorted(np.random.choice(
                    range(1, self.white_max + 1),
                    size=self.white_count,
                    replace=False,
                    p=self._wb_probs
                ).tolist())
                extra = (int(np.random.choice(range(1, self.extra_max + 1), p=self._extra_probs))
                         if self.has_extra_ball else None)
                tickets.append(self._safe_ticket(numbers, extra, 0.82))
            except Exception:
                tickets.append(self._random_fallback(1)[0])

        return tickets

    def _train(self, draws: pd.DataFrame):
        """Entrena XGBoost y cachea vectores de probabilidad."""
        try:
            from xgboost import XGBClassifier

            if len(draws) < 50:
                self._wb_probs = None
                return

            number_cols = [c for c in ['n1', 'n2', 'n3', 'n4', 'n5'] if c in draws.columns]
            draws = draws.sort_values('draw_date').reset_index(drop=True)

            # Features: frecuencias acumuladas hasta cada sorteo
            wb_freq = np.zeros(self.white_max)
            wb_probs_list = []

            for _, row in draws.iterrows():
                total = wb_freq.sum()
                probs = (wb_freq / total) if total > 0 else np.ones(self.white_max) / self.white_max
                wb_probs_list.append(probs.copy())
                for col in number_cols:
                    n = int(row[col])
                    if 1 <= n <= self.white_max:
                        wb_freq[n - 1] += 1

            # Usamos el vector de frecuencias acumuladas como probabilidades base
            # XGBoost refina este prior con señal de recencia
            X = np.array(wb_probs_list[:-1])   # features: probs hasta t-1
            y_raw = draws[number_cols].iloc[1:].values  # targets: números reales

            # Crear target binario por número
            probs_sum = np.zeros(self.white_max)
            for i in range(self.white_max):
                n = i + 1
                y = ((y_raw == n).any(axis=1)).astype(int)
                if y.sum() == 0:
                    probs_sum[i] = wb_freq[i]
                    continue
                try:
                    clf = XGBClassifier(n_estimators=50, max_depth=3,
                                        use_label_encoder=False, eval_metric='logloss',
                                        verbosity=0, random_state=42)
                    clf.fit(X, y)
                    probs_sum[i] = clf.predict_proba(X[-1:].reshape(1, -1))[0][1]
                except Exception:
                    probs_sum[i] = wb_freq[i]

            total = probs_sum.sum()
            self._wb_probs = probs_sum / total if total > 0 else np.ones(self.white_max) / self.white_max

            # Extra: frecuencia simple (XGBoost overkill para 26 valores)
            extra_freq = np.zeros(self.extra_max) if self.has_extra_ball else None
            if self.has_extra_ball and 'pb' in draws.columns:
                for n in draws[(draws['pb'] >= 1) & (draws['pb'] <= self.extra_max)]['pb']:
                    extra_freq[int(n) - 1] += 1
            if self.has_extra_ball:
                t = extra_freq.sum()
                self._extra_probs = extra_freq / t if t > 0 else np.ones(self.extra_max) / self.extra_max
            else:
                self._extra_probs = None

            self._trained_on = len(draws)

        except ImportError:
            # XGBoost no instalado
            self._wb_probs = None
            self._extra_probs = None

    def _random_fallback(self, count: int) -> List[Dict]:
        return [
            self._safe_ticket(
                sorted(random.sample(range(1, self.white_max + 1), self.white_count)),
                self._random_extra(),
                0.50
            )
            for _ in range(count)
        ]
