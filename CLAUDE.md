# SHIOL+ v9 — Guía para agentes AI

Documento canónico para sesiones de trabajo asistidas. Lee esto completo antes de
modificar cualquier archivo. Las secciones marcadas ⚠️ documentan incidentes reales.

## Arquitectura en una línea

**Worker JS** (cron + API pública) → **Container Python** (estrategias + evaluación)
← **D1** (única base de datos, producción y local)

Regla central: ninguna lógica de negocio por-juego vive en `worker.js`. Vive
en `engine/`. Si ves lógica de fetch/parseo/estrategia en `worker.js`, es un bug
por duplicación — ver ADR-0001.

---

## Archivos clave

| Archivo | Qué hace |
|---------|----------|
| `src/worker.js` | Cron + API HTTP. Orquesta; no calcula. |
| `src/container.js` | Binding al Container Python. Helpers: `runEngineCycle`, `generateEngineCycle`, `evaluateEngineCycle`, `fetchDrawFromEngine`. |
| `engine/server.py` | FastAPI interno del Container. Endpoints: `/run-cycle`, `/generate-cycle`, `/evaluate-cycle`, `/fetch-draw`, `/fetch-jackpot`, `/games`. |
| `engine/games/*.py` | Config por juego: prize_table, draw_days, fuentes de datos, `has_extra_ball`. |
| `engine/pipeline/evaluate.py` | Evalúa tickets contra draw real. Game-agnostic vía prize_table. |
| `engine/pipeline/fetch_draw.py` | Fuentes en orden: ny_data_api → nc_csv → powerball.com → musl_api. Las dos últimas son solo para Powerball. |
| `engine/strategies/` | 8 estrategias Python. Única implementación — no duplicar en JS. |
| `schema/d1_schema.sql` | Esquema completo de D1. |
| `schema/000N_*.sql` | Migraciones incrementales. Ver "Deploy checklist" abajo. |
| `wrangler.toml` | Worker + D1 + Container + cron triggers. |

---

## Juegos activos

| ID | Nombre | Días de sorteo | Hora sorteo ET | Fuente primaria |
|----|--------|----------------|----------------|-----------------|
| `powerball` | Powerball | Mon/Wed/Sat | ~23:00 | ny_data_api (Socrata) |
| `mega_millions` | Mega Millions | Tue/Fri | ~23:00 | ny_data_api (Socrata) |
| `cash5` | NC Cash 5 | Todos los días | 23:22 | nc_csv (nclottery.com/cash5-download) |

### ⚠️ Timing de fuentes de datos

**Mega Millions / Powerball (Socrata — data.ny.gov)**
El dataset de NY Open Data puede tardar **más de 6 horas** en reflejar un sorteo.
Un sorteo a las 23:00 ET = 04:00 UTC del día siguiente. Los crons de 05:00 y 09:00
UTC son demasiado tempranos para MM de forma consistente.
- Cron especial añadido: `0 17 * * 3` (miércoles) para el sorteo del martes y
  `0 17 * * 6` (sábado) para el del viernes — 13h después del sorteo, Socrata
  definitivamente tiene el dato.
- Si ves un ciclo de MM en D1 con `status='generated'` y `draw_date` en el pasado,
  es lag de Socrata — no es un bug de código.

**Cash 5 (NC CSV)**
El CSV de NC Lottery se actualiza normalmente dentro de las 6-8h del sorteo.
El cron de 09:00 UTC (5-6h después) puede ser marginal en algunos días.
El cron de 17:00 también sirve como backup para Cash5 los miércoles y sábados.

**Dataset IDs de Socrata por juego** (en `engine/games/*.py`):
- Powerball: `d6yy-54nr`
- Mega Millions: `5xaw-6ayf`, usa campo separado `mega_ball` para la bola extra
  (distinto del formato de Powerball donde los 6 números van juntos en `winning_numbers`)
- Cash5: **no tiene dataset en Socrata** — solo NC CSV

---

## Cron schedule

```
0 5 * * *     Diario primario — todos los juegos
0 9 * * *     Diario backup   — todos los juegos
0 17 * * 3    Miércoles 17:00 UTC — retry específico para MM (sorteo Tue)
0 17 * * 6    Sábado 17:00 UTC    — retry específico para MM (sorteo Fri)
```

