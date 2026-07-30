"""
Fetch Jackpot -- obtiene el jackpot estimado actual (del próximo sorteo) de
cada juego.

Fuente: nclottery.com (NC Education Lottery, revendedor oficial de ambos
juegos). Se eligió esta fuente en vez de powerball.com/megamillions.com
directos tras verificar las tres opciones con requests reales:

  - powerball.com: server-renderiza el valor en el HTML inicial, pero su
    CDN (Azure Front Door) responde de forma intermitente con contenido
    binario/incompleto -- ~1 de cada 4 intentos fallaba en pruebas reales
    (2026-07-07), aun con headers de navegador normales.
  - megamillions.com: el valor se carga por JS contra un servicio interno
    no documentado (ASMX) -- funciona, pero es un endpoint no pensado para
    consumo externo y sin ninguna garantía de estabilidad.
  - nclottery.com: sirve AMBOS juegos con el mismo patrón (ASP.NET
    WebForms, ids de control estables y únicos por campo), 100% consistente
    en pruebas repetidas (3/3 en ambos juegos), y ya es una fuente conocida
    del proyecto (fetch_draw.py ya la usa como fallback de resultados, ver
    nc_csv_url en engine/games/*.py). Un solo parser, una sola fuente,
    mismo nivel de confianza para los dos juegos.

Estructura real (verificada 2026-07-07):
    Powerball (https://nclottery.com/Powerball):
        <span id="...lblPBJackpot" class="prize">$434 Million</span>
        <span id="...lblPBCash" class="cash">Cash Value $194.7 Million</span>
    Mega Millions (https://nclottery.com/Mega-Millions):
        <span id="...lblMMPrize" class="prize">$576 Million</span>
        <span id="...lblMMCash" class="cash">Cash Value $253.9 Million</span>

Validador de sanidad: cualquier valor fuera del rango histórico plausible (o
que no se pudo extraer) se trata como fallo, no como dato -- ver
JACKPOT_SANITY_RANGE y JackpotValidationError. El caller (server.py) decide
qué hacer con un fallo (típicamente: mantener el último valor bueno que ya
había en D1); este módulo nunca devuelve un número que no pasó el validador.

Riesgo aceptado a propósito (documentado, no un bug): sigue siendo scraping
de una página pública sin contrato ni SLA -- puede cambiar de estructura sin
aviso. El validador + el prefijo [jackpot-scrape][ALERT] en los logs existen
específicamente para que ese día se note rápido en vez de fallar en
silencio. Además se reintenta un par de veces por si hay una falla de red
transitoria (mismo patrón defensivo que se aplicaba a powerball.com, se deja
por las dudas aunque nclottery.com se probó mucho más estable).
"""
import re
from typing import Dict, Optional

import requests

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

NC_LOTTERY_URLS = {
    "powerball": "https://nclottery.com/Powerball",
    "mega_millions": "https://nclottery.com/Mega-Millions",
    "cash5": "https://nclottery.com/cash5",
}

# id de control ASP.NET (sufijo, único por campo) para el jackpot anunciado
# y el valor en efectivo, por juego.
NC_LOTTERY_FIELD_IDS = {
    "powerball":     {"amount": "lblPBJackpot", "cash_value": "lblPBCash"},
    "mega_millions": {"amount": "lblMMPrize",   "cash_value": "lblMMCash"},
    "cash5":         {"amount": "lblC5Prize",   "cash_value": None},
}

# Rango de sanidad conocido para ambos juegos: el jackpot mínimo de arranque
# ronda los $20M, y el récord histórico real hasta ahora es ~$2.04B
# (Powerball, nov 2022). Se deja margen hasta $5B para no romper si algún
# día se supera el récord.
JACKPOT_SANITY_RANGE = (20_000_000, 5_000_000_000)


class JackpotValidationError(Exception):
    """
    El valor obtenido no pasó el validador de sanidad -- probable señal de
    que el HTML de la fuente cambió de estructura (o falló el request).
    """


def _validate(amount: Optional[float], cash_value: Optional[float], game_id: str) -> None:
    lo, hi = (100_000, 10_000_000) if game_id == 'cash5' else JACKPOT_SANITY_RANGE
    if amount is None or not (lo <= amount <= hi):
        raise JackpotValidationError(
            f"[jackpot-scrape][ALERT] {game_id}: jackpot amount fuera de rango o no "
            f"encontrado (valor={amount!r}, rango esperado=${lo:,}-${hi:,}). "
            f"Revisar si nclottery.com cambió de estructura."
        )
    if game_id == 'cash5':
        return
    if cash_value is None or not (lo * 0.2 <= cash_value <= hi):
        raise JackpotValidationError(
            f"[jackpot-scrape][ALERT] {game_id}: cash_value fuera de rango o no "
            f"encontrado (valor={cash_value!r}). Revisar si nclottery.com cambió de estructura."
        )


