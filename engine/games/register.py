"""
SHIOL+ v9 — Game Registration CLI
Registra un juego en D1 y hace backfill del histórico.

Uso:
    python -m engine.games register powerball
    python -m engine.games register mega_millions
    python -m engine.games backfill powerball --from 2020-01-01
    python -m engine.games list

IMPORTANTE — `register`/`backfill` escriben en D1 de PRODUCCIÓN por defecto,
en caliente, sin ambiente de prueba: `d1()` (más abajo) pega directo a la API
REST de Cloudflare usando las credenciales reales de `.env`. Antes de correr
estos comandos contra un juego nuevo, usá `--local` primero para verificar
todo (seed + backfill completo) contra el D1 simulado por `wrangler dev
--local` -- mismo esquema, cero riesgo de dejar un juego "activo pero roto"
en producción si todavía falta desplegar código relacionado (ver
docs/adr/0001-python-first-engine-docker-cloudflare-standby.md y TODO.md,
sesión 14). Ejemplo:
    python -m engine.games register mega_millions --local
    python -m engine.games backfill mega_millions --from 2017-10-31 --local
    # una vez verificado con QA manual en localhost, recién ahí:
    python -m engine.games register mega_millions
    python -m engine.games backfill mega_millions --from 2017-10-31
"""
import os
import sys
import json
import argparse
import subprocess
import tempfile
import csv
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / '.env')

REPO_ROOT = Path(__file__).parent.parent.parent

ACCOUNT_ID  = os.getenv('CLOUDFLARE_ACCOUNT_ID')
API_TOKEN   = os.getenv('CLOUDFLARE_API_TOKEN')
DATABASE_ID = os.getenv('D1_DATABASE_ID')

# Debe coincidir con wrangler.toml -> [[d1_databases]] -> database_name.
# Hardcodeado a propósito (no se parsea wrangler.toml) para no depender de
# `tomllib`/una librería TOML en el Python que sea que corra este CLI.
D1_DATABASE_NAME = 'shiol-plus-db'

CF_D1_URL = (
    f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}'
    f'/d1/database/{DATABASE_ID}/query'
)

HEADERS = {
    'Authorization': f'Bearer {API_TOKEN}',
    'Content-Type':  'application/json',
}

from engine.strategies import ALL_STRATEGIES


# ── D1 helpers ────────────────────────────────────────────────────────────────

def d1(sql: str, params: list = None):
    """Escribe/lee en D1 de PRODUCCIÓN vía la API REST de Cloudflare."""
    payload = {'sql': sql, 'params': params or []}
    r = requests.post(CF_D1_URL, json=payload, headers=HEADERS, timeout=30)
    r.raise_for_status()
    result = r.json()
    if not result.get('success'):
        raise RuntimeError(f"D1 error: {result.get('errors')}")
    return result['result'][0] if result.get('result') else {}


def _sql_literal(v):
    """
    Convierte un valor Python a un literal SQL embebible directo en el
    statement. Necesario porque `wrangler d1 execute --local` no soporta
    bind params posicionales como sí lo hace la API REST de producción
    (`d1()` de arriba) -- ver d1_local().
    """
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, (int, float)):
        return str(v)
    # Escapar comillas simples al estilo SQL estándar ('' representa una
    # comilla literal dentro de un string).
    return "'" + str(v).replace("'", "''") + "'"


