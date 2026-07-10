"""
sync_d1.py — Sube resultados del pipeline a Cloudflare D1

Lee data/cycle_YYYY-MM-DD.json (generado por run.py) e inserta:
  1. Draw resultado en tabla `draws`
  2. Ciclo en tabla `cycles`
  3. Stats por estrategia en `strategy_stats`
  4. Actualiza pesos en `strategies`

Requisitos en .env:
  CLOUDFLARE_ACCOUNT_ID=...
  CLOUDFLARE_API_TOKEN=...       (permiso D1:edit)
  D1_DATABASE_ID=ad168e4c-e90c-4642-8b29-6c8d0bfc6157

Uso:
  python -m engine.pipeline.sync_d1 --date 2025-11-17 --game powerball
  python -m engine.pipeline.sync_d1 --file data/cycle_powerball_2025-11-17.json
  python -m engine.pipeline.sync_d1 --latest           # último JSON en data/

Nota: el JSON generado por run.py se llama cycle_{game_id}_{date}.json
(no cycle_{date}.json — ese era el nombre legacy pre-refactor game-agnostic).
Con --date hay que pasar también --game (default 'powerball') para armar
el nombre correcto. --latest y --file no tienen este problema.
"""

import os
import sys
import json
import argparse
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

ROOT     = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / 'data'

# ── Config ────────────────────────────────────────────────────
ACCOUNT_ID  = os.getenv('CLOUDFLARE_ACCOUNT_ID')
API_TOKEN   = os.getenv('CLOUDFLARE_API_TOKEN')
DATABASE_ID = os.getenv('D1_DATABASE_ID', 'ad168e4c-e90c-4642-8b29-6c8d0bfc6157')

CF_D1_URL = (
    f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}'
    f'/d1/database/{DATABASE_ID}/query'
)

HEADERS = {
    'Authorization': f'Bearer {API_TOKEN}',
    'Content-Type':  'application/json',
}


# ── Estrategia: nombre plano del motor vs. id en D1 ─────────────
def _to_d1_strategy_id(strategy_name: str, lottery_id: str) -> str:
    """
    Traduce el nombre plano del motor (claves de ALL_STRATEGIES, sin
    noción de juego -- p. ej. 'frequency_weighted') al id que usa D1.
    engine/games/register.py sufija con `_{lottery_id}` para cualquier
    juego que no sea powerball, porque `strategies.id` es PRIMARY KEY de
    una sola columna y no puede repetirse entre juegos. Sin esta
    traducción, sync_strategy_weights() nunca encuentra la fila real para
    juegos != powerball y el UPDATE afecta 0 filas (Fase 5, ADR-0001;
    mismo fix aplicado en src/worker.js para la ruta del cron).
    """
    return strategy_name if lottery_id == 'powerball' else f'{strategy_name}_{lottery_id}'


