/**
 * SHIOL+ v9 — Worker (API + cron) + frontend estático (Workers Static Assets)
 *
 * El frontend (HTML/CSS/JS) vive en public/ y se sirve DIRECTO desde ahí vía
 * el binding `env.ASSETS` (ver `[assets]` en wrangler.toml) — Cloudflare lo
 * despliega junto con este Worker en un solo `wrangler deploy`, sin ningún
 * paso de build intermedio (ver ADR-0001, Fase 4; reemplaza al viejo
 * build.js + frontend.generated.js, que ya no existen).
 *
 * Deploy: npx wrangler deploy
 */

// ─────────────────────────────────────────────────────────────
// CONTAINER: motor de estrategias (Python) — ver docs/adr/0001-...
// Wrangler necesita que la clase Durable Object del container esté
// exportada desde el entrypoint del Worker (este archivo) para poder
// resolver el binding `[[durable_objects.bindings]] class_name =
// "EngineContainer"` de wrangler.toml.
//
// Fase 3 del ADR-0001: `runPipeline()` (el cron) llama a `runEngineCycle()`
// para generar tickets/evaluar/actualizar pesos — ya no queda ninguna
// lógica de estrategias corriendo en JS. El motor (`engine/`) es la única
// implementación de las 8 estrategias en todo el proyecto.
// ─────────────────────────────────────────────────────────────
export { EngineContainer } from './container.js';
import {
  runEngineCycle, generateEngineCycle, evaluateEngineCycle, fetchDrawFromEngine,
  fetchJackpotFromEngine,
} from './container.js';
import { handlePresentationAPI } from './presentation-api.js';
import { handlePlpAPI } from './plp-api.js';

// ─────────────────────────────────────────────────────────────
// PIPELINE ENGINE (JS — ejecuta en el cron)
// ─────────────────────────────────────────────────────────────
//
// El fetch/parseo del resultado real de un sorteo (ny_data_api, schema
// distinto por juego, fallbacks) YA NO vive acá. Vivía en dos
// implementaciones JS independientes (fetchDrawFromNyData/fetchDrawFromCSV)
// que un bug real (auditoría externa, 2026-07-05) demostró que se
// desincronizan de la versión Python en engine/pipeline/fetch_draw.py --
// el fix de Mega Millions se aplicó en Python y nunca se espejó acá, y el
// cron real (que usa esta copia JS) quedó roto en silencio. Regla del
// proyecto en adelante: ninguna lógica de fetch/parseo de datos de lotería
// por-juego vive en worker.js -- vive en engine/, expuesta acá vía el
// Container (fetchDrawFromEngine(), ver container.js) o vía CLI para
// operaciones manuales/masivas (engine/games/register.py). Ver TODO.md
// sesión 12-13 y docs/adr/0001-python-first-engine-docker-cloudflare-standby.md.

/**
 * Calcula la fecha del último draw de un juego dado la fecha actual.
 * draw_days: ['Monday','Wednesday','Saturday']
 */
function lastDrawDate(drawDays) {
  const DAY_MAP = {Sunday:0,Monday:1,Tuesday:2,Wednesday:3,Thursday:4,Friday:5,Saturday:6};
  const targets = new Set(drawDays.map(d => DAY_MAP[d]));
  const now = new Date();
  // Buscar hacia atrás hasta 7 días
  for (let i = 1; i <= 7; i++) {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() - i);
    if (targets.has(d.getUTCDay())) {
      return d.toISOString().slice(0, 10);
    }
  }
  return null;
}

/**
 * Calcula la fecha del PRÓXIMO draw de un juego (todavía no ocurrió) --
 * espejo de lastDrawDate() pero buscando hacia adelante. Usada por la fase
 * de generación del pipeline de dos fases (sesión 18): nunca devuelve hoy
 * (el sorteo de hoy, si hoy es día de sorteo, todavía no pasó al momento en
 * que corre el cron de la mañana -- ese caso lo cubre lastDrawDate() en la
 * corrida siguiente, no acá).
 */
function nextDrawDate(drawDays) {
  const DAY_MAP = {Sunday:0,Monday:1,Tuesday:2,Wednesday:3,Thursday:4,Friday:5,Saturday:6};
  const targets = new Set(drawDays.map(d => DAY_MAP[d]));
  const now = new Date();
  // Buscar hacia adelante hasta 7 días
  for (let i = 1; i <= 7; i++) {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() + i);
    if (targets.has(d.getUTCDay())) {
      return d.toISOString().slice(0, 10);
    }
  }
  return null;
}

// ── Estrategia: id en D1 vs. nombre en el motor Python ────────
// engine/games/register.py sufija el id en D1 con `_${gameId}` para
// cualquier juego que no sea powerball (necesario: `strategies.id` es
// PRIMARY KEY de una sola columna, dos juegos no pueden compartir el mismo
// id de estrategia). El motor Python, en cambio, siempre usa el nombre
// plano (claves de ALL_STRATEGIES, p. ej. 'frequency_weighted'), sin
// sufijo ni noción de juego. Este Worker es el único lugar que habla con
// ambos lados, así que traduce en las dos direcciones (Fase 5, ADR-0001).
function toEngineStrategyName(d1StrategyId, gameId) {
  const suffix = `_${gameId}`;
  return gameId !== 'powerball' && d1StrategyId.endsWith(suffix)
    ? d1StrategyId.slice(0, -suffix.length)
    : d1StrategyId;
}