El handler del cron (`scheduled` en `worker.js`) lee los juegos activos desde D1
(`lotteries.active=1`) y corre `runPipeline` para cada uno. Es idempotente — si
un ciclo ya está evaluado lo salta sin error.

### ⚠️ Ciclos varados (stranded cycles)

Si un ciclo queda con `status='generated'` y su `draw_date` ya pasó (el draw
ocurrió pero la fuente no estaba disponible en ninguna ventana), `evaluatePastCycle`
no lo reintenta porque siempre apunta a `lastDrawDate` (ayer).

**Fix implementado** (2026-07-22): `recoverOldestStrandedCycle` en `worker.js` busca
en cada cron el ciclo 'generated' más antiguo cuya `draw_date < hoy` y lo evalúa
automáticamente. Máximo 1 ciclo stranded por juego por cron run para no alargar
tiempos de ejecución.

Para detectar ciclos varados en D1:
```sql
SELECT lottery_id, draw_date, status
FROM cycles WHERE status='generated' AND draw_date < date('now')
ORDER BY draw_date ASC;
```

---

## Convención de IDs de estrategia

Las estrategias en D1 (`strategies.id`) llevan sufijo `_<game_id>` para cualquier
juego que no sea Powerball, porque `id` es PRIMARY KEY de una sola columna:

| En D1 | En Python (engine/strategies/) |
|-------|-------------------------------|
| `frequency_weighted` | `frequency_weighted` (powerball) |
| `frequency_weighted_mega_millions` | `frequency_weighted` |
| `frequency_weighted_cash5` | `frequency_weighted` |
| `wheeling` | `wheeling` (powerball) |
| `wheeling_mega_millions` | `wheeling` |
| `wheeling_cash5` | `wheeling` |

`worker.js` hace la traducción en `toEngineStrategyName` y `toD1StrategyId`.
El motor Python siempre usa el nombre plano sin sufijo.

---

## ⚠️ Juegos sin bola extra (`has_extra_ball: False`)

Cash5 no tiene Powerball/Mega Ball. Esto afecta varios puntos del pipeline:

**`engine/pipeline/evaluate.py`**: usa `ticket.get('extra')` (no `ticket['extra']`)
porque `model_dump(exclude_none=True)` en `server.py` elimina la clave `extra` del
dict cuando su valor es `None`. Acceder `ticket['extra']` con `[]` en ese caso lanza
`KeyError → HTTP 500 del Container`. El código actual usa `.get()` correctamente.

**`engine/server.py`**: `DrawIn.extra` y `TicketIn.extra` son `Optional[int] = None`.
El campo `extra` en el wire format (JSON Worker↔Container) siempre usa la clave
`extra` (no `pb`); la conversión `extra→pb` ocurre dentro de `server.py` justo antes
de llamar a `evaluate_strategy`.

**`engine/pipeline/fetch_draw.py`**: `_from_nc_csv` devuelve `pb: None` cuando
`has_extra_ball=False`. `_from_ny_data` hace lo mismo.

**Prize table de Cash5**: claves `(matches_white, 0)` — el segundo elemento siempre
es 0 porque no hay bola extra. Ejemplo: `(5, 0): ('jackpot', 0)`.

---

## Servidor local de desarrollo

El proyecto usa **wrangler dev --remote**, que conecta al Worker en Cloudflare pero
sirve los assets localmente en el puerto 8788. El Container Python no corre en local
(solo en remoto), por lo que las rutas que lo invocan (`/api/run`, etc.) usan la
instancia de producción.

### Levantar el servidor

La configuración está en `.claude/launch.json` (entrada `shiol-plus-dev`).

**Desde Claude Code** (recomendado para agentes AI): usa la herramienta
`preview_start` con `name: "shiol-plus-dev"`. El agente puede luego usar
`preview_logs` con el `serverId` retornado para verificar que el servidor esté listo
(busca la línea `Ready on http://127.0.0.1:8788`).

**Desde terminal**:
```bash
npx wrangler dev --remote --port 8788 --test-scheduled
```

El flag `--test-scheduled` habilita el endpoint `/__scheduled` para disparar crons
manualmente durante el desarrollo.

### Verificar que está corriendo

```bash
curl http://localhost:8788/api/health
```

Respuesta esperada: `{ "status": "ok", ... }`

### Notas importantes

