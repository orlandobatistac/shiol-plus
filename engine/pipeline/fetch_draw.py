"""
Fetch Draw -- obtiene el resultado de un sorteo desde multiples fuentes.

Orden de prioridad (sesion 33, 2026-07-22):
  1. nc_web      -- scraping de nclottery.com (mismo dia del sorteo, game-aware)
  2. nc_csv      -- CSV descargable de NC Lottery (Cash5; mas robusto que web para historico)
  3. ny_data_api -- NY Open Data / Socrata (lag 6-24h, util para historico)
  4. powerball.com -- scraping especifico de Powerball (fallback)
  5. musl_api    -- API MUSL (Powerball; requiere renovacion de API key)

Las ultimas dos (powerball.com, MUSL) son fallbacks especificos de
Powerball -- se saltan automaticamente para cualquier otro juego en vez de
devolver datos incorrectos (Fase 5, ADR-0001).

nc_web es la fuente nueva mas rapida para MM y PB: NC Lottery publica los
resultados en su web el mismo dia del sorteo, sin el lag de Socrata.
Limitacion: solo devuelve el ultimo sorteo disponible en la pagina --
si el cron perdio un sorteo y ya hubo uno nuevo, nc_web no sirve para
el sorteo historico; los fallbacks cubren ese caso.
"""
import re
import csv
import io
import requests
import pandas as pd
from typing import Optional, Dict
from datetime import datetime


def fetch_draw(draw_date: str, game: Dict = None) -> Optional[Dict]:
    """
    Intenta obtener el draw de multiples fuentes en orden de prioridad.

    Args:
        draw_date: 'YYYY-MM-DD'
        game:      game config dict (de engine.games). Si None, usa Powerball.

    Returns:
        {'draw_date', 'n1','n2','n3','n4','n5','pb', 'source'} o None
    """
    # Defaults para Powerball si no se pasa game config
    if game is None:
        from engine.games import get_game
        game = get_game('powerball')

    nc_web_url    = game.get('nc_web_url', '')
    nc_csv_url    = game.get('nc_csv_url', '')
    nc_csv_cols   = game.get('nc_csv_columns', {})
    nc_csv_fmt    = game.get('nc_csv_date_format', '%m/%d/%Y')
    ny_dataset_id = game.get('ny_dataset_id', '')
    # Campo separado para la bola extra en el dataset de Socrata -- None si
    # viene embebida en 'winning_numbers' junto con las 5 blancas (caso
    # Powerball). Mega Millions usa un campo aparte ('mega_ball'): ver
    # ny_extra_ball_field en engine/games/mega_millions.py.
    ny_extra_field = game.get('ny_extra_ball_field')
    has_extra_ball = game.get('has_extra_ball', True)
    white_count    = game.get('white_count', 5)
    game_id        = game.get('id', 'powerball')

    sources = [
        ('nc_web',        lambda d: _from_nc_web(d, nc_web_url, has_extra_ball, white_count)),
        ('nc_csv',        lambda d: _from_nc_csv(d, nc_csv_url, nc_csv_cols, nc_csv_fmt, has_extra_ball)),
        ('ny_data_api',   lambda d: _from_ny_data(d, ny_dataset_id, ny_extra_field, has_extra_ball)),
        ('powerball.com', lambda d: _from_powerball_web(d, game_id)),
        ('musl_api',      lambda d: _from_musl_api(d, game_id)),
    ]

    for source_name, fn in sources:
        try:
            result = fn(draw_date)
            if result:
                result['source'] = source_name
                print(f"OK Draw {draw_date} fetched from {source_name}")
                return result
            else:
                print(f"... {source_name}: draw not available yet")
        except Exception as e:
            print(f"ERR {source_name} error: {e}")

    return None