function toD1StrategyId(engineStrategyName, gameId) {
  return gameId !== 'powerball' ? `${engineStrategyName}_${gameId}` : engineStrategyName;
}

// ── Pipeline principal (llamado desde scheduled) ─────────────
//
// Pipeline de dos fases (sesión 18, ver TODO.md): la generación de tickets
// para un sorteo y su evaluación contra el resultado real ya NO ocurren
// siempre juntas.
//   - evaluatePastCycle(): busca el último sorteo que ya debería haber
//     pasado. Si hay tickets pre-generados (`status='generated'`) para esa
//     fecha, los evalúa contra el resultado real. Si NO hay ninguno
//     (primera corrida de este flujo, o un ciclo que se saltó), hace
//     catch-up generando Y evaluando en el mismo paso (Opción B), igual que
//     el flujo viejo pre-sesión 18.
//   - generateNextCycle(): calcula el PRÓXIMO sorteo (todavía no ocurrió) y,
//     si no se generó ya, genera los 20 tickets x 8 estrategias por
//     adelantado y los guarda sin evaluar.
// Ambas sub-funciones son idempotentes -- el cron corre 2 veces por día en
// cada día de sorteo. Toda la lógica de estrategias/evaluación/pesos sigue
// viviendo únicamente en el motor Python (ver ADR-0001); este Worker solo
// orquesta: trae el draw real, lee/escribe D1, persiste lo que el Container
// devuelve.

async function loadStrategiesAndWeights(db, gameId) {
  const { results: strategies } = await db.prepare(
    `SELECT id, current_weight, total_cycles FROM strategies
     WHERE lottery_id=? AND status != 'archived'`
  ).bind(gameId).all();

  // Traducir id de D1 (sufijado para no-powerball) -> nombre plano del
  // motor, para que el motor encuentre el peso real en vez de caer al
  // default (Fase 5, ADR-0001).
  const currentWeights = {};
  const totalCycles    = {};
  for (const s of strategies) {
    const engineName = toEngineStrategyName(s.id, gameId);
    currentWeights[engineName] = s.current_weight;
    totalCycles[engineName]    = s.total_cycles;
  }
  return { strategies, currentWeights, totalCycles };
}

/**
 * Escribe el resultado de UNA estrategia para un ciclo ya evaluado:
 * strategy_stats, el peso nuevo en `strategies`, y los tickets individuales.
 *
 * Si los tickets de `r.tickets` traen `id` (vienen de D1 -- fase 2,
 * pre-generados en un cron anterior) se ACTUALIZAN in-place. Si no traen
 * `id` (se generaron y evaluaron en el mismo paso -- catch-up/Opción B) se
 * insertan frescos, borrando primero cualquier resto de un intento previo
 * (la generación no es determinística, un reintento daría un set distinto).
 */