- `--remote` es obligatorio: el Container Python solo corre en Cloudflare, no en local.
  Sin `--remote`, las llamadas al Container fallan.
- Si el puerto 8788 ya está en uso, otro proceso wrangler está activo. Verificar con
  `netstat -ano | findstr 8788` (Windows) o `lsof -i :8788` (Unix).
- Los assets en `public/` se sirven localmente; cambios en esos archivos se reflejan
  sin reiniciar. Cambios en `src/worker.js` requieren reinicio del servidor.

---

## Deploy checklist

### Al modificar código existente:
```bash
npx wrangler deploy
```
El Container se reconstruye solo si cambió algo en `engine/` o `requirements.txt`.
Si el resultado dice "Image already exists remotely, skipping push", el Container
no cambió — normal y correcto.

### Al añadir un juego nuevo:

1. Crear `engine/games/<game_id>.py` con el GAME dict completo.
2. Registrar en `engine/games/__init__.py` (ALL_GAMES).
3. Crear `schema/000N_<game_id>.sql` con:
   - `INSERT OR IGNORE INTO lotteries (...)` con `active=0` inicialmente.
   - `INSERT OR IGNORE INTO strategies (...)` para las 8 estrategias base.
   - `INSERT OR IGNORE INTO strategies (...)` para `wheeling_<game_id>` si Fase 9
     ya está deployada (ver `schema/0003_wheeling.sql` como referencia).
4. Ejecutar la migración en D1 remoto **antes** del deploy del Worker:
   ```bash
   npx wrangler d1 execute shiol-plus-db --remote --file schema/000N_<game_id>.sql
   ```
5. Hacer backfill de histórico via CLI (no via Worker endpoint — ese fue eliminado):
   ```bash
   python -m engine.games.register backfill <game_id>
   ```
   Sincronizar el CSV resultante a D1:
   ```bash
   # Ver register.py::cmd_backfill para el comando exacto de sync a D1
   ```
6. Activar el juego en D1:
   ```bash
   npx wrangler d1 execute shiol-plus-db --remote \
     --command "UPDATE lotteries SET active=1 WHERE id='<game_id>'"
   ```
7. Añadir la config mínima a `GAME_CONFIGS` en `worker.js` (solo `id` y `draw_days`).
8. Si el juego tiene lag de Socrata > 6h, añadir cron específico en `wrangler.toml`.
9. Deploy:
   ```bash
   npx wrangler deploy
   ```

### ⚠️ El seed de estrategias en `schema/` es obligatorio ANTES del deploy

Si el Worker se deploya antes de ejecutar el SQL de estrategias, el primer cron
encuentra `strategies` vacío para el juego nuevo, `loadStrategiesAndWeights` devuelve
array vacío, y el pipeline devuelve `{ skipped: true, reason: 'no_active_strategies' }`.
La draw sí se inserta en D1 (ocurre antes del check), pero no hay evaluación. El
ciclo queda huérfano en `status='generated'` o el draw en `draws` sin cycle asociado.

---

## Verificar estado en producción

```bash
# Estado de ciclos (buscar stranded o anomalías)
npx wrangler d1 execute shiol-plus-db --remote \
  --command "SELECT lottery_id, draw_date, status, tickets_total FROM cycles ORDER BY draw_date DESC LIMIT 20"

# Estrategias activas por juego
npx wrangler d1 execute shiol-plus-db --remote \
  --command "SELECT id, lottery_id, status, current_weight, total_cycles FROM strategies ORDER BY lottery_id, id"

# Último draw evaluado por juego
npx wrangler d1 execute shiol-plus-db --remote \
  --command "SELECT lottery_id, MAX(draw_date) as last_eval FROM cycles WHERE status='evaluated' GROUP BY lottery_id"

# Health del Worker
curl https://shiol-plus.orlandob.workers.dev/api/health
```

---

## Referencia rápida

- **ADR principal**: `docs/adr/0001-python-first-engine-docker-cloudflare-standby.md`
- **TODO / registro de sesiones**: `TODO.md`
- **Esquema D1 completo**: `schema/d1_schema.sql`
- **URL producción**: https://shiol-plus.orlandob.workers.dev
- **D1 database ID**: `ad168e4c-e90c-4642-8b29-6c8d0bfc6157`
- **Container Application ID**: `a03cfd96-a494-4a00-a00e-86a5832e9678`
