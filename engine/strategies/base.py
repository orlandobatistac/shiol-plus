"""
SHIOL+ v9 — BaseStrategy
Interfaz común para todas las estrategias. Sin dependencias de DB.
"""
from abc import ABC, abstractmethod
from typing import List, Dict
import pandas as pd


class BaseStrategy(ABC):
    """
    Clase base para todas las estrategias de generación de tickets.

    Principios de diseño v9:
    - Sin acceso a DB (los datos se pasan como parámetro)
    - Sin side effects (funciones puras)
    - Portables a cualquier juego de lotería via LotteryConfig
    """

    def __init__(self, name: str, lottery_config: Dict):
        """
        Args:
            name: Identificador único ('frequency_weighted')
            lottery_config: Reglas del juego {
                'white_count': 5,
                'white_max': 69,
                'extra_max': 26,
                'extra_name': 'Powerball'
            }
        """
        self.name = name
        self.config = lottery_config
        self.white_count = lottery_config.get('white_count', 5)
        self.white_max = lottery_config.get('white_max', 69)
        self.has_extra_ball = lottery_config.get('has_extra_ball', True)
        self.extra_max = lottery_config.get('extra_max') if self.has_extra_ball else None

    @abstractmethod
    def generate(self, draws: pd.DataFrame, count: int = 10) -> List[Dict]:
        """
        Genera tickets basándose en el histórico de draws.

        Args:
            draws: DataFrame con columnas [draw_date, n1, n2, n3, n4, n5, pb]
            count: Número de tickets a generar

        Returns:
            Lista de dicts: {
                'numbers': [int, ...],  # white balls, sorted
                'extra': int,           # powerball / mega ball
                'confidence': float     # 0.0 - 1.0
            }
        """

    def validate(self, numbers: List[int], extra: int = None) -> bool:
        """Valida que un ticket cumple las reglas del juego."""
        if len(numbers) != self.white_count:
            return False
        if len(set(numbers)) != self.white_count:
            return False
        if not all(1 <= n <= self.white_max for n in numbers):
            return False
        if self.has_extra_ball:
            if extra is None or not 1 <= extra <= self.extra_max:
                return False
        elif extra is not None:
            return False
        return True

    def _safe_ticket(self, numbers: List[int], extra: int, confidence: float) -> Dict:
        """Construye un ticket validado."""
        import random
        if not self.validate(numbers, extra):
            numbers = sorted(random.sample(range(1, self.white_max + 1), self.white_count))
            extra = self._random_extra()
            confidence = 0.5
        return {
            'numbers': sorted(numbers),
            'extra': extra,
            'confidence': round(confidence, 4)
        }

    def _random_extra(self):
        """Genera la bola adicional o None para juegos que no la usan."""
        import random
        return random.randint(1, self.extra_max) if self.has_extra_ball else None