async function persistStrategyResult(db, { cycleId, gameId, drawDate, strategyId, r }) {
  await db.prepare(
    `INSERT OR REPLACE INTO strategy_stats
       (cycle_id,lottery_id,draw_date,strategy_id,tickets_count,
        matches_3,matches_4,matches_5,total_prize,roi,weight_before,weight_after)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`
  ).bind(
    cycleId, gameId, drawDate,
    strategyId, r.tickets_count,
    r.matches_3, r.matches_4, r.matches_5,
    r.total_prize, r.roi, r.weight_before, r.weight_after
  ).run();

  await db.prepare(
    `UPDATE strategies SET current_weight=?, status=?, total_cycles=total_cycles+1
     WHERE id=? AND lottery_id=?`
  ).bind(r.weight_after, r.status, strategyId, gameId).run();

  if (!r.tickets?.length) return;

  const preGenerated = r.tickets.every(t => t.id != null);
  let ticketsWithIds;

  if (preGenerated) {
    const updateStmts = r.tickets.map(t => db.prepare(
      `UPDATE tickets SET matches_white=?, matches_extra=?, prize_level=?, prize_amount=?, evaluated=1
       WHERE id=?`
    ).bind(t.matches_white, t.matches_extra, t.prize_level, t.prize_amount, t.id));
    await db.batch(updateStmts);
    ticketsWithIds = r.tickets;
  } else {
    await db.prepare(`DELETE FROM tickets WHERE cycle_id=? AND strategy_id=?`)
      .bind(cycleId, strategyId).run();

    const insertStmts = r.tickets.map(t => db.prepare(
      `INSERT INTO tickets
         (cycle_id,strategy_id,lottery_id,draw_date,n1,n2,n3,n4,n5,extra,
          confidence,matches_white,matches_extra,prize_level,prize_amount,evaluated)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)`
    ).bind(
      cycleId, strategyId, gameId, drawDate,
      t.numbers[0], t.numbers[1], t.numbers[2], t.numbers[3], t.numbers[4], t.extra,
      t.confidence ?? 0.5, t.matches_white, t.matches_extra, t.prize_level, t.prize_amount
    ));
    await db.batch(insertStmts);

    // Recién insertados -- D1 no devuelve el `id` autogenerado por
    // statement dentro de un batch, así que se re-leen y se matchean por
    // combinación de números para poder linkear los wins al ticket real
    // (necesario para el índice único de idempotencia, ver insertWinsForTickets()).
    // Se guarda una COLA de ids por combinación de números (no un solo id) porque
    // el motor no garantiza que los 20 tickets de una estrategia sean únicos entre
    // sí -- si dos tickets del mismo lote comparten números exactos, cada aparición
    // consume un id distinto de la cola en vez de que ambos apunten al mismo id
    // (eso hacía que uno de los dos ganadores reales nunca se registrara en `wins`,
    // ver TODO.md).
    const { results: freshRows } = await db.prepare(
      `SELECT id,n1,n2,n3,n4,n5,extra FROM tickets WHERE cycle_id=? AND strategy_id=?`
    ).bind(cycleId, strategyId).all();
    const idsByNumbers = new Map();
    for (const row of freshRows) {
      const key = `${row.n1},${row.n2},${row.n3},${row.n4},${row.n5},${row.extra}`;
      if (!idsByNumbers.has(key)) idsByNumbers.set(key, []);
      idsByNumbers.get(key).push(row.id);
    }
    ticketsWithIds = r.tickets.map(t => {
      const key = `${t.numbers[0]},${t.numbers[1]},${t.numbers[2]},${t.numbers[3]},${t.numbers[4]},${t.extra}`;
      return { ...t, id: idsByNumbers.get(key)?.shift() };
    });
  }

  // No bloqueante -- mismo patrón que refreshJackpot(). Un fallo acá (error
  // transitorio de D1, etc.) nunca debe impedir que generateNextCycle() corra
  // después en runPipeline(); registrar el hit en el Hall of Wins es
  // secundario frente a generar los tickets del próximo ciclo.
  try {
    await insertWinsForTickets(db, { gameId, drawDate, strategyId, tickets: ticketsWithIds });
  } catch (e) {
    console.error(`[wins] ${gameId} ${strategyId}: error insertando wins`, e);
  }
}

/**
 * Hall of Wins automático (sesión 21): cualquier ticket evaluado con
 * prize_amount > 0 se registra solo en `wins` -- ya no hace falta
 * insertarlo a mano. Sin filtro de monto mínimo a propósito (Orlando pidió
 * ver TODOS los tickets ganadores, hasta el premio más chico -- $2-$4 según
 * el juego, ver prize_table en engine/games/*.py).
 *
 * `INSERT OR IGNORE` + el índice único parcial sobre `wins.ticket_id` (ver
 * schema/d1_schema.sql) hacen esto idempotente: si algún día un ciclo se
 * re-evalúa, no se duplican filas. `verified=1` de entrada -- a diferencia
 * del flujo manual viejo, el dato ya sale de un draw real fetcheado de la
 * fuente oficial (mismo que actualiza los pesos), no hace falta un paso de
 * verificación humana aparte.
 */
async function insertWinsForTickets(db, { gameId, drawDate, strategyId, tickets }) {
  const winners = tickets.filter(t => t.prize_amount > 0 && t.id != null);
  if (!winners.length) return;

  const stmts = winners.map(t => db.prepare(
    `INSERT OR IGNORE INTO wins
       (strategy_id,lottery_id,draw_date,numbers,extra,prize_level,prize_amount,verified,ticket_id)
     VALUES (?,?,?,?,?,?,?,1,?)`
  ).bind(
    strategyId, gameId, drawDate,
    JSON.stringify(t.numbers), t.extra,
    t.prize_level, t.prize_amount, t.id
  ));
  await db.batch(stmts);
}

/**
 * Fase "evaluar": busca el último sorteo que ya debería haber pasado, y si
 * el resultado real ya está publicado, evalúa contra él los tickets
 * pre-generados (o hace catch-up si no hay ninguno -- Opción B).
 */
