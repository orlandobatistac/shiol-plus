"""
Wheeling Strategy (estrategia 9) — Covering design / lottery wheel.

Origen (Fase 9, sesión 33): la observación de Orlando de que los números
ganadores aparecen dispersos entre las jugadas premiadas motivó un segundo
nivel "consolidador". El análisis estadístico (ver TODO.md Fase 9) demostró
que esa dispersión es sesgo de selección retrospectiva y no es aprendible
por ML (cada sorteo es independiente). Lo que SÍ es optimizable es la
estructura combinatoria: esta estrategia construye sus tickets como un
*wheel* — un covering design parcial C(pool, 5, t=3) — sobre un pool de
números calientes.

Propiedad que se está probando (falsable, medible en producción):
- El valor esperado por ticket es matemáticamente idéntico al azar (los
  marginales no cambian con la estructura). Lo único que cambia es la
  distribución conjunta: SI ≥3 ganadores caen dentro del pool, el wheel
  maximiza la probabilidad de que un mismo ticket los concentre.
- Predicción del Monte Carlo (200k sorteos, sesión 33): ROI
  indistinguible de random_baseline a largo plazo; diferencia solo en la
  *forma* de los premios (más concentrados cuando el pool acierta, menos
  premios pequeños regados). El experimento vivo confirma o refuta.

Diseño (parámetros elegidos con simulación, no con intuición):
- pool_size ≈ 43% de white_max (69→30, 70→30, 43→18): balance entre
  P(ganadores dentro del pool) y densidad de cobertura de triples.
- Greedy max-coverage de triples: 20 tickets cubren ~9% de los triples
  del pool — un covering completo C(30,5,3) necesitaría cientos de líneas.
- Extra ball: rota entre las top-4 calientes (cobertura, no concentración).

Sin dependencias de DB. Game-agnostic vía LotteryConfig (BaseStrategy).
"""
import random
from itertools import combinations
from typing import List, Dict, Set, Tuple

import pandas as pd

from .base import BaseStrategy

POOL_RATIO      = 0.43   # fracción de white_max que entra al pool caliente
MAX_CANDIDATES  = 4000   # subsets candidatos por iteración greedy
HOT_EXTRA_COUNT = 4      # extras calientes entre las que se rota
CONFIDENCE      = 0.70


class WheelingStrategy(BaseStrategy):

    def __init__(self, lottery_config: Dict):
        super().__init__('wheeling', lottery_config)

    # ── pool ──────────────────────────────────────────────────────────

    def _hot_pool(self, draws: pd.DataFrame, pool_size: int) -> List[int]:
        """Top pool_size números por frecuencia histórica; completa con
        números aleatorios si el histórico no alcanza."""
        freq = {}
        for col in ['n1', 'n2', 'n3', 'n4', 'n5']:
            if col in draws.columns:
                for n in draws[col].dropna():
                    n = int(n)
                    if 1 <= n <= self.white_max:
                        freq[n] = freq.get(n, 0) + 1
        pool = [n for n, _ in sorted(freq.items(), key=lambda kv: -kv[1])][:pool_size]
        if len(pool) < pool_size:
            rest = [n for n in range(1, self.white_max + 1) if n not in pool]
            pool += random.sample(rest, pool_size - len(pool))
        return pool

    def _hot_extras(self, draws: pd.DataFrame) -> List[int]:
        freq = {}
        if 'pb' in draws.columns:
            for n in draws['pb'].dropna():
                n = int(n)
                if 1 <= n <= self.extra_max:
                    freq[n] = freq.get(n, 0) + 1
        hot = [n for n, _ in sorted(freq.items(), key=lambda kv: -kv[1])][:HOT_EXTRA_COUNT]
        if not hot:
            hot = random.sample(range(1, self.extra_max + 1),
                                min(HOT_EXTRA_COUNT, self.extra_max))
        return hot

    # ── wheel ─────────────────────────────────────────────────────────

    def _build_wheel(self, pool: List[int], count: int) -> List[List[int]]:
        """Greedy max-coverage: en cada paso elige el 5-subset del pool que
        cubre más triples (t=3) aún no cubiertos por los tickets previos."""
        k = self.white_count
        n_subsets = _ncr(len(pool), k)
        if n_subsets <= MAX_CANDIDATES:
            candidates = [list(c) for c in combinations(pool, k)]
        else:
            seen: Set[Tuple[int, ...]] = set()
            while len(seen) < MAX_CANDIDATES:
                seen.add(tuple(sorted(random.sample(pool, k))))
            candidates = [list(c) for c in seen]

        triples = [frozenset(combinations(sorted(c), 3)) for c in candidates]
        covered: Set[Tuple[int, ...]] = set()
        wheel: List[List[int]] = []
        used: Set[Tuple[int, ...]] = set()

        for _ in range(count):
            best_i, best_gain = -1, -1
            for i, tr in enumerate(triples):
                key = tuple(sorted(candidates[i]))
                if key in used:
                    continue
                gain = len(tr - covered)
                if gain > best_gain:
                    best_gain, best_i = gain, i
            if best_i < 0:  # pool agotado (count > subsets posibles)
                wheel.append(sorted(random.sample(range(1, self.white_max + 1), k)))
                continue
            wheel.append(sorted(candidates[best_i]))
            used.add(tuple(sorted(candidates[best_i])))
            covered |= triples[best_i]
        return wheel

    # ── API BaseStrategy ──────────────────────────────────────────────

    def generate(self, draws: pd.DataFrame, count: int = 10) -> List[Dict]:
        pool_size = max(2 * self.white_count,
                        round(self.white_max * POOL_RATIO))
        pool_size = min(pool_size, self.white_max)

        pool  = self._hot_pool(draws, pool_size)
        wheel = self._build_wheel(pool, count)
        extras = self._hot_extras(draws) if self.has_extra_ball else None

        tickets = []
        for i, numbers in enumerate(wheel):
            extra = extras[i % len(extras)] if extras else None
            tickets.append(self._safe_ticket(numbers, extra, CONFIDENCE))
        return tickets


def _ncr(n: int, r: int) -> int:
    from math import comb
    return comb(n, r)