def _from_nc_web(draw_date: str, url: str, has_extra_ball: bool = True,
                 white_count: int = 5) -> Optional[Dict]:
    """
    Scraping de nclottery.com (SSR) -- fuente primaria para MM, PB y Cash5.

    La pagina es Server-Side Rendered: los resultados estan en el HTML que
    devuelve requests.get, sin necesidad de ejecutar JavaScript.

    Estructura del DOM (verificado 2026-07-22 contra los 3 juegos):
      <div class="part results-box">
        Drawing Date
        Tuesday, Jul 21, 2026
        <li class="ball">25</li>          <- bola blanca
        <li class="ball megaball">10</li> <- bola extra (MM: megaball, PB: powerball)
        ...
      </div>

    El primer .results-box es el sorteo mas reciente. Si la pagina ya
    muestra uno mas nuevo que draw_date solicitado, retorna None y los
    fallbacks (nc_csv, ny_data_api) cubren el historico.
    """
    if not url:
        return None
    from bs4 import BeautifulSoup
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0 Safari/537.36'
        )
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    # Primer bloque de resultados = sorteo mas reciente
    box = soup.find(class_='results-box')
    if not box:
        return None

    # Fecha: "Drawing Date\nTuesday, Jul 21, 2026\n..."
    text = box.get_text(separator='\n', strip=True)
    date_match = re.search(r'(\w+,\s+\w{3}\s+\d{1,2},\s+\d{4})', text)
    if not date_match:
        return None

    try:
        page_date = datetime.strptime(
            date_match.group(1), '%A, %b %d, %Y'
        ).strftime('%Y-%m-%d')
    except ValueError:
        return None

    if page_date != draw_date:
        return None

    # Bolas: class="ball" (blancas) vs class="ball <extra>" (powerball/megaball)
    all_balls = box.find_all(class_='ball')
    whites = [b for b in all_balls if b.get('class') == ['ball']]
    extras = [b for b in all_balls if len(b.get('class', [])) > 1]

    if len(whites) < white_count:
        return None

    w = [int(b.get_text(strip=True)) for b in whites[:white_count]]
    extra = int(extras[0].get_text(strip=True)) if has_extra_ball and extras else None

    if has_extra_ball and extra is None:
        return None

    return {
        'draw_date': draw_date,
        'n1': w[0], 'n2': w[1], 'n3': w[2],
        'n4': w[3], 'n5': w[4],
        'pb': extra,
    }