async function evaluatePastCycle(game, env, ticketsPerStrategy, overrideDate = null) {
  const db       = env.DB;
  const gameId   = game.id;
  const drawDate = overrideDate ?? lastDrawDate(game.draw_days);
  if (!drawDate) return { skipped: true, reason: 'no_draw_date' };

  const already = await db.prepare(
    `SELECT id FROM cycles WHERE lottery_id=? AND draw_date=? AND status='evaluated'`
  ).bind(gameId, drawDate).first();
  if (already) return { skipped: true, reason: 'already_evaluated', draw_date: drawDate };

  // Poll: intentar traer el sorteo real. 'found: false' es normal (todavía
  // no se publicó) -- no es un error, se reintenta en el próximo cron.
  let draw = null;
  try {
    const result = await fetchDrawFromEngine(env, { game_id: gameId, draw_date: drawDate });
    if (result.found) draw = { ...result.draw, pb: result.draw.extra };
  } catch (e) {
    console.error('[fetch-draw]', e);
  }
  // Fallback: si la fuente externa no tiene el draw pero ya está en D1
  // (ciclos varados cuyo dato llegó tarde o la fuente ya no lo expone),
  // usarlo directamente para no bloquear la evaluación indefinidamente.
  if (!draw) {
    const cached = await db.prepare(
      `SELECT draw_date,n1,n2,n3,n4,n5,extra,source FROM draws WHERE lottery_id=? AND draw_date=?`
    ).bind(gameId, drawDate).first();
    if (cached) {
      draw = { ...cached, pb: cached.extra };
      console.log(`[pipeline] ${gameId} ${drawDate}: usando draw cacheado en D1 (fuente externa no disponible)`);
    }
  }
  if (!draw) return { skipped: true, reason: 'draw_not_available', draw_date: drawDate };

  await db.prepare(
    `INSERT OR IGNORE INTO draws (lottery_id,draw_date,n1,n2,n3,n4,n5,extra,source)
     VALUES (?,?,?,?,?,?,?,?,?)`
  ).bind(gameId, drawDate, draw.n1, draw.n2, draw.n3, draw.n4, draw.n5, draw.pb, draw.source).run();

  const { strategies, currentWeights, totalCycles } = await loadStrategiesAndWeights(db, gameId);
  if (!strategies.length) {
    console.warn(`[pipeline] ${gameId}: no hay estrategias activas, nada que evaluar`);
    return { skipped: true, reason: 'no_active_strategies', draw_date: drawDate };
  }

  const drawPayload = {
    draw_date: draw.draw_date,
    n1: draw.n1, n2: draw.n2, n3: draw.n3, n4: draw.n4, n5: draw.n5,
    extra: draw.pb,
    source: draw.source,
  };

  const cycle = await db.prepare(
    `SELECT id, status FROM cycles WHERE lottery_id=? AND draw_date=?`
  ).bind(gameId, drawDate).first();

  let cycleId, engineResult;

  if (cycle && cycle.status === 'generated') {
    // Fase 2: ya hay tickets pre-generados para este sorteo -- evaluarlos.
    cycleId = cycle.id;
    const ticketsByStrategy = {};
    for (const s of strategies) {
      const engineName = toEngineStrategyName(s.id, gameId);
      const { results: rows } = await db.prepare(
        `SELECT id,n1,n2,n3,n4,n5,extra,confidence FROM tickets WHERE cycle_id=? AND strategy_id=?`
      ).bind(cycleId, s.id).all();
      ticketsByStrategy[engineName] = rows.map(t => ({
        id: t.id, numbers: [t.n1, t.n2, t.n3, t.n4, t.n5], extra: t.extra, confidence: t.confidence,
      }));
    }

    engineResult = await evaluateEngineCycle(env, {
      game_id: gameId,
      draw: drawPayload,
      tickets_by_strategy: ticketsByStrategy,
      current_weights: currentWeights,
      total_cycles: totalCycles,
    });
  } else {
    // Opción B -- catch-up: no hay tickets pre-generados (primera corrida
    // de este flujo, o un ciclo que se saltó). Generar Y evaluar en un solo
    // paso, igual que el flujo pre-sesión 18.
    console.warn(`[pipeline] ${gameId} ${drawDate}: sin tickets pre-generados, catch-up vía /run-cycle`);

    await db.prepare(
      `INSERT OR IGNORE INTO cycles (lottery_id,draw_date,tickets_total,status)
       VALUES (?,?,?,?)`
    ).bind(gameId, drawDate, strategies.length * ticketsPerStrategy, 'pending').run();

    const cycleRow = await db.prepare(
      `SELECT id FROM cycles WHERE lottery_id=? AND draw_date=?`
    ).bind(gameId, drawDate).first();
    cycleId = cycleRow.id;

    const { results: history } = await db.prepare(
      `SELECT draw_date,n1,n2,n3,n4,n5,extra FROM draws
       WHERE lottery_id=? AND draw_date < ? ORDER BY draw_date DESC LIMIT 500`
    ).bind(gameId, drawDate).all();

    engineResult = await runEngineCycle(env, {
      game_id: gameId,
      draw: drawPayload,
      draws_history: history.map(d => ({
        draw_date: d.draw_date,
        n1: d.n1, n2: d.n2, n3: d.n3, n4: d.n4, n5: d.n5,
        extra: d.extra,
      })),
      current_weights: currentWeights,
      total_cycles: totalCycles,
      tickets_per_strategy: ticketsPerStrategy,
    });
  }

  for (const [engineName, r] of Object.entries(engineResult.strategy_results)) {
    const strategyId = toD1StrategyId(engineName, gameId);
    await persistStrategyResult(db, { cycleId, gameId, drawDate, strategyId, r });
  }

  const totalTickets = Object.values(engineResult.strategy_results)
    .reduce((sum, r) => sum + r.tickets_count, 0);
  await db.prepare(
    `UPDATE cycles SET status='evaluated', tickets_total=? WHERE id=?`
  ).bind(totalTickets, cycleId).run();

  const nStrategies = Object.keys(engineResult.strategy_results).length;
  console.log(`[pipeline] ${gameId} ${drawDate} ✅ ${nStrategies} strategies evaluated`);
  return { success: true, game_id: gameId, draw_date: drawDate, strategies_evaluated: nStrategies };
}