# ── D1 Query helper ───────────────────────────────────────────
def d1(sql: str, params: list = None) -> list:
    """Ejecuta SQL en D1 y retorna rows. Lanza excepción si falla."""
    payload = {'sql': sql}
    if params:
        payload['params'] = [str(p) if not isinstance(p, (int, float, type(None))) else p
                             for p in params]
    resp = requests.post(CF_D1_URL, headers=HEADERS, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data.get('success'):
        errors = data.get('errors', [])
        raise RuntimeError(f'D1 error: {errors}')
    return data['result'][0].get('results', [])


# ── Sync functions ────────────────────────────────────────────
def sync_draw(draw: dict, lottery_id: str = 'powerball') -> int:
    """Inserta draw en D1 si no existe. Retorna el ID."""
    draw_date = draw['draw_date']

    # Check existencia
    rows = d1(
        'SELECT id FROM draws WHERE lottery_id = ? AND draw_date = ?',
        [lottery_id, draw_date]
    )
    if rows:
        draw_id = rows[0]['id']
        print(f'  [draw] Ya existe: {draw_date} (id={draw_id})')
        return draw_id

    d1(
        '''INSERT INTO draws (lottery_id, draw_date, n1, n2, n3, n4, n5, extra, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        [lottery_id, draw_date,
         draw['n1'], draw['n2'], draw['n3'], draw['n4'], draw['n5'],
         draw['pb'], draw.get('source', 'pipeline')]
    )

    rows = d1(
        'SELECT id FROM draws WHERE lottery_id = ? AND draw_date = ?',
        [lottery_id, draw_date]
    )
    draw_id = rows[0]['id']
    print(f'  [draw] Insertado: {draw_date} — {draw["n1"]}-{draw["n2"]}-{draw["n3"]}-{draw["n4"]}-{draw["n5"]} PB:{draw["pb"]} (id={draw_id})')
    return draw_id


def sync_cycle(cycle_data: dict, lottery_id: str = 'powerball') -> int:
    """Inserta o actualiza el ciclo. Retorna cycle_id."""
    draw_date    = cycle_data['draw_date']
    total_tickets = cycle_data.get('total_tickets', 0)
    n_strategies  = len(cycle_data.get('strategy_results', {}))
    executed_at   = cycle_data.get('executed_at', datetime.utcnow().isoformat())

    # Check existencia
    rows = d1(
        'SELECT id FROM cycles WHERE lottery_id = ? AND draw_date = ?',
        [lottery_id, draw_date]
    )
    if rows:
        cycle_id = rows[0]['id']
        # Actualizar a evaluated
        d1(
            '''UPDATE cycles SET status='evaluated', tickets_total=?, strategies_run=?, executed_at=?
               WHERE id=?''',
            [total_tickets, n_strategies, executed_at, cycle_id]
        )
        print(f'  [cycle] Actualizado: {draw_date} (id={cycle_id})')
        return cycle_id

    d1(
        '''INSERT INTO cycles (lottery_id, draw_date, status, tickets_total, strategies_run, executed_at)
           VALUES (?, ?, 'evaluated', ?, ?, ?)''',
        [lottery_id, draw_date, total_tickets, n_strategies, executed_at]
    )
    rows = d1(
        'SELECT id FROM cycles WHERE lottery_id = ? AND draw_date = ?',
        [lottery_id, draw_date]
    )
    cycle_id = rows[0]['id']
    print(f'  [cycle] Insertado: {draw_date} (id={cycle_id})')
    return cycle_id


def sync_strategy_stats(cycle_id: int, draw_date: str,
                        strategy_results: dict, lottery_id: str = 'powerball'):
    """Inserta stats por estrategia para este ciclo."""
    for strategy_name, res in strategy_results.items():
        # strategy_results viene del motor con nombres planos -- traducir
        # al id real de D1 antes de tocar la tabla (Fase 5).
        strategy_id = _to_d1_strategy_id(strategy_name, lottery_id)
        # Upsert — si ya existe para este cycle, actualiza
        rows = d1(
            'SELECT id FROM strategy_stats WHERE cycle_id = ? AND strategy_id = ?',
            [cycle_id, strategy_id]
        )
        if rows:
            d1(
                '''UPDATE strategy_stats
                   SET tickets_count=?, matches_3=?, matches_4=?, matches_5=?,
                       total_prize=?, roi=?, weight_before=?, weight_after=?
                   WHERE cycle_id=? AND strategy_id=?''',
                [res['tickets_count'], res['matches_3'], res['matches_4'], res['matches_5'],
                 res['total_prize'], res['roi'], res['weight_before'], res['weight_after'],
                 cycle_id, strategy_id]
            )
        else:
            d1(
                '''INSERT INTO strategy_stats
                   (cycle_id, strategy_id, lottery_id, draw_date,
                    tickets_count, matches_3, matches_4, matches_5,
                    total_prize, roi, weight_before, weight_after)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                [cycle_id, strategy_id, lottery_id, draw_date,
                 res['tickets_count'], res['matches_3'], res['matches_4'], res['matches_5'],
                 res['total_prize'], res['roi'], res['weight_before'], res['weight_after']]
            )

        roi_pct = res['roi'] * 100
        print(f'  [stats] {strategy_id:25s} ROI:{roi_pct:+.1f}% Prize:${res["total_prize"]:,.0f} '
              f'w:{res["weight_before"]:.4f}→{res["weight_after"]:.4f}')


def sync_strategy_weights(strategy_results: dict, lottery_id: str = 'powerball'):
    """Actualiza current_weight y total_cycles en strategies."""
    for strategy_name, res in strategy_results.items():
        strategy_id = _to_d1_strategy_id(strategy_name, lottery_id)
        d1(
            '''UPDATE strategies
               SET current_weight = ?,
                   status = ?,
                   total_cycles = total_cycles + 1
               WHERE id = ? AND lottery_id = ?''',
            [res['weight_after'], res.get('status', 'active'), strategy_id, lottery_id]
        )
    print(f'  [weights] Actualizados {len(strategy_results)} estrategias')


# ── Main sync ─────────────────────────────────────────────────
def sync_cycle_file(json_path: Path, dry_run: bool = False):
    print(f"\n{'='*60}")
    print(f"  SHIOL+ v9 Sync D1 — {json_path.name}")
    print(f"{'='*60}\n")

    if not json_path.exists():
        print(f'  ❌ Archivo no encontrado: {json_path}')
        sys.exit(1)

    with open(json_path) as f:
        data = json.load(f)

    if data.get('status') == 'pending':
        print('  ⏳ Ciclo pendiente — draw no disponible aún. Nada que sincronizar.')
        return

    draw             = data['draw']
    draw_date        = data['draw_date']
    strategy_results = data['strategy_results']
    lottery_id       = data.get('game_id', 'powerball')

    print(f'  Game:       {lottery_id}')
    print(f'  Draw:       {draw_date}')
    print(f'  Estrategias: {len(strategy_results)}')
    print(f'  Tickets:    {data.get("total_tickets", "?")}')
    print()

    if dry_run:
        print('  [DRY RUN] No se escribirá nada en D1.\n')
        return

    # 1. Draw
    print('[1/4] Sincronizando draw...')
    sync_draw(draw, lottery_id=lottery_id)

    # 2. Ciclo
    print('\n[2/4] Sincronizando ciclo...')
    cycle_id = sync_cycle(data, lottery_id=lottery_id)

    # 3. Stats por estrategia
    print('\n[3/4] Sincronizando strategy_stats...')
    sync_strategy_stats(cycle_id, draw_date, strategy_results, lottery_id=lottery_id)

    # 4. Pesos
    print('\n[4/4] Actualizando pesos adaptativos...')
    sync_strategy_weights(strategy_results, lottery_id=lottery_id)

    print(f"\n{'='*60}")
    print(f'  ✅ Sync completo — {draw_date}')
    print(f"{'='*60}\n")


# ── CLI ───────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='SHIOL+ v9 — Sync pipeline → D1')
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument('--date',   help='Fecha del ciclo (YYYY-MM-DD) — usar junto con --game')
    grp.add_argument('--file',   help='Path directo al JSON')
    grp.add_argument('--latest', action='store_true', help='Último JSON en data/')
    parser.add_argument('--game', type=str, default='powerball',
                        help="ID del juego, solo aplica con --date (default: 'powerball'). "
                             "run.py nombra los archivos cycle_{game}_{date}.json.")
    parser.add_argument('--dry-run', action='store_true', help='No escribe en D1')
    args = parser.parse_args()

    if not ACCOUNT_ID or not API_TOKEN:
        print('❌ Faltan CLOUDFLARE_ACCOUNT_ID o CLOUDFLARE_API_TOKEN en .env')
        sys.exit(1)

    if args.date:
        json_path = DATA_DIR / f'cycle_{args.game}_{args.date}.json'
    elif args.file:
        json_path = Path(args.file)
    else:  # --latest
        files = sorted(DATA_DIR.glob('cycle_*.json'), reverse=True)
        if not files:
            print('❌ No hay archivos cycle_*.json en data/')
            sys.exit(1)
        json_path = files[0]
        print(f'  Usando último ciclo: {json_path.name}')

    sync_cycle_file(json_path, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