def _from_ny_data(draw_date: str, dataset_id: str, extra_field: str = None,
                  has_extra_ball: bool = True) -> Optional[Dict]:
    """
    NY State Open Data (Socrata, data.ny.gov) -- alimentado por NY Lottery/MUSL.
    Powerball: dataset 'd6yy-54nr'. Mega Millions: dataset '5xaw-6ayf'.

    El schema de 'winning_numbers' NO es igual entre datasets -- verificado
    contra la API real (Fase de activación de Mega Millions, ADR-0001):
      - Powerball: 'winning_numbers' trae los 6 números juntos
        ('n1 n2 n3 n4 n5 extra').
      - Mega Millions: 'winning_numbers' trae solo las 5 blancas: la bola
        extra viene en un campo separado ('mega_ball').
    `extra_field` indica cuál caso aplica: None = embebido en
    winning_numbers (Powerball); nombre de columna = campo separado (Mega
    Millions). Bug real encontrado: antes de este fix, esta función asumía
    siempre el formato de Powerball y devolvía None para siempre con
    cualquier otro juego que no lo compartiera.
    """
    if not dataset_id:
        return None
    url = (
        f"https://data.ny.gov/resource/{dataset_id}.json"
        f"?$where=draw_date='{draw_date}T00:00:00.000'"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None
    row = rows[0]

    if not has_extra_ball:
        whites = [int(n) for n in row['winning_numbers'].split()]
        if len(whites) != 5:
            return None
        n1, n2, n3, n4, n5 = whites
        extra = None
    elif extra_field:
        # Bola extra en un campo separado (Mega Millions: 'mega_ball').
        whites = [int(n) for n in row['winning_numbers'].split()]
        if len(whites) != 5:
            return None
        n1, n2, n3, n4, n5 = whites
        extra = int(row[extra_field])
    else:
        # Los 6 números juntos en winning_numbers (Powerball).
        nums = [int(n) for n in row['winning_numbers'].split()]
        if len(nums) != 6:
            return None
        n1, n2, n3, n4, n5, extra = nums

    return {
        'draw_date': draw_date,
        'n1': n1, 'n2': n2, 'n3': n3, 'n4': n4, 'n5': n5,
        'pb': extra,
    }


def _from_nc_csv(draw_date: str, url: str, cols: dict, date_fmt: str,
                 has_extra_ball: bool = True) -> Optional[Dict]:
    """Descarga CSV de NC Lottery y busca el draw. Game-agnostic via cols/url."""
    if not url:
        return None
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()

    c = cols  # shorthand
    for parts in csv.reader(io.StringIO(resp.text)):
        parts = [p.strip() for p in parts]
        if len(parts) < 6:
            continue
        try:
            parsed = pd.to_datetime(parts[c.get('date', 0)], format=date_fmt, errors='coerce')
            if pd.isna(parsed) or parsed.strftime('%Y-%m-%d') != draw_date:
                continue
            # El CSV oficial de Cash 5 incluye dos filas por fecha desde 2021:
            # DP=0 es el juego base; DP=1 es Double Play.
            if 'dp' in c and int(parts[c['dp']]) != 0:
                continue
            return {
                'draw_date': draw_date,
                'n1': int(parts[c.get('n1', 1)]),
                'n2': int(parts[c.get('n2', 2)]),
                'n3': int(parts[c.get('n3', 3)]),
                'n4': int(parts[c.get('n4', 4)]),
                'n5': int(parts[c.get('n5', 5)]),
                'pb': int(parts[c.get('extra', 6)]) if has_extra_ball else None,
            }
        except (ValueError, IndexError):
            continue
    return None


def _from_powerball_web(draw_date: str, game_id: str = 'powerball') -> Optional[Dict]:
    """
    Scraping de powerball.com -- solo sirve para Powerball. No hay una
    fuente equivalente game-aware todavía para otros juegos, así que se
    salta explícitamente en vez de devolver un draw real de Powerball
    etiquetado como si fuera de otro juego (bug detectado en Fase 5,
    ADR-0001).
    """
    if game_id != 'powerball':
        return None
    try:
        from bs4 import BeautifulSoup
        url = "https://www.powerball.com/all-winning-numbers"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Buscar en la tabla de resultados
        for row in soup.select('tr, .result-row, [class*="winning"]'):
            text = row.get_text()
            if draw_date in text or _date_match(text, draw_date):
                nums = _extract_numbers(text)
                if nums and len(nums) >= 6:
                    return {
                        'draw_date': draw_date,
                        'n1': nums[0], 'n2': nums[1], 'n3': nums[2],
                        'n4': nums[3], 'n5': nums[4], 'pb': nums[5]
                    }
    except Exception:
        pass
    return None


def _from_musl_api(draw_date: str, game_id: str = 'powerball') -> Optional[Dict]:
    """
    MUSL REST API -- mismo caso que _from_powerball_web: el endpoint es
    específico de Powerball, así que se salta explícitamente para
    cualquier otro juego (Fase 5, ADR-0001).
    """
    if game_id != 'powerball':
        return None
    url = f"https://data.musl.org/latest-powerball/?format=json"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        date = data.get('date', data.get('draw_date', ''))
        if pd.to_datetime(date, errors='coerce').strftime('%Y-%m-%d') == draw_date:
            nums = data.get('numbers', data.get('winning_numbers', '').split())
            pb = data.get('powerball', data.get('pb'))
            if nums and pb:
                nums = [int(n) for n in nums[:5]]
                return {
                    'draw_date': draw_date,
                    'n1': nums[0], 'n2': nums[1], 'n3': nums[2],
                    'n4': nums[3], 'n5': nums[4], 'pb': int(pb)
                }
    except Exception:
        pass
    return None


def _extract_numbers(text: str):
    import re
    return [int(n) for n in re.findall(r'\b([1-9][0-9]?)\b', text)]


def _date_match(text: str, draw_date: str) -> bool:
    try:
        dt = datetime.strptime(draw_date, '%Y-%m-%d')
        variants = [
            dt.strftime('%m/%d/%Y'),
            dt.strftime('%-m/%-d/%Y'),
            dt.strftime('%B %d, %Y'),
        ]
        return any(v in text for v in variants)
    except Exception:
        return False