/**
 * Fase "generar": calcula el próximo sorteo (todavía no ocurrió) y, si no
 * se generó ya, arma los 20 tickets x 8 estrategias por adelantado y los
 * guarda sin evaluar (`evaluated=0`) -- quedan esperando a evaluatePastCycle()
 * en un cron futuro, cuando el sorteo real ya haya pasado.
 */
async function generateNextCycle(game, env, ticketsPerStrategy) {
  const db       = env.DB;
  const gameId   = game.id;
  const nextDate = nextDrawDate(game.draw_days);
  if (!nextDate) return { skipped: true, reason: 'no_next_draw_date' };

  // Idempotencia: el cron corre 2 veces por día en cada día de sorteo -- no
  // regenerar si este sorteo futuro ya tiene tickets.
  const existing = await db.prepare(
    `SELECT id FROM cycles WHERE lottery_id=? AND draw_date=? AND status IN ('generated','evaluated')`
  ).bind(gameId, nextDate).first();
  if (existing) return { skipped: true, reason: 'already_generated', draw_date: nextDate };

  const { strategies } = await loadStrategiesAndWeights(db, gameId);
  if (!strategies.length) {
    console.warn(`[pipeline] ${gameId}: no hay estrategias activas, nada que generar`);
    return { skipped: true, reason: 'no_active_strategies', draw_date: nextDate };
  }

  const { results: history } = await db.prepare(
    `SELECT draw_date,n1,n2,n3,n4,n5,extra FROM draws
     WHERE lottery_id=? AND draw_date < ? ORDER BY draw_date DESC LIMIT 500`
  ).bind(gameId, nextDate).all();

  const engineResult = await generateEngineCycle(env, {
    game_id: gameId,
    draws_history: history.map(d => ({
      draw_date: d.draw_date,
      n1: d.n1, n2: d.n2, n3: d.n3, n4: d.n4, n5: d.n5,
      extra: d.extra,
    })),
    tickets_per_strategy: ticketsPerStrategy,
  });

  await db.prepare(
    `INSERT OR IGNORE INTO cycles (lottery_id,draw_date,tickets_total,status)
     VALUES (?,?,?,?)`
  ).bind(gameId, nextDate, strategies.length * ticketsPerStrategy, 'pending').run();

  const cycleRow = await db.prepare(
    `SELECT id FROM cycles WHERE lottery_id=? AND draw_date=?`
  ).bind(gameId, nextDate).first();
  const cycleId = cycleRow.id;

  for (const s of strategies) {
    const engineName = toEngineStrategyName(s.id, gameId);
    const tickets = engineResult.strategies[engineName] || [];
    if (!tickets.length) continue;

    // Idempotencia defensiva -- por si un intento anterior parcial dejó algo.
    await db.prepare(`DELETE FROM tickets WHERE cycle_id=? AND strategy_id=?`)
      .bind(cycleId, s.id).run();

    const insertStmts = tickets.map(t => db.prepare(
      `INSERT INTO tickets
         (cycle_id,strategy_id,lottery_id,draw_date,n1,n2,n3,n4,n5,extra,confidence,evaluated)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,0)`
    ).bind(
      cycleId, s.id, gameId, nextDate,
      t.numbers[0], t.numbers[1], t.numbers[2], t.numbers[3], t.numbers[4], t.extra,
      t.confidence ?? 0.5
    ));
    await db.batch(insertStmts);
  }

  await db.prepare(`UPDATE cycles SET status='generated' WHERE id=?`).bind(cycleId).run();

  console.log(`[pipeline] ${gameId} ${nextDate} ✅ tickets generados para ${strategies.length} estrategias`);
  return { success: true, game_id: gameId, draw_date: nextDate, strategies_generated: strategies.length };
}

/**
 * Refresca el jackpot estimado del próximo sorteo (nclottery.com, vía el
 * motor -- ver engine/pipeline/fetch_jackpot.py). No bloqueante a propósito:
 * un fallo acá nunca debe tirar abajo el resto del pipeline (generar/evaluar
 * tickets es lo que de verdad importa; el jackpot es solo un dato de
 * display). Si el scrape falla el validador de sanidad, se mantiene el
 * último valor bueno en D1 y solo se actualiza `last_status`/
 * `last_attempt_at`, para poder detectar scraping roto sin perder el dato
 * mostrado al usuario mientras tanto.
 */