def _parse_dollar_amount(number_str: str, unit: str) -> float:
    n = float(number_str.replace(",", ""))
    return n * (1_000_000_000 if unit.lower().startswith("b") else 1_000_000)


def _extract_field(html: str, id_suffix: str) -> Optional[tuple]:
    """
    Busca el span con id que termina en `id_suffix` y extrae el primer
    "$X Million"/"$X Billion" que aparece en su contenido (soporta texto
    extra antes del monto, ej. "Cash Value $194.7 Million").
    """
    pattern = rf'id="[^"]*{re.escape(id_suffix)}"[^>]*>[^<]*\$([\d,\.]+)\s*(Million|Billion)'
    m = re.search(pattern, html)
    return m.groups() if m else None


def _extract_plain_dollars(html: str, id_suffix: str) -> Optional[float]:
    pattern = rf'id="[^"]*{re.escape(id_suffix)}"[^>]*>[^<]*\$([\d,]+)'
    match = re.search(pattern, html)
    return float(match.group(1).replace(',', '')) if match else None


def _fetch_from_nc_lottery(game_id: str) -> Dict:
    url = NC_LOTTERY_URLS[game_id]
    field_ids = NC_LOTTERY_FIELD_IDS[game_id]

    html = None
    last_error = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
            resp.raise_for_status()
            if field_ids["amount"] in resp.text:
                html = resp.text
                break
            last_error = (
                f"respuesta sin el marcador esperado (intento {attempt + 1}/3, "
                f"len={len(resp.text)})"
            )
        except requests.RequestException as e:
            last_error = f"{type(e).__name__}: {e} (intento {attempt + 1}/3)"

    if html is None:
        raise JackpotValidationError(
            f"[jackpot-scrape][ALERT] {game_id}: no se pudo obtener HTML válido de "
            f"nclottery.com tras 3 intentos -- último error: {last_error}."
        )

    if game_id == 'cash5':
        amount = _extract_plain_dollars(html, field_ids['amount'])
        if amount is None:
            raise JackpotValidationError(
                f"[jackpot-scrape][ALERT] cash5: no se encontro lblC5Prize en nclottery.com."
            )
        return {"amount": amount, "cash_value": None, "source": "nclottery.com"}

    amount_match = _extract_field(html, field_ids["amount"])
    cash_match = _extract_field(html, field_ids["cash_value"])
    if not amount_match or not cash_match:
        raise JackpotValidationError(
            f"[jackpot-scrape][ALERT] {game_id}: no se encontraron los campos esperados "
            f"({field_ids['amount']}/{field_ids['cash_value']}) en el HTML de "
            f"nclottery.com. El markup puede haber cambiado -- revisar el parser."
        )

    return {
        "amount": _parse_dollar_amount(*amount_match),
        "cash_value": _parse_dollar_amount(*cash_match),
        "source": "nclottery.com",
    }


def fetch_jackpot(game_id: str) -> Optional[Dict]:
    """
    Punto de entrada único. Nunca lanza -- devuelve None y loguea (con el
    prefijo [jackpot-scrape][ALERT] cuando es un fallo de parseo/validación,
    para que sea fácil de encontrar/grep en los logs) si algo falla. El
    caller decide qué hacer con un None (típicamente: mantener el último
    valor bueno en D1 en vez de sobreescribir con basura).
    """
    if game_id not in NC_LOTTERY_URLS:
        print(f"[jackpot-scrape][ALERT] game_id desconocido: {game_id!r}")
        return None
    try:
        result = _fetch_from_nc_lottery(game_id)
        _validate(result.get("amount"), result.get("cash_value"), game_id)
        cash_note = (f" (cash ${result['cash_value']:,.0f})"
                     if result.get('cash_value') is not None else '')
        print(f"OK Jackpot {game_id}: ${result['amount']:,.0f}{cash_note} via {result['source']}")
        return result
    except JackpotValidationError as e:
        print(str(e))
        return None
    except Exception as e:
        print(
            f"[jackpot-scrape][ALERT] {game_id}: fallo inesperado al hacer fetch/parse "
            f"({type(e).__name__}: {e}). Revisar conectividad o si la fuente cambió."
        )
        return None
