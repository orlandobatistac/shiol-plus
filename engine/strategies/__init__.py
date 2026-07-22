from .frequency_weighted  import FrequencyWeightedStrategy
from .cooccurrence        import CooccurrenceStrategy
from .range_balanced      import RangeBalancedStrategy
from .coverage_optimizer  import CoverageOptimizerStrategy
from .xgboost_ml          import XGBoostMLStrategy
from .hybrid_ensemble     import HybridEnsembleStrategy
from .intelligent_scoring import IntelligentScoringStrategy
from .random_baseline     import RandomBaselineStrategy
from .wheeling            import WheelingStrategy

ALL_STRATEGIES = {
    'frequency_weighted':  FrequencyWeightedStrategy,
    'cooccurrence':        CooccurrenceStrategy,
    'range_balanced':      RangeBalancedStrategy,
    'coverage_optimizer':  CoverageOptimizerStrategy,
    'xgboost_ml':          XGBoostMLStrategy,
    'hybrid_ensemble':     HybridEnsembleStrategy,
    'intelligent_scoring': IntelligentScoringStrategy,
    'random_baseline':     RandomBaselineStrategy,
    'wheeling':            WheelingStrategy,
}


def get_strategy(name: str, lottery_config: dict):
    """
    Instancia una estrategia con el config del juego.

    Args:
        name:           ID de la estrategia
        lottery_config: dict — usar engine.games.get_lottery_config(game_id)
    """
    if name not in ALL_STRATEGIES:
        raise ValueError(
            f"Estrategia '{name}' no existe. "
            f"Disponibles: {list(ALL_STRATEGIES.keys())}"
        )
    return ALL_STRATEGIES[name](lottery_config)


def get_compatible_strategies(game: dict) -> dict:
    """Retorna estrategias compatibles con el juego dado."""
    compat = game.get('compatible_strategies', 'all')
    if compat == 'all':
        return ALL_STRATEGIES
    return {k: v for k, v in ALL_STRATEGIES.items() if k in compat}