async function refreshJackpot(game, env) {
  const db     = env.DB;
  const gameId = game.id;
  const now    = new Date().toISOString();

  let result;
  try {
    result = await fetchJackpotFromEngine(env, { game_id: gameId });
  } catch (e) {
    console.error(`[jackpot] ${gameId}: fetch falló`, e);
    result = { found: false };
  }

  if (result.found) {
    await db.prepare(
      `INSERT INTO jackpots (lottery_id, amount, cash_value, source, last_status, last_success_at, last_attempt_at)
       VALUES (?,?,?,?,'ok',?,?)
       ON CONFLICT(lottery_id) DO UPDATE SET
         amount=excluded.amount, cash_value=excluded.cash_value, source=excluded.source,
         last_status='ok', last_success_at=excluded.last_success_at, last_attempt_at=excluded.last_attempt_at`
    ).bind(gameId, result.amount, result.cash_value, result.source, now, now).run();
    console.log(`[jackpot] ${gameId}: actualizado $${result.amount}`);
    return { success: true, amount: result.amount };
  }

  // Fallo (scrape no pasó el validador de sanidad, o excepción de red):
  // mantener el último valor bueno, solo marcar que este intento no sirvió.
  await db.prepare(
    `INSERT INTO jackpots (lottery_id, last_status, last_attempt_at)
     VALUES (?, 'stale_parser_broken', ?)
     ON CONFLICT(lottery_id) DO UPDATE SET
       last_status='stale_parser_broken', last_attempt_at=excluded.last_attempt_at`
  ).bind(gameId, now).run();
  console.warn(`[jackpot] ${gameId}: fetch no disponible este ciclo, se mantiene el último valor bueno`);
  return { skipped: true, reason: 'fetch_failed' };
}

/**
 * Si un ciclo pasado quedó con status='generated' (el draw no estaba
 * disponible en ninguna de las dos ventanas diarias del cron), este cron
 * lo recupera en la siguiente corrida -- sin esperar intervención manual.
 * Solo intenta el ciclo más antiguo pendiente por juego para no alargar
 * el tiempo de ejecución del cron.
 */
async function recoverOldestStrandedCycle(game, env, ticketsPerStrategy, primaryDate) {
  const db     = env.DB;
  const today  = new Date().toISOString().slice(0, 10);
  const stranded = await db.prepare(
    `SELECT draw_date FROM cycles
     WHERE lottery_id=? AND status='generated' AND draw_date < ? AND draw_date != ?
     ORDER BY draw_date ASC LIMIT 1`
  ).bind(game.id, today, primaryDate ?? '').first();

  if (!stranded) return { skipped: true, reason: 'no_stranded_cycles' };
  console.log(`[pipeline] ${game.id}: recovering stranded cycle for ${stranded.draw_date}`);
  return evaluatePastCycle(game, env, ticketsPerStrategy, stranded.draw_date);
}

async function runPipeline(game, env, ticketsPerStrategy = 20) {
  const primaryDate = lastDrawDate(game.draw_days);
  const evaluate = await evaluatePastCycle(game, env, ticketsPerStrategy);
  const recover  = await recoverOldestStrandedCycle(game, env, ticketsPerStrategy, primaryDate);
  const generate = await generateNextCycle(game, env, ticketsPerStrategy);

  // No bloqueante -- ver refreshJackpot(). Un fallo acá no debe afectar el
  // resultado real del pipeline (generar/evaluar tickets).
  let jackpot;
  try {
    jackpot = await refreshJackpot(game, env);
  } catch (e) {
    console.error(`[jackpot] ${game.id}: error inesperado`, e);
    jackpot = { error: e.message };
  }

  return { evaluate, recover, generate, jackpot };
}

// ─────────────────────────────────────────────────────────────
// GAME CONFIGS (mirror de engine/games/ — data-driven desde D1)
// ─────────────────────────────────────────────────────────────

// Solo lo mínimo que este Worker sigue necesitando: qué juegos existen y
// sus días de sorteo (para el cron / lastDrawDate()). Todo lo demás
// (rangos de bolas, fuente de datos, schema de fetch) vive únicamente en
// engine/games/*.py -- ya no se mantiene una segunda copia acá (ver nota
// al inicio del archivo sobre la duplicación de fetch que causó un bug real).
const GAME_CONFIGS = {
  powerball: {
    id: 'powerball',
    draw_days: ['Monday', 'Wednesday', 'Saturday'],
  },
  mega_millions: {
    id: 'mega_millions',
    draw_days: ['Tuesday', 'Friday'],
  },
  cash5: {
    id: 'cash5',
    draw_days: ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'],
  },
};

// ─────────────────────────────────────────────────────────────
// HTTP API
// ─────────────────────────────────────────────────────────────

const JSON_H = {
  'Content-Type': 'application/json',
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: JSON_H });
}