def d1_local(sql: str, params: list = None):
    """
    Ejecuta un statement contra D1 LOCAL -- el SQLite que simula `wrangler
    dev --local --persist` (mismo esquema que producción, sin tocarla). No
    existe una API REST para D1 local, así que este helper arma un archivo
    .sql temporal con los valores ya interpolados (evita el problema real de
    doble expansión de shell que apareció al intentar pasar SQL por
    `--command` a través de WSL/Windows -- ver TODO.md sesión 14) y lo
    ejecuta con `npx wrangler d1 execute --local --file=...`.

    No requiere `CLOUDFLARE_ACCOUNT_ID`/`API_TOKEN` -- D1 local no usa la API
    de Cloudflare en absoluto. Sí requiere correrse desde una máquina con
    `node`/`wrangler` instalados y estar parado en la raíz del repo (mismo
    directorio que `wrangler.toml`/`node_modules`), igual que cualquier otro
    comando de `wrangler`.
    """
    query = sql
    for p in (params or []):
        query = query.replace('?', _sql_literal(p), 1)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.sql', delete=False, encoding='utf-8'
        ) as f:
            f.write(query)
            tmp_path = f.name

        result = subprocess.run(
            ['npx', 'wrangler', 'd1', 'execute', D1_DATABASE_NAME,
             '--local', f'--file={tmp_path}', '--json'],
            capture_output=True, text=True, timeout=30,
            cwd=REPO_ROOT, shell=(os.name == 'nt'),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"wrangler d1 execute --local falló (exit {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        try:
            data = json.loads(result.stdout)
            return data[0]['results'][0] if data and data[0].get('results') else {}
        except (json.JSONDecodeError, IndexError, KeyError):
            # wrangler a veces mezcla texto informativo con el JSON en stdout;
            # no es un error real si returncode fue 0.
            return {}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ── Comandos ──────────────────────────────────────────────────────────────────

def cmd_list(_args):
    """Lista todos los juegos registrados en D1."""
    from engine.games import ALL_GAMES, ACTIVE_GAMES
    print(f"\n{'Juego':<20} {'Activo':<8} {'Días sorteo':<25} {'Bolas'}")
    print('-' * 70)
    for gid, g in ALL_GAMES.items():
        active = '✅' if g['active'] else '❌'
        days = ', '.join(g['draw_days'])
        balls = f"{g['white_count']}×{g['white_max']} + {g['extra_name']} 1-{g['extra_max']}"
        print(f"{g['name']:<20} {active:<8} {days:<25} {balls}")
    print()


def cmd_register(args):
    """Registra un juego en D1 y hace seed de sus estrategias."""
    from engine.games import get_game
    game  = get_game(args.game_id)
    gid   = game['id']
    d1_fn = d1_local if args.local else d1

    target = "💻 LOCAL (D1 simulado por wrangler dev)" if args.local else "⚠️  PRODUCCIÓN (D1 real de Cloudflare)"
    print(f"\n📋 Registrando {game['name']} en D1 -- destino: {target}")

    # 1. Insertar/actualizar lottery
    d1_fn("""
        INSERT OR REPLACE INTO lotteries
            (id, name, draw_days, white_ball_count, white_ball_max,
             extra_ball_name, extra_ball_max, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        gid,
        game['name'],
        ','.join(d[:3].lower() for d in game['draw_days']),
        game['white_count'],
        game['white_max'],
        game['extra_name'] or '',
        game['extra_max'] or 0,
        1 if game['active'] else 0,
    ])
    print(f"  ✓ Lottery '{gid}' registrada")

    # 2. Seed de estrategias
    strategies = list(ALL_STRATEGIES.keys())
    seeded = 0
    for sid in strategies:
        nice_name = sid.replace('_', ' ').title()
        d1_fn("""
            INSERT OR IGNORE INTO strategies
                (id, lottery_id, name, description, status, current_weight)
            VALUES (?, ?, ?, ?, 'active', 1.0)
        """, [f"{sid}_{gid}" if gid != 'powerball' else sid, gid, nice_name, ''])
        seeded += 1
    print(f"  ✓ {seeded} estrategias seeded")

    print(f"\n✅ {game['name']} listo en {'local' if args.local else 'PRODUCCIÓN'}. Próximo paso:")
    print(f"   python -m engine.games backfill {gid}{' --local' if args.local else ''}\n")


def cmd_backfill(args):
    """
    Descarga histórico desde NY Open Data (Socrata) e inserta en D1.

    Antes usaba directo game['nc_csv_url'] -- ese endpoint quedó 404 (NC
    Lottery cambió su estructura de URLs, verificado 2026-07-04) y este
    comando nunca se actualizó al fix de ny_data_api que sí se aplicó en
    fetch_draw.py/worker.js. Bug real detectado y arreglado al activar
    Mega Millions (ADR-0001): correr este backfill hoy explotaba con un
    404 apenas se intentaba.
    """
    from engine.games import get_game
    game        = get_game(args.game_id)
    if game['id'] == 'cash5' or getattr(args, 'csv_path', None):
        return _cmd_backfill_cash5(args, game)
    from_date   = args.from_date or '2010-01-01'
    dataset_id  = game.get('ny_dataset_id', '')
    extra_field = game.get('ny_extra_ball_field')
    d1_fn       = d1_local if args.local else d1

    if not dataset_id:
        print(f"❌ '{game['name']}' no tiene ny_dataset_id configurado -- no se puede hacer backfill.")
        return

    target = "💻 LOCAL (D1 simulado por wrangler dev)" if args.local else "⚠️  PRODUCCIÓN (D1 real de Cloudflare)"
    print(f"\n📥 Backfill {game['name']} desde {from_date} -- destino: {target}")
    print(f"   Fuente: ny_data_api (dataset {dataset_id})")

    # Socrata devuelve el dataset completo en un solo request si el límite
    # alcanza (probado con 2516 filas de Mega Millions sin paginar). `params=`
    # deja que requests arme el query string bien encodeado (los operadores
    # SoQL como '>=' y 'ASC' necesitan espacios que a mano hay que escapar).
    resp = requests.get(
        f"https://data.ny.gov/resource/{dataset_id}.json",
        params={
            '$where': f"draw_date >= '{from_date}T00:00:00.000'",
            '$order': 'draw_date ASC',
            '$limit': 5000,
        },
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()

    draws = []
    for row in rows:
        try:
            date_str = row['draw_date'][:10]  # 'YYYY-MM-DDT00:00:00.000' -> 'YYYY-MM-DD'
            if extra_field:
                # Bola extra en un campo separado (p. ej. Mega Millions: 'mega_ball').
                whites = [int(n) for n in row['winning_numbers'].split()]
                if len(whites) != 5:
                    continue
                n1, n2, n3, n4, n5 = whites
                extra = int(row[extra_field])
            else:
                # Los 6 números juntos en winning_numbers (Powerball).
                nums = [int(n) for n in row['winning_numbers'].split()]
                if len(nums) != 6:
                    continue
                n1, n2, n3, n4, n5, extra = nums
            draws.append({
                'date': date_str,
                'n1': n1, 'n2': n2, 'n3': n3, 'n4': n4, 'n5': n5,
                'extra': extra,
            })
        except (ValueError, KeyError, IndexError):
            continue

    print(f"   {len(draws)} draws encontrados desde {from_date}")

    # Insertar en D1 (batch de 50 para no sobrecargar)
    inserted = skipped = 0
    batch_size = 50
    for i in range(0, len(draws), batch_size):
        batch = draws[i:i+batch_size]
        for draw in batch:
            try:
                d1_fn("""
                    INSERT OR IGNORE INTO draws
                        (lottery_id, draw_date, n1, n2, n3, n4, n5, extra, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ny_data_api_backfill')
                """, [
                    game['id'], draw['date'],
                    draw['n1'], draw['n2'], draw['n3'],
                    draw['n4'], draw['n5'], draw['extra'],
                ])
                inserted += 1
            except Exception as e:
                if 'UNIQUE' in str(e):
                    skipped += 1
                else:
                    print(f"  ⚠️  Error en {draw['date']}: {e}")
        print(f"  → {min(i+batch_size, len(draws))}/{len(draws)} procesados...", end='\r')

    print(f"\n  ✓ {inserted} draws insertados, {skipped} ya existían")
    print(f"\n✅ Backfill completo para {game['name']} en {'local' if args.local else 'PRODUCCIÓN'}\n")


# ── Entrypoint ────────────────────────────────────────────────────────────────

def _cash5_draws_from_csv(path: Path):
    """Lee el CSV oficial NCEL, conservando solo Cash 5 base (DP=0)."""
    draws = []
    double_play = invalid = 0
    with path.open(newline='', encoding='utf-8-sig') as handle:
        for row in csv.DictReader(handle):
            try:
                date = datetime.strptime(row['Date'], '%m/%d/%Y').strftime('%Y-%m-%d')
                numbers = [int(row[f'Ball {i}']) for i in range(1, 6)]
                if int(row['DP']) != 0:
                    double_play += 1
                    continue
                if len(set(numbers)) != 5 or not all(1 <= n <= 43 for n in numbers):
                    raise ValueError('numeros fuera de las reglas de Cash 5')
                draws.append({'date': date, 'numbers': numbers})
            except (KeyError, TypeError, ValueError):
                invalid += 1
    return draws, double_play, invalid


def _cmd_backfill_cash5(args, game):
    if not args.csv_path:
        raise ValueError('Cash 5 requiere --csv con el archivo oficial descargado de NCEL')
    csv_path = Path(args.csv_path)
    if not csv_path.is_file():
        raise FileNotFoundError(f'CSV no encontrado: {csv_path}')

    draws, double_play, invalid = _cash5_draws_from_csv(csv_path)
    if args.from_date:
        draws = [draw for draw in draws if draw['date'] >= args.from_date]
    draws.sort(key=lambda draw: draw['date'])
    if not draws:
        raise ValueError('El CSV no contiene sorteos Cash 5 base validos')

    d1_fn = d1_local if args.local else d1
    target = 'LOCAL' if args.local else 'PRODUCCION'
    print(f"\nBackfill {game['name']} -> {target}")
    print(f'   CSV: {csv_path}')
    print(f"   Base validos: {len(draws)} ({draws[0]['date']} -> {draws[-1]['date']})")
    print(f'   Double Play excluidos: {double_play}; filas invalidas/informativas: {invalid}')

    processed = 0
    batch_size = 500 if args.local else 100
    for offset in range(0, len(draws), batch_size):
        batch = draws[offset:offset + batch_size]
        placeholders = ','.join(['(?,?,?,?,?,?,?,NULL,?)'] * len(batch))
        params = []
        for draw in batch:
            params.extend([game['id'], draw['date'], *draw['numbers'], 'ncel_cash5_csv_backfill'])
        d1_fn(f"""
            INSERT OR IGNORE INTO draws
                (lottery_id, draw_date, n1, n2, n3, n4, n5, extra, source)
            VALUES {placeholders}
        """, params)
        processed += len(batch)
        print(f'   -> {processed}/{len(draws)} procesados', end='\r')
    print(f'\nBackfill Cash 5 completo: {processed} filas procesadas de forma idempotente.\n')


def main():
    parser = argparse.ArgumentParser(description='SHIOL+ Game Manager')
    sub    = parser.add_subparsers(dest='cmd')

    # list
    sub.add_parser('list', help='Lista juegos registrados')

    # register
    p_reg = sub.add_parser('register', help='Registra un juego en D1')
    p_reg.add_argument('game_id', help='ID del juego (powerball, mega_millions...)')
    p_reg.add_argument('--local', action='store_true',
                       help='Escribe en D1 LOCAL (wrangler dev --local) en vez de producción')

    # backfill
    p_bf = sub.add_parser('backfill', help='Importa histórico a D1')
    p_bf.add_argument('game_id', help='ID del juego')
    p_bf.add_argument('--from', dest='from_date', default=None,
                      help='Fecha inicio YYYY-MM-DD (default: 2010-01-01)')
    p_bf.add_argument('--csv', dest='csv_path', default=None,
                      help='CSV oficial NCEL (requerido para Cash 5)')
    p_bf.add_argument('--local', action='store_true',
                      help='Escribe en D1 LOCAL (wrangler dev --local) en vez de producción')

    args = parser.parse_args()

    if args.cmd == 'list':
        cmd_list(args)
    elif args.cmd == 'register':
        cmd_register(args)
    elif args.cmd == 'backfill':
        cmd_backfill(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
