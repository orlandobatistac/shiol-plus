"""
engine/server.py — API HTTP interna del motor de estrategias SHIOL+ v9.

Expone el motor de Python (estrategias, evaluación, pesos adaptativos) para
que el Worker de Cloudflare lo orqueste vía un Container binding
(ver docs/adr/0001-python-first-engine-docker-cloudflare-standby.md).

Diseño clave: este servicio no toca disco ni D1 -- el Worker manda todo lo
que el motor necesita (historial de draws, pesos actuales) en el body del
request, y recibe de vuelta el resultado, listo para que el Worker lo
escriba en D1 con su binding nativo. Esto reemplaza el flujo viejo de CLI +
JSON en disco (engine/pipeline/run.py) para el camino de producción; run.py
se mantiene para uso manual/backtest local.

Excepción a "sin red externa": /fetch-draw sí sale a internet (data.ny.gov,
NC Lottery) -- es la única lógica de negocio real que quedaba duplicada en
JS (worker.js) tras la migración de estrategias del ADR-0001. Se centralizó
acá por el mismo motivo que las estrategias: el parseo de 'winning_numbers'
tiene reglas específicas por juego (ver ny_extra_ball_field), y mantener
esa lógica en dos lenguajes ya causó un bug real al activar Mega Millions
(ver TODO.md, sesión 12-13). Regla del proyecto: ninguna lógica de
fetch/parseo de datos de lotería por-juego vive en worker.js -- vive acá,
o en CLI (engine/games/register.py) para operaciones manuales/masivas.

Convención de nombres: el wire format usa 'extra' para la bola extra
(Powerball/Mega Ball), igual que la columna `extra` de la tabla `draws` en
D1 — es la fuente de verdad real. Las estrategias y evaluate.py internamente
usan la clave 'pb' (heredado de Powerball); este módulo hace la conversión
en la frontera, para no tener que tocar 8 archivos de estrategias ni
propagar la ambigüedad pb/extra más allá de este archivo.

Pipeline de dos fases (sesión 18, ver TODO.md): la generación de tickets y
su evaluación contra el draw real ya NO ocurren siempre juntas. `worker.js`
llama a /generate-cycle para el próximo sorteo (todavía no ocurrió) y guarda
esos tickets sin evaluar en D1; días después, cuando el sorteo real aparece,
llama a /evaluate-cycle con esos mismos tickets (leídos de vuelta desde D1,
con su `id`) para completar la evaluación y los pesos. /run-cycle se
mantiene tal cual (genera + evalúa en un solo paso) como fallback de
"catch-up" para cuando no hay tickets pre-generados para un draw ya
ocurrido (Opción B). Las tres rutas comparten la misma lógica interna
(_generate_tickets_for_game / _evaluate_tickets_for_game) — no hay
duplicación.

Uso local (sin Docker):
    pip install -r requirements.txt
    uvicorn engine.server:app --reload --port 8000

Uso en Docker: ver engine/Dockerfile.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from engine.games import ALL_GAMES, get_game, get_lottery_config
from engine.strategies import get_compatible_strategies
from engine.pipeline.evaluate import evaluate_strategy
from engine.pipeline.weights import update_weights
from engine.pipeline.fetch_draw import fetch_draw
from engine.pipeline.fetch_jackpot import fetch_jackpot

app = FastAPI(
    title="SHIOL+ v9 Engine",
    description="Motor de estrategias (Python) orquestado por el Worker de Cloudflare.",
    version="1.0.0",
)


# ── Serialización de game configs ──────────────────────────────────────────

def _serialize_prize_table(prize_table: Dict) -> List[Dict]:
    """
    Convierte las claves tupla (matches_white, matches_extra) del prize_table
    a una lista de objetos JSON-safe (las tuplas no son válidas como keys JSON).
    """
    return [
        {
            "matches_white": white,
            "matches_extra": extra,
            "level": level,
            "amount": amount,
        }
        for (white, extra), (level, amount) in prize_table.items()
    ]


def _serialize_game(game: Dict) -> Dict:
    return {**game, "prize_table": _serialize_prize_table(game["prize_table"])}


# ── Endpoints de solo lectura ───────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "shiolplus-engine"}


@app.get("/games")
def list_games():
    """
    Config completa de todos los juegos registrados (activos e inactivos).
    Fuente única de verdad — el Worker sincroniza esto a la tabla `lotteries`
    de D1 en vez de mantener su propia copia de las reglas de cada juego.
    """
    return {game_id: _serialize_game(game) for game_id, game in ALL_GAMES.items()}


# ── /fetch-draw ───────────────────────────────────────────────────────────
#
# Reemplaza a fetchDrawFromNyData()/fetchDrawFromCSV() (JS) en worker.js --
# esa era la última pieza de lógica de negocio por-juego duplicada fuera
# del motor (ver ADR-0001 y nota al inicio del archivo).

class FetchDrawRequest(BaseModel):
    game_id: str
    draw_date: str


@app.post("/fetch-draw")
def fetch_draw_endpoint(req: FetchDrawRequest):
    """
    Intenta traer el resultado real de un sorteo desde las fuentes externas
    (ny_data_api -> nc_csv -> fallbacks guardados por juego, ver
    engine/pipeline/fetch_draw.py). 'found: false' es un resultado normal
    (el sorteo todavía no se publicó), no un error -- el Worker lo
    interpreta como 'reintentar en el próximo cron', igual que antes.
    """
    try:
        game = get_game(req.game_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    draw = fetch_draw(req.draw_date, game=game)
    if not draw:
        return {"found": False}

    return {
        "found": True,
        "draw": {
            "draw_date": draw["draw_date"],
            "n1": draw["n1"], "n2": draw["n2"], "n3": draw["n3"],
            "n4": draw["n4"], "n5": draw["n5"],
            "extra": draw["pb"],  # convención del wire format: 'extra', no 'pb'
            "source": draw.get("source"),
        },
    }


# ── /fetch-jackpot ───────────────────────────────────────────────────────────
#
# Trae el jackpot estimado del próximo sorteo desde nclottery.com (ver
# engine/pipeline/fetch_jackpot.py -- incluye validador de sanidad + reintentos).
# Sigue la misma regla que /fetch-draw: ningún fetch/parseo de datos externos
# de lotería vive en worker.js, vive acá.

class FetchJackpotRequest(BaseModel):
    game_id: str


@app.post("/fetch-jackpot")
def fetch_jackpot_endpoint(req: FetchJackpotRequest):
    """
    'found: false' es el resultado normal cuando el scrape falla el
    validador de sanidad (fuente caída, o cambió de estructura) -- no es un
    error fatal. El Worker mantiene el último valor bueno que ya tenía en
    D1 en ese caso, igual que /fetch-draw hace con 'sorteo no disponible
    todavía'.
    """
    if req.game_id not in ALL_GAMES:
        raise HTTPException(status_code=400, detail=f"game_id desconocido: {req.game_id!r}")

    result = fetch_jackpot(req.game_id)
    if not result:
        return {"found": False}

    return {
        "found": True,
        "amount": result["amount"],
        "cash_value": result["cash_value"],
        "source": result["source"],
    }


# ── Modelos compartidos ─────────────────────────────────────────────────────

class DrawIn(BaseModel):
    """Resultado real de un sorteo. 'extra' = Powerball/Mega Ball/etc."""
    draw_date: str
    n1: int
    n2: int
    n3: int
    n4: int
    n5: int
    extra: Optional[int] = None
    source: Optional[str] = None


class HistoricalDrawIn(BaseModel):
    """Un renglón de histórico, mismo shape que la tabla `draws` de D1."""
    draw_date: str
    n1: int
    n2: int
    n3: int
    n4: int
    n5: int
    extra: Optional[int] = None


class TicketIn(BaseModel):
    """
    Un ticket ya generado. Sin `id` cuando viene recién generado en el mismo
    request (fallback /run-cycle); con `id` cuando viene leído de vuelta
    desde D1 (fase 2, /evaluate-cycle) -- el Worker lo necesita para saber
    qué fila actualizar.
    """
    id: Optional[int] = None
    numbers: List[int]
    extra: Optional[int] = None
    confidence: Optional[float] = 0.5


def _draws_to_dataframe(draws: List[HistoricalDrawIn]) -> pd.DataFrame:
    """Arma el DataFrame [draw_date, n1..n5, pb] que esperan las estrategias."""
    if not draws:
        return pd.DataFrame(columns=["draw_date", "n1", "n2", "n3", "n4", "n5", "pb"])
    rows = [
        {
            "draw_date": d.draw_date,
            "n1": d.n1, "n2": d.n2, "n3": d.n3, "n4": d.n4, "n5": d.n5,
            "pb": d.extra,  # conversión extra (D1) -> pb (interno)
        }
        for d in draws
    ]
    df = pd.DataFrame(rows)
    df["draw_date"] = pd.to_datetime(df["draw_date"])
    return df


# ── Lógica interna compartida (generar / evaluar) ───────────────────────────
#
# Extraída de lo que antes era todo el cuerpo de /run-cycle, para que
# /generate-cycle, /evaluate-cycle y /run-cycle (fallback) reusen la misma
# implementación sin duplicar nada (sesión 18).

def _generate_tickets_for_game(strategies: Dict, lottery_cfg: Dict,
                                draws_df: pd.DataFrame,
                                tickets_per_strategy: int) -> Dict[str, List[Dict]]:
    """Genera tickets frescos para cada estrategia compatible -- sin evaluar."""
    generated = {}
    for name, StratClass in strategies.items():
        strategy = StratClass(lottery_cfg)
        generated[name] = strategy.generate(draws_df, count=tickets_per_strategy)
    return generated


def _evaluate_tickets_for_game(tickets_by_strategy: Dict[str, List[Dict]],
                                draw_dict: Dict, game: Dict,
                                current_weights: Dict[str, float],
                                total_cycles: Dict[str, int]) -> Dict[str, Dict]:
    """
    Evalúa tickets YA generados (frescos o leídos de D1) contra un draw real
    y calcula los pesos adaptativos nuevos.
    """
    eval_results = {
        name: evaluate_strategy(tickets, draw_dict, game=game)
        for name, tickets in tickets_by_strategy.items()
    }

    # total_cycles que llega es "antes de este ciclo"; se incrementa acá
    cycles_after = {name: total_cycles.get(name, 0) + 1 for name in tickets_by_strategy}
    weight_updates = update_weights(current_weights, eval_results, cycles_after)

    return {
        name: {
            "tickets_count": res["tickets_count"],
            "matches_3":     res["matches_3"],
            "matches_4":     res["matches_4"],
            "matches_5":     res["matches_5"],
            "total_prize":   res["total_prize"],
            "roi":           res["roi"],
            "weight_before": current_weights.get(name, 1.0),
            "weight_after":  weight_updates[name]["weight"],
            "status":        weight_updates[name]["status"],
            # Tickets individuales evaluados -- el Worker los persiste en D1
            # (tabla `tickets`) para trazabilidad real por ciclo. Si el
            # ticket de entrada traía `id` (viene de D1, fase 2), se
            # preserva en la salida para que el Worker sepa qué fila
            # actualizar en vez de insertar una nueva.
            "tickets": [
                {
                    **({"id": t["id"]} if t.get("id") is not None else {}),
                    "numbers":       t["numbers"],
                    "extra":         t["extra"],
                    "confidence":    t.get("confidence"),
                    "matches_white": t["matches_white"],
                    "matches_extra": t["matches_extra"],
                    "prize_level":   t["prize_level"],
                    "prize_amount":  t["prize_amount"],
                }
                for t in res["evaluated_tickets"]
            ],
        }
        for name, res in eval_results.items()
    }


# ── /generate-cycle ─────────────────────────────────────────────────────────
#
# Fase 1 del pipeline de dos fases: genera tickets para el PRÓXIMO sorteo
# (todavía no ocurrió), sin evaluar. No necesita el draw real ni pesos.

class GenerateCycleRequest(BaseModel):
    game_id: str
    draws_history: List[HistoricalDrawIn] = Field(default_factory=list)
    tickets_per_strategy: int = 20


@app.post("/generate-cycle")
def generate_cycle(req: GenerateCycleRequest):
    """
    Genera los tickets de las 8 estrategias compatibles de un juego para un
    sorteo que todavía no ocurrió. El Worker los guarda en D1 sin evaluar
    (`evaluated=0`) y los evalúa después, cuando el sorteo real aparezca,
    vía /evaluate-cycle.
    """
    try:
        game = get_game(req.game_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    lottery_cfg = get_lottery_config(req.game_id)
    strategies = get_compatible_strategies(game)
    if not strategies:
        raise HTTPException(
            status_code=400,
            detail=f"El juego '{req.game_id}' no tiene estrategias compatibles.",
        )

    draws_df = _draws_to_dataframe(req.draws_history)
    generated = _generate_tickets_for_game(strategies, lottery_cfg, draws_df, req.tickets_per_strategy)

    return {
        "game_id": req.game_id,
        "strategies": {
            name: [
                {"numbers": t["numbers"], "extra": t["extra"], "confidence": t.get("confidence")}
                for t in tickets
            ]
            for name, tickets in generated.items()
        },
    }


# ── /evaluate-cycle ─────────────────────────────────────────────────────────
#
# Fase 2 del pipeline de dos fases: evalúa tickets ya generados (leídos de
# vuelta desde D1, con su `id`) contra el draw real, y calcula pesos nuevos.

class EvaluateCycleRequest(BaseModel):
    game_id: str
    draw: DrawIn
    tickets_by_strategy: Dict[str, List[TicketIn]]
    current_weights: Dict[str, float] = Field(default_factory=dict)
    total_cycles: Dict[str, int] = Field(default_factory=dict)


@app.post("/evaluate-cycle")
def evaluate_cycle(req: EvaluateCycleRequest):
    """
    Evalúa tickets ya generados en un ciclo previo (fase 1) contra el
    resultado real del sorteo. No genera tickets nuevos.
    """
    try:
        game = get_game(req.game_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    tickets_by_strategy = {
        name: [t.model_dump(exclude_none=True) for t in tickets]
        for name, tickets in req.tickets_by_strategy.items()
    }

    draw_dict = req.draw.model_dump()
    draw_dict["pb"] = draw_dict.pop("extra")

    strategy_results = _evaluate_tickets_for_game(
        tickets_by_strategy, draw_dict, game, req.current_weights, req.total_cycles
    )

    return {
        "game_id":          req.game_id,
        "draw_date":        req.draw.draw_date,
        "draw":             req.draw.model_dump(),
        "strategy_results": strategy_results,
        "executed_at":      datetime.now(timezone.utc).isoformat(),
    }


# ── /run-cycle ────────────────────────────────────────────────────────────
#
# Fallback de "catch-up" (Opción B, ver TODO.md sesión 18): cuando no hay
# tickets pre-generados para un draw que ya ocurrió (primera corrida del
# pipeline de dos fases, o un ciclo que se saltó), genera Y evalúa en un
# solo paso -- mismo comportamiento que antes de la sesión 18.

class RunCycleRequest(BaseModel):
    game_id: str
    draw: DrawIn
    draws_history: List[HistoricalDrawIn] = Field(default_factory=list)
    current_weights: Dict[str, float] = Field(default_factory=dict)
    total_cycles: Dict[str, int] = Field(default_factory=dict)
    tickets_per_strategy: int = 20


@app.post("/run-cycle")
def run_cycle(req: RunCycleRequest):
    """
    Corre un ciclo completo y stateless para un draw ya resuelto:
      1. Genera tickets por cada estrategia compatible con el juego.
      2. Evalúa cada estrategia contra el draw real.
      3. Calcula los nuevos pesos adaptativos.
    No persiste nada — el Worker toma la respuesta y escribe a D1.
    """
    try:
        game = get_game(req.game_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    lottery_cfg = get_lottery_config(req.game_id)
    strategies = get_compatible_strategies(game)
    if not strategies:
        raise HTTPException(
            status_code=400,
            detail=f"El juego '{req.game_id}' no tiene estrategias compatibles.",
        )

    draws_df = _draws_to_dataframe(req.draws_history)
    generated = _generate_tickets_for_game(strategies, lottery_cfg, draws_df, req.tickets_per_strategy)
    total_tickets = sum(len(t) for t in generated.values())

    draw_dict = req.draw.model_dump()
    draw_dict["pb"] = draw_dict.pop("extra")

    strategy_results = _evaluate_tickets_for_game(
        generated, draw_dict, game, req.current_weights, req.total_cycles
    )

    return {
        "game_id":          req.game_id,
        "draw_date":        req.draw.draw_date,
        "draw":             req.draw.model_dump(),
        "total_tickets":    total_tickets,
        "strategy_results": strategy_results,
        "executed_at":      datetime.now(timezone.utc).isoformat(),
    }