async function handleAPI(path, url, request, env) {
  const lotteryId = url.searchParams.get('game') || 'powerball';

  const plpResponse = await handlePlpAPI(path, url, request, env);
  if (plpResponse) return plpResponse;

  const presentationResponse = await handlePresentationAPI(path, url, env);
  if (presentationResponse) return presentationResponse;

  if (path === '/api/health') {
    return json({ status: 'ok', ts: new Date().toISOString(), version: 'v9' });
  }

  if (path === '/api/strategies') {
    const { results } = await env.DB.prepare(`
      SELECT s.id, s.name, s.description, s.status,
             s.current_weight, s.total_cycles,
             COALESCE(agg.total_prize,0) AS lifetime_prize,
             COALESCE(agg.avg_roi,0)     AS avg_roi
      FROM strategies s
      LEFT JOIN (
        SELECT strategy_id, SUM(total_prize) AS total_prize, AVG(roi) AS avg_roi
        FROM strategy_stats GROUP BY strategy_id
      ) agg ON s.id = agg.strategy_id
      WHERE s.lottery_id = ?
      ORDER BY s.current_weight DESC
    `).bind(lotteryId).all();
    return json(results);
  }

  if (path === '/api/latest-cycle') {
    const cycle = await env.DB.prepare(`
      SELECT c.*, d.n1, d.n2, d.n3, d.n4, d.n5, d.extra AS pb
      FROM cycles c
      LEFT JOIN draws d ON d.lottery_id=c.lottery_id AND d.draw_date=c.draw_date
      WHERE c.status='evaluated' AND c.lottery_id=?
      ORDER BY c.draw_date DESC LIMIT 1
    `).bind(lotteryId).first();
    if (!cycle) return json({ message: 'No cycles yet' }, 404);
    const { results: stats } = await env.DB.prepare(`
      SELECT strategy_id, tickets_count, matches_3, matches_4, matches_5,
             total_prize, roi, weight_before, weight_after
      FROM strategy_stats WHERE cycle_id=? ORDER BY roi DESC
    `).bind(cycle.id).all();
    return json({ cycle, strategy_results: stats });
  }

  if (path === '/api/history') {
    const strategy = url.searchParams.get('strategy');
    const limit    = Math.min(parseInt(url.searchParams.get('limit') || '30'), 100);
    let q = `SELECT draw_date,strategy_id,roi,total_prize,matches_3,matches_4,matches_5,
                    weight_before,weight_after
             FROM strategy_stats WHERE lottery_id=?`;
    const b = [lotteryId];
    if (strategy) { q += ' AND strategy_id=?'; b.push(strategy); }
    q += ' ORDER BY draw_date DESC LIMIT ?'; b.push(limit);
    const { results } = await env.DB.prepare(q).bind(...b).all();
    return json(results);
  }

  if (path === '/api/wins') {
    // Filtra por juego -- sin esto, con más de un juego activo, el Hall of
    // Wins mezclaría wins de Powerball y Mega Millions sin distinguirlos
    // (la columna `lottery_id` ya existe en el schema, solo faltaba usarla
    // acá). `game` es opcional: sin él, devuelve todos los juegos (uso
    // interno/histórico); el frontend siempre lo manda.
    //
    // Sesión 21: ahora que `wins` se llena automático para CUALQUIER premio
    // (no solo los grandes, ver insertWinsForTickets()), la tabla puede
    // crecer bastante -- el total mostrado ya NO puede ser la suma de lo
    // que se ve en pantalla (antes tenía un LIMIT 50 client-side-summed, que
    // mentía apenas hubiera más de 50 filas). Ahora el total sale de un
    // SUM()/COUNT() real contra toda la tabla; la lista sigue capada
    // (default 50, hasta 200) para no mandar miles de filas de una, pero
    // ordenada por prize_amount DESC así los premios grandes siempre quedan
    // arriba sin importar cuántos hits chicos ($2-$4) haya debajo.
    const gameFilter = url.searchParams.get('game');
    const limit = Math.min(parseInt(url.searchParams.get('limit') || '50'), 200);
    const where = gameFilter ? 'WHERE lottery_id = ?' : '';
    const binds = gameFilter ? [gameFilter] : [];

    const totals = await env.DB.prepare(
      `SELECT COUNT(*) AS total_count, COALESCE(SUM(prize_amount),0) AS total_amount
       FROM wins ${where}`
    ).bind(...binds).first();

    const { results } = await env.DB.prepare(
      `SELECT * FROM wins ${where} ORDER BY prize_amount DESC LIMIT ?`
    ).bind(...binds, limit).all();

    return json({
      total_amount: totals.total_amount,
      total_count: totals.total_count,
      wins: results,
    });
  }

  if (path === '/api/ticket-performance') {
    // Sesión 21 -- "Strategy Scoreboard": win rate real y $ ganado por
    // estrategia, calculado directo sobre `tickets` (ya trae matches/prize
    // por ticket individual desde la sesión 17, no hace falta trackear nada
    // nuevo). Solo tickets ya evaluados (`evaluated=1`) -- los del próximo
    // sorteo (pendientes, ver /api/upcoming-tickets) todavía no tienen
    // resultado real, incluirlos falsearía el win rate.
    const { results } = await env.DB.prepare(`
      SELECT strategy_id,
             COUNT(*) AS total_tickets,
             SUM(CASE WHEN prize_amount > 0 THEN 1 ELSE 0 END) AS winning_tickets,
             COALESCE(SUM(prize_amount), 0) AS total_won,
             ROUND(100.0 * SUM(CASE WHEN prize_amount > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS win_rate
      FROM tickets
      WHERE lottery_id = ? AND evaluated = 1
      GROUP BY strategy_id
      ORDER BY total_won DESC
    `).bind(lotteryId).all();
    return json(results);
  }

  if (path === '/api/upcoming-tickets') {
    // Sesión 21 -- los 20 tickets ya generados (sin evaluar todavía) de UNA
    // estrategia para el próximo sorteo, ordenados por `confidence` de mayor
    // a menor (único criterio real de "mejor a peor" disponible antes de que
    // el sorteo ocurra -- todavía no hay matches/prize reales que ordenar).
    const strategyId = url.searchParams.get('strategy');
    if (!strategyId) return json({ error: 'falta ?strategy=' }, 400);

    const nextCycle = await env.DB.prepare(
      `SELECT id, draw_date FROM cycles WHERE lottery_id=? AND status='generated'
       ORDER BY draw_date ASC LIMIT 1`
    ).bind(lotteryId).first();
    if (!nextCycle) return json({ found: false });

    const { results } = await env.DB.prepare(
      `SELECT id,n1,n2,n3,n4,n5,extra,confidence FROM tickets
       WHERE cycle_id=? AND strategy_id=? ORDER BY confidence DESC`
    ).bind(nextCycle.id, strategyId).all();

    return json({ found: true, draw_date: nextCycle.draw_date, tickets: results });
  }

  if (path === '/api/draws') {
    const limit = Math.min(parseInt(url.searchParams.get('limit') || '10'), 50);
    const { results } = await env.DB.prepare(`
      SELECT draw_date,n1,n2,n3,n4,n5,extra AS pb FROM draws
      WHERE lottery_id=? ORDER BY draw_date DESC LIMIT ?
    `).bind(lotteryId, limit).all();
    return json(results);
  }

  if (path === '/api/jackpot') {
    const row = await env.DB.prepare(
      `SELECT amount, cash_value, source, last_status, last_success_at FROM jackpots WHERE lottery_id=?`
    ).bind(lotteryId).first();
    if (!row || row.amount == null) return json({ found: false });

    // stale: no se pudo refrescar en los últimos 5 días -- suficiente
    // margen para cubrir un cron salteado sin marcar como viejo algo que
    // en realidad está al día (los sorteos ocurren 2-3 veces por semana).
    const STALE_AFTER_MS = 5 * 24 * 60 * 60 * 1000;
    const staleByTime = row.last_success_at
      ? (Date.now() - new Date(row.last_success_at).getTime()) > STALE_AFTER_MS
      : true;
    const stale = row.last_status !== 'ok' || staleByTime;

    return json({
      found: true,
      amount: row.amount,
      cash_value: row.cash_value,
      source: row.source,
      stale,
    });
  }

  if (path === '/api/games') {
    const { results } = await env.DB.prepare(
      `SELECT id, name, draw_days, white_ball_count, white_ball_max,
              extra_ball_name, extra_ball_max, active FROM lotteries`
    ).all();
    return json(results);
  }

  // Backfill histórico: ya no existe como endpoint HTTP -- estaba roto
  // (usaba nc_csv_url, 404 desde 2026-07-04) y era una tercera copia de
  // la lógica de parseo de fetch_draw.py. El backfill masivo es una
  // operación manual/rara: vive solo en el CLI, ya corregido y usando
  // ny_data_api (ver engine/games/register.py::cmd_backfill).

  return json({ error: 'Not found' }, 404);
}

