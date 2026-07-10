"""
Adaptive Weight System — Bayesian weight update por estrategia.
Estrategias con ROI positivo aumentan peso; con ROI negativo sostenido → probation → archived.
"""
from typing import Dict


PROBATION_THRESHOLD = 0.05   # peso mínimo antes de probation
ARCHIVE_THRESHOLD   = 0.01   # peso mínimo antes de archivarse
LEARNING_RATE       = 0.1    # qué tan rápido se ajustan los pesos
MIN_CYCLES          = 10     # ciclos mínimos antes de poder archivar


def update_weights(
    current_weights: Dict[str, float],
    cycle_results: Dict[str, Dict],
    total_cycles: Dict[str, int],
) -> Dict[str, Dict]:
    """
    Actualiza pesos basado en ROI del último ciclo.

    Args:
        current_weights: {'strategy_id': weight, ...}
        cycle_results:   {'strategy_id': {'roi': float, ...}, ...}
        total_cycles:    {'strategy_id': int, ...}

    Returns:
        {'strategy_id': {'weight': float, 'status': str, 'delta': float}}
    """
    updates = {}

    for strategy_id, result in cycle_results.items():
        old_weight = current_weights.get(strategy_id, 1.0)
        roi = result.get('roi', 0.0)
        cycles = total_cycles.get(strategy_id, 0)

        # Bayesian-style update: peso se mueve hacia roi_signal
        # roi > 0 → señal positiva → subir peso
        # roi < 0 → señal negativa → bajar peso
        roi_signal = 1.0 + roi   # roi=0.5 → signal=1.5; roi=-0.5 → signal=0.5

        new_weight = old_weight * (1 - LEARNING_RATE) + old_weight * roi_signal * LEARNING_RATE
        new_weight = max(0.001, min(5.0, new_weight))  # clamp

        # Determinar status
        if cycles >= MIN_CYCLES and new_weight <= ARCHIVE_THRESHOLD:
            status = 'archived'
        elif cycles >= MIN_CYCLES and new_weight <= PROBATION_THRESHOLD:
            status = 'probation'
        else:
            status = 'active'

        updates[strategy_id] = {
            'weight':     round(new_weight, 6),
            'status':     status,
            'delta':      round(new_weight - old_weight, 6),
            'roi':        roi,
        }

    return updates


def normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """Normaliza pesos para que sumen 1.0 (útil para sampling proporcional)."""
    total = sum(weights.values())
    if total == 0:
        n = len(weights)
        return {k: 1.0 / n for k in weights}
    return {k: v / total for k, v in weights.items()}
