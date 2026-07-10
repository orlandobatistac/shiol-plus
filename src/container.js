/**
 * src/container.js — Clase Container + helpers para orquestar el motor
 * Python (engine/) desde el Worker.
 *
 * Ver docs/adr/0001-python-first-engine-docker-cloudflare-standby.md.
 *
 * Fase 3 (ADR-0001): `runPipeline()` (el cron) usa `runEngineCycle()` —
 * ya no queda ninguna lógica de estrategias corriendo en JS en producción.
 */
import { Container, getContainer } from '@cloudflare/containers';

export class EngineContainer extends Container {
  // Coincide con `uvicorn engine.server:app --port 8000` en engine/Dockerfile.
  defaultPort = 8000;

  // El motor solo se necesita unas pocas veces por semana (cron de sorteos).
  // Apagarlo rápido entre usos ahorra el costo de CPU activo del Container
  // (se cobra por uso, no por estar "encendido" — pero solo si lo apagamos).
  sleepAfter = '2m';
}

// Instancia única (singleton) — este proyecto no necesita una instancia de
// Container por sesión/usuario, solo un motor de cómputo compartido.
const INSTANCE_NAME = 'engine';

/**
 * Config completa de todos los juegos, tal como los define engine/games/
 * (fuente única de verdad — ver ADR-0001). Útil para sincronizar la tabla
 * `lotteries` de D1 sin duplicar las reglas de cada juego en JS.
 */
export async function getEngineGames(env) {
  const container = getContainer(env.ENGINE, INSTANCE_NAME);
  const resp = await container.fetch(new Request('http://engine/games'));
  if (!resp.ok) {
    throw new Error(`engine /games respondió ${resp.status}: ${await resp.text()}`);
  }
  return resp.json();
}

/**
 * Corre un ciclo completo (generar tickets, evaluar contra el draw real,
 * calcular pesos nuevos) para un draw ya resuelto. No persiste nada — el
 * caller (Worker) es responsable de escribir el resultado a D1.
 *
 * `payload` debe tener el shape que espera
 * engine/server.py::RunCycleRequest:
 *   {
 *     game_id: string,
 *     draw: { draw_date, n1..n5, extra, source? },
 *     draws_history: [{ draw_date, n1..n5, extra }, ...],
 *     current_weights: { [strategy_id]: number },
 *     total_cycles: { [strategy_id]: number },
 *     tickets_per_strategy?: number,
 *   }
 */
export async function runEngineCycle(env, payload) {
  const container = getContainer(env.ENGINE, INSTANCE_NAME);
  const resp = await container.fetch(
    new Request('http://engine/run-cycle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  );
  if (!resp.ok) {
    throw new Error(`engine /run-cycle respondió ${resp.status}: ${await resp.text()}`);
  }
  return resp.json();
}

/**
 * Fase 1 del pipeline de dos fases (sesión 18): genera tickets para las 8
 * estrategias de un juego, para un sorteo que TODAVÍA NO ocurrió. No evalúa,
 * no necesita pesos ni el draw real.
 *
 * `payload` debe tener el shape de engine/server.py::GenerateCycleRequest:
 *   { game_id, draws_history: [...], tickets_per_strategy? }
 *
 * Devuelve { game_id, strategies: { [engineName]: [{numbers,extra,confidence}] } }.
 */
export async function generateEngineCycle(env, payload) {
  const container = getContainer(env.ENGINE, INSTANCE_NAME);
  const resp = await container.fetch(
    new Request('http://engine/generate-cycle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  );
  if (!resp.ok) {
    throw new Error(`engine /generate-cycle respondió ${resp.status}: ${await resp.text()}`);
  }
  return resp.json();
}

/**
 * Fase 2 del pipeline de dos fases (sesión 18): evalúa tickets ya generados
 * en un ciclo previo (leídos de vuelta desde D1, con su `id`) contra el
 * draw real, y calcula los pesos nuevos.
 *
 * `payload` debe tener el shape de engine/server.py::EvaluateCycleRequest:
 *   {
 *     game_id, draw: {...},
 *     tickets_by_strategy: { [engineName]: [{id,numbers,extra,confidence}] },
 *     current_weights, total_cycles,
 *   }
 */
export async function evaluateEngineCycle(env, payload) {
  const container = getContainer(env.ENGINE, INSTANCE_NAME);
  const resp = await container.fetch(
    new Request('http://engine/evaluate-cycle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  );
  if (!resp.ok) {
    throw new Error(`engine /evaluate-cycle respondió ${resp.status}: ${await resp.text()}`);
  }
  return resp.json();
}

/**
 * Intenta traer el resultado real de un sorteo desde las fuentes externas
 * (ny_data_api -> nc_csv -> fallbacks por juego). Reemplaza a las viejas
 * `fetchDrawFromNyData()`/`fetchDrawFromCSV()` que vivían en worker.js —
 * esa duplicación causó un bug real al activar Mega Millions (el fix se
 * aplicó en Python pero no en la copia JS). Ver TODO.md sesión 12-13 y el
 * comentario al inicio de engine/server.py.
 *
 * `payload`: { game_id: string, draw_date: string } (YYYY-MM-DD).
 *
 * Devuelve `{ found: false }` si el sorteo todavía no se publicó (caso
 * normal, no es un error) o `{ found: true, draw: { draw_date, n1..n5,
 * extra, source } }`.
 */
export async function fetchDrawFromEngine(env, payload) {
  const container = getContainer(env.ENGINE, INSTANCE_NAME);
  const resp = await container.fetch(
    new Request('http://engine/fetch-draw', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  );
  if (!resp.ok) {
    throw new Error(`engine /fetch-draw respondió ${resp.status}: ${await resp.text()}`);
  }
  return resp.json();
}

/**
 * Trae el jackpot estimado del próximo sorteo de un juego (nclottery.com,
 * ver engine/pipeline/fetch_jackpot.py -- incluye validador de sanidad).
 *
 * `payload`: { game_id: string }.
 *
 * Devuelve `{ found: false }` si el scrape falló el validador de sanidad
 * (caso normal, no es un error fatal -- el caller mantiene el último valor
 * bueno que ya tenía en D1) o `{ found: true, amount, cash_value, source }`.
 */
export async function fetchJackpotFromEngine(env, payload) {
  const container = getContainer(env.ENGINE, INSTANCE_NAME);
  const resp = await container.fetch(
    new Request('http://engine/fetch-jackpot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  );
  if (!resp.ok) {
    throw new Error(`engine /fetch-jackpot respondió ${resp.status}: ${await resp.text()}`);
  }
  return resp.json();
}