// ─────────────────────────────────────────────────────────────
// ENTRYPOINTS
// ─────────────────────────────────────────────────────────────

export default {
  // ── HTTP requests ───────────────────────────────────────────
  async fetch(request, env) {
    const url  = new URL(request.url);
    const path = url.pathname;

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: JSON_H });
    }
    if (path.startsWith('/api/')) {
      try { return await handleAPI(path, url, request, env); }
      catch (err) { console.error('[api]', err); return json({ error: err.message }, 500); }
    }
    // Todo lo que no es /api/* es frontend estático: index.html (Home),
    // game.html (detalle por juego), styles.css, home.js/game.js, y
    // cualquier otro archivo que se agregue a public/ — Cloudflare ya sirve
    // estos assets directo (antes de llegar acá) para la mayoría de los
    // requests; este fallback cubre los casos donde el Worker corre primero
    // (p. ej. rutas con querystring) y también da el 404 real de Cloudflare
    // para archivos que no existen en public/.
    return env.ASSETS.fetch(request);
  },

  // ── Cron trigger (scheduled handler) ───────────────────────
  async scheduled(event, env, ctx) {
    console.log(`[cron] fired: ${event.cron} at ${new Date().toISOString()}`);

    // Leer juegos activos desde D1 (source of truth)
    const { results: activeGames } = await env.DB.prepare(
      `SELECT id, draw_days FROM lotteries WHERE active = 1`
    ).all();

    const results = [];
    for (const g of activeGames) {
      const gameConfig = GAME_CONFIGS[g.id];
      if (!gameConfig) {
        console.warn(`[cron] No GAME_CONFIGS entry for '${g.id}', skipping`);
        continue;
      }
      // draw_days en D1 es 'mon,wed,sat' → convertir a nombres completos
      const dayFull = { mon:'Monday', tue:'Tuesday', wed:'Wednesday',
                        thu:'Thursday', fri:'Friday', sat:'Saturday', sun:'Sunday' };
      gameConfig.draw_days = g.draw_days.split(',').map(d => dayFull[d] || d);

      try {
        const result = await runPipeline(gameConfig, env);
        results.push({ game: g.id, ...result });
      } catch (err) {
        console.error(`[cron] pipeline error for ${g.id}:`, err);
        results.push({ game: g.id, error: err.message });
      }
    }

    console.log('[cron] done:', JSON.stringify(results));
  },
};
