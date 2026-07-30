"""
Pipeline Runner — orquesta el ciclo completo para un draw y juego dados.

Uso:
    python -m engine.pipeline.run --game powerball --date 2025-12-01
    python -m engine.pipeline.run --game mega_millions --date 2025-12-03
    python -m engine.pipeline.run  # usa powerball + próximo draw esperado
"""
import sys
import json
import argparse
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

ROOT      = Path(__file__).parent.parent.parent
DATA_DIR  = ROOT / 'data'


def load_weights(game_id: str) -> dict:
    weights_file = DATA_DIR / f'strategy_weights_{game_id}.json'
    if weights_file.exists():
        with open(weights_file) as f:
            return json.load(f)
    from engine.strategies import ALL_STRATEGIES
    return {name: 1.0 for name in ALL_STRATEGIES}


def save_weights(game_id: str, weights: dict):
    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_DIR / f'strategy_weights_{game_id}.json', 'w') as f:
        json.dump(weights, f, indent=2)


def load_draws(game_id: str) -> pd.DataFrame:
    """Carga histórico desde CSV local del juego."""
    csv = DATA_DIR / f'{game_id}_draws.csv'
    if not csv.exists():
        # fallback al nombre legacy para powerball
        csv = DATA_DIR / 'powerball_draws.csv'
    return pd.read_csv(csv, parse_dates=['draw_date'])


def run_pipeline(game_id: str, draw_date: str,
                 tickets_per_strategy: int = 20, dry_run: bool = False):
    """
    Ciclo completo game-agnostic:
    1. Cargar game config
    2. Cargar histórico + pesos
    3. Generar tickets por estrategia compatible
    4. Fetch draw real
    5. Evaluar tickets vs draw
    6. Actualizar pesos
    7. Guardar JSON para sync a D1
    """
    from engine.games import get_game, get_lottery_config
    from engine.strategies import get_compatible_strategies
    from engine.pipeline.fetch_draw import fetch_draw
    from engine.pipeline.evaluate import evaluate_strategy
    from engine.pipeline.weights import update_weights

    game         = get_game(game_id)
    lottery_cfg  = get_lottery_config(game_id)
    strategies   = get_compatible_strategies(game)

    print(f"\n{'='*60}")
    print(f"  SHIOL+ v9 — {game['name']} | Draw: {draw_date}")
    print(f"{'='*60}\n")

    draws           = load_draws(game_id)
    current_weights = load_weights(game_id)

    # ── STEP 1: Generar tickets ────────────────────────────────
    print(f"[1] Generando {tickets_per_strategy} tickets × {len(strategies)} estrategias...")
    generated = {}
    for name, StratClass in strategies.items():
        strategy = StratClass(lottery_cfg)
        tickets  = strategy.generate(draws, count=tickets_per_strategy)
        generated[name] = tickets
        print(f"  ✓ {name}: {len(tickets)} tickets")

    total_tickets = sum(len(t) for t in generated.values())
    print(f"\n  Total: {total_tickets} tickets\n")

    # ── STEP 2: Fetch draw ─────────────────────────────────────
    print(f"[2] Buscando resultado del draw {draw_date} ({game['name']})...")
    draw = fetch_draw(draw_date, game=game)

    if not draw:
        print(f"  ⏳ Draw {draw_date} no disponible aún.")
        return {'status': 'pending', 'draw_date': draw_date, 'game_id': game_id}

    winning = [draw['n1'], draw['n2'], draw['n3'], draw['n4'], draw['n5']]
    extra_label = f" {game['extra_name']}:{draw['pb']}" if game.get('has_extra_ball', True) else ''
    print(f"  🎱 {winning}{extra_label} (fuente: {draw['source']})\n")

    # ── STEP 3: Evaluar ────────────────────────────────────────
    print("[3] Evaluando estrategias...")
    eval_results  = {}
    total_cycles  = {name: 1 for name in strategies}

    for name, tickets in generated.items():
        result = evaluate_strategy(tickets, draw, game=game)
        eval_results[name] = result
        print(f"  {name:25s} | ROI: {result['roi']*100:+.1f}% | "
              f"Prize: ${result['total_prize']:,.0f} | "
              f"3m:{result['matches_3']} 4m:{result['matches_4']} 5m:{result['matches_5']}")

    # ── STEP 4: Pesos ──────────────────────────────────────────
    print("\n[4] Actualizando pesos adaptativos...")
    weight_updates = update_weights(current_weights, eval_results, total_cycles)

    for name, upd in weight_updates.items():
        delta = upd['delta']
        status_tag = f"[{upd['status']}]" if upd['status'] != 'active' else ''
        print(f"  {name:25s} | {current_weights.get(name,1.0):.4f} → "
              f"{upd['weight']:.4f} ({delta:+.4f}) {status_tag}")

    new_weights = {name: upd['weight'] for name, upd in weight_updates.items()}
    if not dry_run:
        save_weights(game_id, new_weights)

    # ── STEP 5: Guardar JSON ───────────────────────────────────
    output = {
        'game_id':    game_id,
        'draw_date':  draw_date,
        'draw':       draw,
        'total_tickets': total_tickets,
        'strategy_results': {
            name: {
                'tickets_count': res['tickets_count'],
                'matches_3':     res['matches_3'],
                'matches_4':     res['matches_4'],
                'matches_5':     res['matches_5'],
                'total_prize':   res['total_prize'],
                'roi':           res['roi'],
                'weight_before': current_weights.get(name, 1.0),
                'weight_after':  weight_updates[name]['weight'],
                'status':        weight_updates[name]['status'],
            }
            for name, res in eval_results.items()
        },
        'executed_at': datetime.utcnow().isoformat(),
    }

    out_file = DATA_DIR / f"cycle_{game_id}_{draw_date}.json"
    if not dry_run:
        DATA_DIR.mkdir(exist_ok=True)
        with open(out_file, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"\n  💾 {out_file.name}")

    print(f"\n{'='*60}")
    print(f"  Pipeline completado ✅")
    print(f"{'='*60}\n")
    return {'status': 'completed', **output}


def main():
    parser = argparse.ArgumentParser(description='SHIOL+ v9 Pipeline')
    parser.add_argument('--game',    type=str, default='powerball',
                        help='ID del juego (default: powerball)')
    parser.add_argument('--date',    type=str, default=None,
                        help='Draw date YYYY-MM-DD')
    parser.add_argument('--tickets', type=int, default=20,
                        help='Tickets por estrategia')
    parser.add_argument('--dry-run', action='store_true',
                        help='No guardar resultados')
    args = parser.parse_args()

    if args.date:
        draw_date = args.date
    else:
        from engine.games import get_game
        game = get_game(args.game)
        day_map = {'Monday': 0, 'Wednesday': 2, 'Saturday': 5,
                   'Tuesday': 1, 'Friday': 4}
        draw_nums = {day_map[d] for d in game['draw_days'] if d in day_map}
        today = datetime.now()
        draw_date = None
        for i in range(7):
            candidate = today + timedelta(days=i)
            if candidate.weekday() in draw_nums:
                draw_date = candidate.strftime('%Y-%m-%d')
                break
        if not draw_date:
            print("No se pudo determinar próximo draw. Usa --date.")
            sys.exit(1)

    run_pipeline(args.game, draw_date,
                 tickets_per_strategy=args.tickets,
                 dry_run=args.dry_run)


if __name__ == '__main__':
    main()
