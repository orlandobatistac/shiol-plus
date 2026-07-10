# TODO — SHIOL+ v9

Contexto persistente del proyecto. Actualizar esta lista al cerrar cada sesion de trabajo
para que una conversacion nueva pueda retomar sin perder contexto.

Ultima actualizacion: 2026-07-09 (sesion 26 -- deploy Cloudflare del rediseño minimalista)

## Estado actual

- Worker `shiol-plus` deployado en Cloudflare Workers con el Container Python +
  el pipeline de dos fases (generar/evaluar por separado, sesión 18), sin "Top
  Pick" (reemplazado por "Current Jackpot" real, sesión 17 mock -> sesión 20
  conectado a nclottery.com), con `wins` automático + Next Draw Tickets (sesión
  21), el fix de colisión de números en `wins` (sesión 22), y el rediseño UX del
  dashboard con podio + tooltips + detalle técnico colapsable (sesión 23, ver
  "Hecho" abajo). Versión activa en producción:
  `362a9b54-2c37-49c0-8d01-c2ebb086c960` (2026-07-09, sesión 26).
  URL: https://shiol-plus.orlandob.workers.dev
- Container `shiol-plus-enginecontainer` (Application ID `a03cfd96-a494-4a00-a00e-86a5832e9678`)
  en estado `ready` en producción. Imagen ~1.1GB (reducida de 1.83GB en sesión 10).
- D1 `shiol-plus-db`: `draws` tiene 2352 sorteos de Powerball (2006-05-31 -> 2026-07-06) y
  906 de Mega Millions (2017-10-31 -> 2026-07-03, activado en producción en sesión 16).
  Ambos juegos activos (`lotteries.active=1`), 16 estrategias sembradas (8 por juego).
  Tabla nueva `jackpots` (sesión 20, ver abajo) ya migrada en D1 real.
- Cron triggers activos: TUE/THU/SUN a las 05:00 y 09:00 UTC (6 triggers). **Confirmado
  en sesión 20 (2026-07-07), vía query directa a D1 de producción: el pipeline de dos
  fases YA corrió de punta a punta con un cron real** -- Powerball en flujo normal
  (cycle 2026-07-06 evaluado, cycle 2026-07-08 generado por adelantado, `total_cycles=4`),
  Mega Millions hizo el catch-up (Opción B) contra el sorteo 2026-07-03 (primera
  evaluación real desde la activación) y ya generó el siguiente ciclo (2026-07-10).
  El pendiente de la sesión 19 ("no se puede confirmar hasta que pase") queda cerrado.

## Hecho (2026-07-09, sesiones 25-26 - rediseno minimalista y deploy Cloudflare)

- [x] **Direccion visual aprobada e implementada**: reemplazo del dashboard oscuro
      con multiples tarjetas, colores e iconos por una interfaz editorial minimalista
      en fondo calido claro, texto de alto contraste, un solo azul de acento y color
      reservado para la bola extra y valores positivos. Sin gradientes, glassmorphism,
      iconografia decorativa ni apariencia generica de dashboard AI.
- [x] **Portada reconstruida** (`public/index.html`, `public/home.js`): nueva
      introduccion del producto, reportes por juego con jackpot, estrategia lider,
      total ganado y cantidad de premios, mas una explicacion compacta del metodo.
      Corregido el bug de `Total Won`: `/api/wins` devuelve un objeto
      `{total_amount,total_count,wins}`, no un arreglo.
- [x] **Dashboard reconstruido** (`public/game.html`, `public/game.js`):
      selector Powerball/Mega Millions, encabezado de reporte, banda resumen con
      jackpot/proximo sorteo/ultimo resultado, ranking principal con win rate,
      tickets evaluados y total ganado, lista compacta de tickets, premios recientes
      en lenguaje claro y laboratorio tecnico colapsable.
- [x] **Responsive y accesibilidad** (`public/styles.css`): navegacion inferior
      movil, layout sin overflow horizontal a 390 px, tipografia legible, estados de
      foco visibles, soporte `prefers-reduced-motion`, modal con `role=dialog`,
      `aria-modal`, bloqueo del fondo, Escape, foco inicial y restauracion del foco.
- [x] **QA local con datos reales de produccion**: portada cargo ambos juegos con
      jackpots y totales correctos; Powerball cargo 8 rankings, 8 estrategias de
      tickets y 4 wins. Modal XGBoost mostro los 20 tickets. Verificado desktop y
      viewport movil 390x844, sin desbordamiento horizontal. `node --check` limpio
      en `home.js` y `game.js`; IDs de HTML/JS y llaves CSS balanceados.
- [x] **Deploy directo a Cloudflare completado**: `wrangler deploy` publico los
      cinco assets del frontend y actualizo el Container sin fusionar el PR #40,
      tocar `main` ni ejecutar el workflow del VPS. Version activa:
      `362a9b54-2c37-49c0-8d01-c2ebb086c960`. Verificacion publica: portada,
      estilos, scripts, `/api/health`, jackpots, estrategias, rendimiento y wins
      de Powerball/Mega Millions respondieron 200; ambos juegos devolvieron sus
      8 estrategias. `.env` fue restaurado con el mismo tamano y fecha.

## Hecho (2026-07-09, sesion 24 - respaldo GitHub v8/v9 y plan de migracion)

- [x] **Repositorio GitHub conectado**: esta carpeta `C:\Dev\apps\shiol-plus-v9`
      quedo vinculada al repositorio publico
      `https://github.com/orlandobatistac/shiol-plus`, conservando todo el historial
      de la aplicacion monolitica anterior.
- [x] **Rama v9 publicada**: `agent/publish-v9`, commit
      `988ec9a2e0405f00bd6561105cc9d7af7a6f20cb`. Contiene la sustitucion completa
      de la arquitectura v7/v8 (FastAPI + VPS) por la arquitectura v9 vigente
      (Worker + Static Assets + D1 + Container Python). La sintaxis de los cuatro
      archivos JavaScript principales y de todo `engine/` fue verificada antes del
      push; `.env`, `node_modules`, `.wrangler`, bytecode y artefactos temporales
      de backfill quedaron fuera.
- [x] **PR de migracion creado como borrador**: PR #40,
      `https://github.com/orlandobatistac/shiol-plus/pull/40`, desde
      `agent/publish-v9` hacia `main`. **NO fusionar todavia.**
- [x] **Rama de respaldo v8 creada**: `agent/publish-v8`, apuntando al ultimo commit
      operativo de v8 (`3052f75d942926244194a569b8891fe7658cc6a2`). Esta rama
      conserva explicitamente la version del VPS aunque `main` cambie en el futuro.
- [x] **Riesgo de deploy antiguo confirmado**: el `main` actual contiene
      `.github/workflows/deploy-light.yml`, que corre en cada push a `main`, entra
      por SSH al VPS, hace `git pull origin main`, instala `requirements-prod.txt`
      y reinicia `shiolplus.service`. Tambien existe `deploy-restart.yml`, pero es
      solo manual (`workflow_dispatch`). El push de `agent/publish-v9` y la creacion
      de `agent/publish-v8` no dispararon ningun workflow ni tocaron el VPS.
- [ ] **Orden obligatorio antes de fusionar PR #40**:
      1. Migrar `shiolplus.com`/DNS desde el VPS hacia Cloudflare.
      2. Verificar produccion v9 en el dominio final (frontend, APIs, Container,
         D1, crons y ambos juegos).
      3. Desactivar manualmente `Deploy to Server (Light)` en GitHub Actions para
         impedir que un push a `main` vuelva a desplegar al VPS.
      4. Fusionar el PR #40.
      5. Confirmar que `main` representa v9 y que el VPS antiguo ya no recibe
         despliegues. Mantener `agent/publish-v8` como respaldo sin modificar.

## Hecho (2026-07-09, sesión 23 — rediseño UX del dashboard: podio, tooltips, detalle colapsable)

- [x] **Pedido de Orlando** ("no se entiende nada"): `game.html` tenía 7 secciones
      al mismo nivel con jerga sin explicar (`weight` a 4 decimales, `ROI`,
      `confidence`, `status`) y 3 tablas distintas (Strategy Rankings, Scoreboard,
      Last Cycle) respondiendo la misma pregunta de "¿quién va ganando?" con
      métricas diferentes. Cambio acotado a `public/` — cero cambios de API/backend,
      confirmado en la auditoría.
      - Nueva sección `#rankings` con podio top-3 en lenguaje simple ("wins a prize
        on X% of tickets played" + $ ganado), reemplaza el Scoreboard separado de
        sesión 21 — mismo endpoint `/api/ticket-performance`, sin datos nuevos.
      - La tabla completa de 8 estrategias (weight/ROI/sparklines) y "Last Cycle"
        ahora viven colapsadas dentro de `<details>` ("see all 8 strategies" /
        "last cycle — technical breakdown"), no desaparecen, solo dejan de ser lo
        primero que se ve.
      - Tooltips `?` (`.info-icon`/`.info-popover`) explicando en una frase simple
        qué es weight, ROI y confidence, sin sacar el dato técnico.
      - Nav del header simplificado de 5 a 3 links (Rankings / Next Tickets / Hall
        of Wins).
      - Archivos tocados: `public/game.html`, `public/game.js` (nueva
        `renderRankingPodium()` + `initInfoTooltips()`, se borró `renderScoreboard()`),
        `public/styles.css` (nuevas clases `.podium-*`, `.info-*`, estilos de
        `<details>`, se borraron las clases `.scoreboard-*` viejas).
- [x] **Auditoría independiente antes de deployar** (no confiar en el resumen del
      implementador de Cowork): leídos de punta a punta los 3 archivos. `node
      --check` limpio en `game.js`; grep cruzado confirmó que cada `getElementById`
      referenciado en `game.js` tiene su id correspondiente en `game.html` (cero
      huérfanos); cero referencias colgantes a `renderScoreboard`/`.scoreboard-*`
      fuera de comentarios/TODO.md histórico; `<details>` balanceados (2 apertura,
      2 cierre); llaves de `styles.css` balanceadas (137/137). Sin hallazgos.
- [x] **Deploy real a producción** (Windows nativo): Docker Desktop ya estaba
      corriendo. Mismo patrón de siempre para `.env`: oculto, un solo `wrangler
      deploy` de punta a punta sin comandos concurrentes tocándolo, restaurado al
      terminar — confirmado con `ls -la` (mismo tamaño/mtime). Imagen del Container
      100% cacheada (sin cambios en `engine/`, consistente con que esto fue
      puramente frontend) — solo se subieron los 3 assets estáticos modificados.
      **Versión deployada: `4cf746f6-7489-4642-a303-b2fa578624b8`.**
- [x] **Verificación visual real en producción** (Chrome vía MCP, no local):
      ambos juegos (`?game=powerball`, `?game=mega_millions`) cargan sin errores de
      consola. Podio top-3 renderiza con datos reales. `<details>` de "8
      strategies" y "Last cycle" expanden/colapsan correctamente. Tooltip de
      "weight" probado (abre el popover con el texto explicativo, cierra al hacer
      click fuera). Modal de "20 tickets" abre correctamente con el tooltip de
      "confidence" visible. Hall of Wins sigue mostrando los 4 registros reales
      poblados desde sesión 22 (`$16` / 4 wins) — sin regresión.
- [x] **Limpieza de Docker post-deploy**: borrada la imagen de producción anterior
      (`...:f21aca55`, superseded por `a4c4c116`, que ya estaba deployada desde
      sesión 22) y el tag local redundante (`shiol-plus-enginecontainer:a4c4c116`).
      Build cache vaciado (`docker builder prune -f`).

## Hecho (2026-07-09, sesión 22 — fix edge case de colisión de números en `wins`)

- [x] **Fix del hallazgo secundario documentado en sesión 21**: en la rama
      catch-up de `persistStrategyResult()` (`src/worker.js`), si dos tickets de
      la misma estrategia/ciclo compartían números exactos por azar, el
      emparejamiento por clave numérica (`idByNumbers`, un `Map<combinación,
      id>`) hacía que ambos tickets quedaran apuntando al mismo `id` real de la
      tabla `tickets`, y uno de los dos ganadores nunca se registraba en `wins`
      (el índice único parcial descartaba la segunda inserción vía `OR IGNORE`).
      Corregido: `idsByNumbers` ahora es `Map<combinación, id[]>` (una cola por
      combinación), y cada ticket consume un id distinto con `.shift()` -- como
      dos tickets con los mismos números tienen forzosamente el mismo resultado
      de premio, no importa cuál id de la cola le toque a cada uno, lo único que
      importa es que cada fila física reciba su propio id en vez de que dos
      tickets compartan uno. Confirmado leyendo el código real (no el resumen):
      el diff coincide exactamente con lo descrito, `node --check` limpio en
      `src/worker.js` tras el cambio.
- [x] **Deploy real a producción** (Windows nativo): Docker Desktop ya estaba
      corriendo. Mismo patrón de siempre para `.env` (token con scope `D1:Edit`
      no alcanza para deploy): oculto, un solo `wrangler deploy` de punta a
      punta sin comandos concurrentes tocándolo, restaurado al terminar --
      confirmado con `ls -la` (mismo tamaño/mtime que el original). Build de la
      imagen del Container limpio (~93s de `pip install`), push al registry de
      Cloudflare exitoso, aplicación de Container actualizada. **Versión
      deployada: `a4c4c116-533f-42ca-a055-6750ce537fb4`.**
- [x] **Verificación post-deploy contra producción real**: `/api/health` (200),
      `/` (200). **`/api/wins?game=powerball` ya muestra datos reales poblados
      por el cron real del 2026-07-08** (`total_count:4`, `total_amount:16`,
      4 filas con `ticket_id` real cada una) -- confirma en producción, no solo
      en teoría, que el flujo completo de sesión 21 (try/catch no bloqueante +
      auto-inserción en `wins`) ya está funcionando de punta a punta.
      `/api/upcoming-tickets?game=powerball&strategy=intelligent_scoring`
      devuelve `found:true` con el próximo ciclo real (`draw_date:2026-07-11`).
- [ ] **Pendiente, no verificable hasta que ocurra**: el propio edge case de
      colisión de números es de probabilidad ínfima (~1 en cientos de millones
      por par de tickets) -- no hay forma de confirmar el fix contra un caso
      real en producción a corto plazo, solo queda validado por lectura de
      código + `node --check`.

## Hecho (2026-07-07, sesión 20)

- [x] **Pendiente #4 (encoding cp1252) cerrado sin cambios de código**: revisado todo
      `TODO.md` buscando cp1252/mojibake/UnicodeEncodeError -- solo existe el incidente
      ya documentado (Docker+WSL2, D1 local vs Windows), ya resuelto con regla
      permanente. No había ningún otro bug de encoding suelto.
- [x] **Pendiente #5 (limpieza) cerrado**: borradas `frontend/public/`, `frontend/src/`
      y `frontend/` (confirmadas vacías, cero referencias en el repo).
- [x] **Verificación real del cron de dos fases (pendiente de sesión 19)** -- ver
      "Estado actual" arriba. Confirmado con queries directas a D1 de producción real
      (no solo revisión de código): ambos juegos corrieron el cron de hoy correctamente,
      incluido el catch-up de Mega Millions.
- [x] **Feature nueva: "Current Jackpot" real** (reemplaza el mock de sesión 17, a
      pedido de Orlando). Investigación primero: `powerball.com` y `megamillions.com`
      no tienen API JSON pública confiable -- `powerball.com` responde con contenido
      binario/incompleto de forma intermitente (~1 de cada 4 intentos, problema de su
      CDN/Azure Front Door) y `megamillions.com` depende de un servicio ASMX interno
      no pensado para consumo externo. A pedido de Orlando se usó en cambio
      **nclottery.com** (NC Education Lottery, revendedor oficial de ambos juegos) --
      confirmado 100% consistente en pruebas repetidas, un solo parser para los dos
      juegos.
      - `engine/pipeline/fetch_jackpot.py` (nuevo): scraper con reintentos (3x) +
        **validador de sanidad** (rango $20M-$5B, y verifica que se encontraron los 2
        campos esperados) -- cualquier fallo se loguea con prefijo `[jackpot-scrape]
        [ALERT]` (grepable) y devuelve `None` en vez de un valor sospechoso; el caller
        decide mantener el último valor bueno.
      - `engine/server.py`: nuevo endpoint `POST /fetch-jackpot` (`{game_id}` ->
        `{found, amount, cash_value, source}` o `{found: false}`).
      - `src/container.js`: nuevo helper `fetchJackpotFromEngine()`.
      - **Migración D1 aplicada a producción real** (vía MCP de Cloudflare): tabla
        `jackpots` (una fila por juego -- `lottery_id` PK, `amount`, `cash_value`,
        `source`, `last_status`, `last_success_at`, `last_attempt_at`). Confirmada con
        `PRAGMA table_info` + un UPSERT de prueba real (después revertido al valor
        correcto). `schema/d1_schema.sql` actualizado en paralelo.
      - `src/worker.js`: nueva `refreshJackpot()`, enganchada como tercer paso de
        `runPipeline()` (no bloqueante -- un fallo acá nunca tira abajo generar/evaluar
        tickets, que es lo que importa de verdad). Si el fetch falla el validador,
        solo actualiza `last_status='stale_parser_broken'` sin tocar el último valor
        bueno. Nuevo endpoint `GET /api/jackpot?game=` que lee de D1 y calcula
        `stale: true` si `last_status != 'ok'` o si pasaron más de 5 días desde el
        último éxito.
      - `public/game.js`: `renderJackpot()` ahora llama a `/api/jackpot` real en vez
        de `JACKPOT_MOCK` (eliminado). Si `stale`, muestra el último valor bueno con
        una nota de que puede estar desactualizado, en vez de fallar en silencio.
      - **Verificado end-to-end** (sin poder correr `wrangler dev` en este sandbox,
        mismo patrón que sesiones previas): `fetch_jackpot.py` probado contra las
        fuentes reales (powerball y mega_millions, valores reales del día:
        $434M/$194.7M y $576M/$253.9M), endpoint `/fetch-jackpot` probado con
        `TestClient` real (200 para ambos juegos, 400 para juego inválido), UPSERT de
        `jackpots` probado contra D1 real, `node --check`/`py_compile` limpios en los
        5 archivos tocados, grep repo-wide sin referencias colgantes a `JACKPOT_MOCK`.
      - **Pendiente real**: falta el `wrangler deploy` desde terminal Windows para que
        esto llegue a producción (mismo gotcha de siempre -- este sandbox no puede
        deployar). Una vez deployado, el próximo cron (o el primer request a
        `/api/jackpot`) va a poblar la tabla `jackpots` de verdad para ambos juegos.

## Hecho (2026-07-07, sesión 21 — automatización de `wins`, Scoreboard, Next Draw Tickets)

- [x] **Pedido de Orlando**: automatizar el registro de premios en `wins` para
      CUALQUIER ticket ganador (no solo matches de 4+, como venía siendo manual desde
      el schema original), poder ver todos los tickets ganadores aunque el premio sea
      mínimo, acumular/sumar esos datos para ver cómo rinde cada estrategia por ticket,
      y visualizar los 20 tickets que cada estrategia genera para el próximo sorteo.
      UI/UX pedida "más emocionante y clara estadísticamente" dado el dataset más rico.
      Para 3 decisiones de diseño (panel de rendimiento por estrategia, forma de ver
      los 20 tickets próximos, alcance del Hall of Wins) Orlando delegó 2 en "sorpréndeme"
      y pidió explícitamente **modal** (no expandir inline) para los 20 tickets,
      ordenados de mejor a peor por `confidence`.
- [x] **Migración D1 aplicada a producción real** (vía MCP de Cloudflare):
      `ALTER TABLE wins ADD COLUMN ticket_id INTEGER REFERENCES tickets(id)` +
      `CREATE UNIQUE INDEX idx_wins_ticket_id ON wins(ticket_id) WHERE ticket_id IS NOT NULL`
      — confirmadas con `PRAGMA table_info`/`PRAGMA index_list`. El índice único
      parcial (no sobre `numbers`) es a propósito: dos tickets distintos de la misma
      estrategia/ciclo podrían compartir la misma combinación de números por azar, y
      eso no debe colapsarse en una sola fila de `wins`. `schema/d1_schema.sql`
      actualizado en paralelo.
- [x] **`src/worker.js` — auto-inserción en `wins`**: reescrito `persistStrategyResult()`
      para recuperar el `id` real de cada ticket en ambos caminos posibles (tickets
      pre-generados: el `id` ya viene en `r.tickets`; tickets frescos/catch-up: D1
      `batch()` no devuelve `last_row_id` por statement, así que se re-consultan los
      recién insertados por `cycle_id`+`strategy_id` y se emparejan de vuelta por una
      clave de números+extra). Nueva `insertWinsForTickets()`: filtra
      `prize_amount > 0`, inserta en `wins` vía `INSERT OR IGNORE ... (…, ticket_id)`
      — sin mínimo de premio, sin intervención manual.
- [x] **`src/worker.js` — `/api/wins` con total real**: separado el cálculo de
      `total_amount`/`total_count` (vía `SUM()`/`COUNT()` sobre toda la tabla) de la
      lista paginada que se muestra (`LIMIT` param, default 50, tope 200, ordenada por
      `prize_amount DESC`) — antes el "total" mostrado en el Hall of Wins era literal
      la suma de lo que traía la página, no el total real acumulado.
- [x] **`src/worker.js` — nuevo `/api/ticket-performance?game=`**: agrega por
      `strategy_id` sobre `tickets` (`evaluated=1`): tickets totales, tickets
      ganadores, `total_won` (`SUM(prize_amount)`), `win_rate` (%). Es la base del
      Scoreboard — a diferencia de `strategy_stats` (agregado por ciclo), esto agrega
      sobre cada ticket individual, que es justo lo que Orlando pidió poder ver.
- [x] **`src/worker.js` — nuevo `/api/upcoming-tickets?game=&strategy=`**: busca el
      próximo `cycles` con `status='generated'` para el juego, devuelve sus 20 tickets
      ordenados por `confidence DESC` (o `{found:false}` si el ciclo todavía no se
      generó).
- [x] **Frontend — Strategy Scoreboard** (`#scoreboard`, entre "Strategies" y "Next
      Draw Tickets" en la nav): `renderScoreboard()` en `game.js` pinta una fila por
      estrategia con barra de win-rate, $ total ganado y ratio de tickets ganadores/
      totales; la fila top (si tiene premios) se resalta en dorado con 🥇, mismo
      lenguaje visual que `.win-card.jackpot`.
- [x] **Frontend — Next Draw Tickets + modal** (`#next-tickets`): `renderNextTickets()`
      pinta una card clickeable por estrategia (deshabilitada si el ciclo aún no se
      generó); al hacer click, `openTicketsModal()` abre un modal (`.modal-overlay`/
      `.modal-card`, cierre por botón/click-fuera/Escape) con los 20 tickets de esa
      estrategia, ordenados de mejor a peor por confianza — exactamente como lo pidió
      Orlando.
- [x] **`public/styles.css`**: agregadas todas las reglas nuevas (scoreboard, cards de
      próximos tickets, modal) reusando el sistema de diseño existente — variables
      `--bg-card`/`--border`/`--gold`/`--radius`/`--shadow`, patrón de barra CSS-width
      (`.weight-bar` → `.scoreboard-bar`), patrón de card dorada (`.win-card.jackpot` →
      `.scoreboard-top`), `.ball` reescalado dentro de `.ticket-balls`. Incluye ajustes
      responsive en el `@media (max-width: 600px)` existente.
- [x] **Verificado en este sandbox** (mismo patrón de siempre — no se puede correr
      `wrangler dev`/D1 local acá): `node --check` limpio en `src/worker.js`,
      `src/container.js`, `public/game.js`; `python -m py_compile` limpio en
      `engine/server.py` y `fetch_jackpot.py`; grep cruzado confirmó que cada clase/id
      nuevo referenciado en `game.js` existe en `game.html` y `styles.css` (cero
      huérfanos), y que cada llamada `/api/...` nueva en `game.js` tiene su ruta
      correspondiente en `worker.js`. Se detectó y corrigió un mount-desync en
      `styles.css` (bash veía 499 líneas de un archivo que en Windows tenía 706) con
      el mismo fix de siempre (heredoc desde bash + verificación de balance de llaves).
- [x] **Auditoría independiente antes de deployar** (mismo criterio de siempre —
      no confiar en el resumen del implementador de Cowork): leídos de punta a punta
      los 6 archivos tocados. **Hallazgo real, no cosmético**: `insertWinsForTickets()`
      se llamaba desde `persistStrategyResult()` **sin try/catch propio**, y
      `persistStrategyResult()` se llamaba desde el loop de `evaluatePastCycle()`
      también sin try/catch — si el `db.batch()` de `wins` lanzaba (error transitorio
      de D1, bind con tipo inesperado — `INSERT OR IGNORE` absorbe violaciones de
      constraint pero no errores de red/D1), la excepción se propagaba hasta
      `runPipeline()` e impedía que `generateNextCycle()` corriera para ese juego en
      ese cron — exactamente el escenario que `refreshJackpot()` (sesión 20) sí evita
      con su propio try/catch, pero que acá no se había replicado pese al comentario
      del código diciendo "no debe ser bloqueante". Mitigante parcial ya existente: el
      try/catch por-juego de `scheduled()` evita que se caiga todo el Worker o el otro
      juego, pero el juego afectado sí perdía el paso "generar" ese cron. **Fix
      aplicado en esta sesión**: se envolvió la llamada a `insertWinsForTickets()`
      dentro de `persistStrategyResult()` en su propio try/catch no bloqueante (mismo
      patrón que `refreshJackpot()`), y se re-verificó `node --check`. Se pausó el
      deploy y se reportó el hallazgo a Orlando antes de continuar — confirmó
      "arreglar y deployar".
      Hallazgo secundario, menor, no bloqueante: en la rama catch-up de
      `persistStrategyResult()`, si dos tickets de la misma estrategia/ciclo
      comparten números por azar (probabilidad ~1 en cientos de millones), el `Map`
      de emparejamiento por clave de números solo se queda con el `id` del último, así
      que ambos tickets originales resuelven al mismo `id` real — no genera
      duplicados en `wins` (el índice único + `OR IGNORE` lo cubren), pero uno de los
      dos tickets ganadores reales quedaría sin su fila en `wins`. Dada la
      probabilidad, no se consideró bloqueante ni se tocó en esta sesión.
      Resto de la auditoría, limpio: índice único parcial sobre `ticket_id` correcto
      (`insertWinsForTickets()` descarta cualquier ticket con `id == null` antes de
      insertar, así que nunca hay una fila con `ticket_id` NULL que evada el índice);
      `node --check` limpio en los 3 JS; grep confirmó `/api/wins` y `renderWins()`
      usan consistentemente la forma nueva (`total_amount`/`total_count`/`wins`), sin
      referencias colgantes al array plano viejo; IDs de DOM (`scoreboard-list`,
      `next-tickets-grid`, `tickets-modal-overlay`, etc.) coinciden 1:1 entre
      `game.html` y `game.js`.
- [x] **Migración D1 reconfirmada en producción real antes de deployar** (no asumida):
      `PRAGMA table_info(wins)` — columna `ticket_id INTEGER` presente; `PRAGMA
      index_list(wins)` — `idx_wins_ticket_id` presente, `unique=1`, `partial=1`.
      Coincide exactamente con `schema/d1_schema.sql` y con lo que decía el resumen
      de Cowork.
- [x] **Deploy real a producción** (Windows nativo): Docker Desktop ya estaba
      corriendo. Mismo patrón de siempre para `.env` (token con scope `D1:Edit` no
      alcanza para deploy): oculto, un solo `wrangler deploy` de punta a punta sin
      comandos concurrentes tocándolo, restaurado al terminar — confirmado con
      `ls -la` (mismo tamaño/mtime que el original). Build de la imagen del Container
      limpio (~78s de `pip install`), push al registry de Cloudflare exitoso,
      aplicación de Container actualizada. **Versión deployada:
      `f21aca55-82d0-444e-9117-875ca39aca9d`.**
- [x] **Verificación post-deploy contra producción real**: `/api/health` (200), `/`
      (200), `/game.html?game=powerball` y `?game=mega_millions` (307 -> 200 siguiendo
      el redirect esperado). `/api/ticket-performance?game=powerball` y
      `?game=mega_millions` — ambos devuelven datos agregados reales por estrategia
      (tickets ya evaluados por el cron real de días previos). `/api/upcoming-tickets`
      para una estrategia real de cada juego — `found:true` con los 20 tickets
      ordenados por `confidence` en ambos. `/api/wins?game=powerball` — forma nueva
      confirmada (`{total_amount, total_count, wins}`), pero **`total_count:0`
      todavía** — esperado: los tickets ya evaluados lo fueron por el código VIEJO
      (antes de este deploy), que no tenía `insertWinsForTickets()`; recién se va a
      empezar a poblar en la próxima evaluación real (`evaluatePastCycle()` corriendo
      con el código nuevo), no retroactivo. Verificación visual real en navegador
      (Chrome vía MCP, contra la URL de producción, no local): `/game.html` de ambos
      juegos cargan sin errores de consola; sección Scoreboard y Next Draw Tickets
      renderizan con datos reales; el modal de "ver los 20 tickets" abre correctamente
      al hacer click en una card de estrategia (probado con Coverage Optimizer,
      Powerball) y cierra bien. `wrangler tail` en vivo (mismo truco de ocultar/
      restaurar `.env`) confirmó requests reales a `/api/ticket-performance`,
      `/api/upcoming-tickets` y `/api/wins` con status `Ok`, sin errores.
- [x] **Limpieza de Docker post-deploy**: borrada la imagen de producción anterior
      (`...:585b1b83`, superseded por `f21aca55`) y el tag local redundante
      (`shiol-plus-enginecontainer:f21aca55`, mismo digest que el tag de registry).
      Build cache vaciado (`docker builder prune -f`).
- [ ] **Pendiente, no se puede confirmar hasta que pase**: `wins` se va a empezar a
      poblar recién con la próxima evaluación real de cada juego (próximo cron). El
      hallazgo secundario de colisión de números en tickets frescos/catch-up (ver
      arriba) sigue sin resolver — probabilidad ínfima, no se priorizó.

## Hecho (2026-07-07, sesión 20 — auditoría + deploy real de "Current Jackpot")

- [x] **Auditoría independiente antes de deployar** (mismo criterio de siempre --
      no confiar en el resumen del implementador): leídos de punta a punta los 6
      archivos tocados (`engine/pipeline/fetch_jackpot.py`, `engine/server.py`,
      `src/container.js`, `src/worker.js`, `public/game.js`, `schema/d1_schema.sql`).
      Sin hallazgos -- la auditoría confirmó exactamente lo que decía el resumen:
      `fetch_jackpot.py` nunca devuelve un valor fuera de rango (`_validate()`
      cubre `None`/fuera de `$20M-$5B` para ambos campos, todo error pasa por
      `[jackpot-scrape][ALERT]` y devuelve `None`, nunca lanza fuera de
      `fetch_jackpot()`); `refreshJackpot()` corre como tercer paso de
      `runPipeline()` envuelta en try/catch propio (además del try/catch interno
      al llamar `fetchJackpotFromEngine()`) -- un fallo ahí nunca puede tirar
      abajo `evaluatePastCycle()`/`generateNextCycle()`, que ya corrieron antes;
      `/api/jackpot` maneja tanto "no hay fila todavía" como "fila con `amount`
      NULL" devolviendo `{found:false}` sin excepción; `lotteryId` tiene default
      `'powerball'` así que no hay caso de `game` faltante sin manejar. Grep
      repo-wide confirmó cero referencias a `JACKPOT_MOCK` fuera de este mismo
      TODO.md (histórico). `node --check` en los 3 JS y `py_compile` en los 2
      Python, limpios. Migración de `jackpots` reconfirmada en D1 de producción
      real (`PRAGMA table_info` -- coincide exactamente con el schema) con una
      fila real de Powerball ya cargada (`$434M`/`$194.7M`, `last_status='ok'`).
- [x] **Deploy real a producción** (Windows nativo): Docker Desktop no estaba
      corriendo, se inició y se esperó a que quedara listo antes de deployar.
      `node_modules` ya tenía binarios reales (no shim) de una sesión previa --
      no hizo falta reinstalar. Mismo patrón de siempre para el `.env` (token
      con scope `D1:Edit` no alcanza para deploy): se ocultó `.env`, se corrió
      **un solo comando** `wrangler deploy` de punta a punta sin ningún otro
      comando tocando `.env` en paralelo, y se restauró al terminar -- confirmado
      con `ls -la` que quedó igual (mismo tamaño y mtime) al original. Build de
      la imagen del Container corrió limpio (~80s de `pip install`, capas base
      cacheadas de Docker Desktop recién iniciado), push al registry de
      Cloudflare exitoso, aplicación de Container actualizada. **Versión
      deployada: `585b1b83-ce4a-46b3-be9c-2b4d33295a2e`.**
- [x] **Verificación post-deploy contra producción real**: `/api/health` (200),
      `/` (200), `/game.html?game=powerball` y `?game=mega_millions` (307 ->
      200 siguiendo el redirect esperado de Workers Static Assets, contenido
      confirmado con el marcador `jackpot-amount` presente en el HTML servido),
      `/api/games` (ambos juegos activos), `/api/jackpot?game=powerball`
      (**`found:true`, `$434,000,000`/`$194,700,000`, `source:nclottery.com`,
      `stale:false`** -- la fila de prueba cargada hoy en D1 se sirve
      correctamente end-to-end), `/api/jackpot?game=mega_millions`
      (`found:false`, esperado -- esa fila no se pobló manualmente, se completa
      con el próximo cron o un fetch manual). `wrangler tail` en vivo (mismo
      truco de ocultar `.env`, correr, restaurar) confirmó requests reales
      llegando con status `Ok` a `/api/jackpot`, `/api/games` y `/`, sin errores.
- [x] **Limpieza de Docker post-deploy**: borrada la imagen de producción
      anterior (`...:ba01dc2b`, superseded por `585b1b83`) y el tag local
      redundante (`shiol-plus-enginecontainer:585b1b83`, mismo digest que el
      tag de registry ya etiquetado). Build cache vaciado (`docker builder
      prune -f`, liberó 2.454GB). Quedó solo la imagen real en uso
      (`585b1b83`) + imágenes de otros proyectos sin relación (no tocadas).
- [ ] **Pendiente, no se puede confirmar hasta que pase**: `mega_millions`
      queda con `found:false` en `/api/jackpot` hasta que corra el próximo
      cron real (o se dispare un fetch manual) -- no es un bug, es esperado.

## Hecho (2026-07-06, sesión 17)

- [x] **Investigación**: "Top Pick Right Now" en el dashboard de Powerball tardaba en
      cargar y cambiaba el set de números en cada refresh. Causa raíz encontrada:
      `/api/top-pick` (`worker.js`) llamaba a `generateEngineTickets()` →
      `/generate-tickets` (`engine/server.py`) en cada request, sin caché — creaba una
      instancia nueva de la estrategia cada vez (perdiendo el caché de entrenamiento de
      XGBoost, ~69 clasificadores re-entrenados por request para Powerball) y sampleaba
      con `np.random.choice()` sin semilla fija (`xgboost_ml.py`). Además, ni el ticket de
      top-pick ni los tickets del cron real (`run-cycle`) se persisten individualmente —
      solo se guardan los agregados por estrategia (`cycles`/`strategy_stats`), por lo que
      el número mostrado nunca se evaluaba contra el premio real (mismo gap ya anotado
      como pendiente #3 más abajo, `tickets` nunca se llena).
- [x] **Decisión de Orlando**: eliminar el feature "Top Pick" por completo en vez de
      arreglarlo, ya que sin persistencia ni evaluación real no aporta valor verificable.
      Reemplazado por una card "Current Jackpot" en el mismo lugar del hero (mock estático
      por ahora, sin llamada a API — pendiente real: conectar a una fuente real de jackpot
      por juego).
- [x] **Eliminado de punta a punta**: endpoint `/api/top-pick` (`worker.js`),
      `generateEngineTickets()` (`container.js`), endpoint `/generate-tickets` y
      `GenerateTicketsRequest` (`engine/server.py`), `renderTopPick()` y su llamada
      (`game.js`), markup y CSS (`game.html`, `styles.css`), mención en el ADR-0001. Cero
      rastro confirmado por grep en todo el repo.
- [ ] Pendiente: conectar `Current Jackpot` a una fuente de datos real (hoy es mock
      hardcodeado por juego en `game.js`).
- [x] **Resuelto el gap de persistencia de tickets (pendiente #3 histórico)**: los 20
      tickets por estrategia que genera y evalúa `run-cycle` ya no se descartan.
      `engine/server.py` ahora incluye `evaluated_tickets` (ya calculados por
      `evaluate.py`, solo dejaron de tirarse) dentro de `strategy_results[name].tickets`.
      `worker.js::runPipeline` los persiste en la tabla `tickets` de D1 vía `db.batch()`
      (uno por estrategia, no 160 inserts sueltos), con `DELETE FROM tickets WHERE
      cycle_id=? AND strategy_id=?` previo por idempotencia (la generación es no
      determinística — sampling aleatorio — así que un reintento de un ciclo fallido a
      medias generaría un set distinto al que ya pudiera existir).
- [x] **Migración de schema aplicada en D1 real de producción** (vía MCP de Cloudflare,
      no wrangler CLI): columna `tickets.draw_date TEXT NOT NULL DEFAULT ''` +
      `idx_tickets_draw_date(lottery_id, draw_date)`. Denormalizado a propósito (además
      de `cycle_id`) para poder evaluar premios contra el sorteo real sin JOIN.
      `schema/d1_schema.sql` actualizado en paralelo para reflejar el estado real.
- [x] Superado por el rediseño de sesión 18 (mismo día) -- ver abajo: el modelo de
      "generar y evaluar en el mismo paso" se reemplazó por un pipeline de dos fases.

## Hecho (2026-07-06, sesión 18) -- pipeline de dos fases

- [x] **Rediseño del pipeline, a pedido de Orlando**: el modelo de sesión 17 (generar
      tickets y evaluarlos siempre en el mismo paso, contra un sorteo que YA había
      ocurrido) se reemplazó por un flujo de dos fases real:
        1. **Generar** (`generateNextCycle()`): calcula el PRÓXIMO sorteo (todavía no
           ocurrió) y, si no se generó ya, arma 20 tickets x 8 estrategias por
           adelantado y los guarda en D1 sin evaluar (`cycles.status='generated'`,
           `tickets.evaluated=0`).
        2. **Evaluar** (`evaluatePastCycle()`): busca el último sorteo que ya debería
           haber pasado, intenta traer el resultado real (poll -- si no está publicado
           todavía, no es error, se reintenta en el próximo cron), y si hay tickets
           `generated` para esa fecha los evalúa contra el resultado real, actualizando
           esas mismas filas (`UPDATE`, no insert) + `strategy_stats` + pesos.
      Usa la tabla `cycles` con sus 3 estados ya existentes en el schema
      (`pending`/`generated`/`evaluated`) que nunca se habían aprovechado de verdad.
- [x] **Opción B (catch-up)**: si en el paso "evaluar" no hay tickets pre-generados
      para el sorteo que ya pasó (primera corrida de este flujo, o un ciclo que se
      saltó), se genera Y evalúa en un solo paso -- mismo comportamiento que sesión 17,
      usado como fallback, no como default.
- [x] **Motor Python (`engine/server.py`) partido en piezas reusables**: se extrajo
      `_generate_tickets_for_game()` y `_evaluate_tickets_for_game()` del cuerpo de
      `/run-cycle`. Tres endpoints comparten esa misma lógica sin duplicar nada:
      `/generate-cycle` (solo genera, no necesita el sorteo real ni pesos),
      `/evaluate-cycle` (solo evalúa tickets ya generados, recibidos con su `id` de D1
      para poder hacer `UPDATE` en vez de `INSERT`), y `/run-cycle` (fallback de
      catch-up, sin cambios de comportamiento respecto a sesión 17).
- [x] **`src/container.js`**: nuevos helpers `generateEngineCycle()` y
      `evaluateEngineCycle()`, llamando a los endpoints nuevos.
- [x] **`src/worker.js`**: nueva función `nextDrawDate()` (espejo de `lastDrawDate()`
      pero hacia adelante), `loadStrategiasAndWeights()` y `persistStrategyResult()`
      extraídas como helpers compartidos entre las dos fases, `runPipeline()` ahora
      solo orquesta `evaluatePastCycle()` + `generateNextCycle()` en secuencia.
- [x] **Sin cambios de infraestructura**: mismos 6 cron triggers de siempre alcanzan
      (cada draw day corre 2 veces/día); no hizo falta tocar `wrangler.toml` ni el
      schema de D1 (la columna `draw_date` y los 3 estados de `cycles` ya estaban).
- [x] **Deploy a producción auditado y confirmado (sesión 19)** -- ver detalle abajo.
- [ ] Pendiente (sin resolver, ya anotado en sesión 17): conectar `Current Jackpot` a
      una fuente de datos real.

## Hecho (2026-07-06, sesión 19 — auditoría + deploy del pipeline de dos fases)

- [x] **Auditoría independiente de las sesiones 17 y 18** antes de deployar (mismo
      criterio que siempre — no confiar en el resumen del implementador sin leer el
      código real): `engine/server.py` (endpoints `/generate-cycle`,
      `/evaluate-cycle`, `/run-cycle` fallback, helpers compartidos
      `_generate_tickets_for_game`/`_evaluate_tickets_for_game`), `evaluate.py`
      (confirmado que `evaluate_strategy()` devuelve `evaluated_tickets` con
      `matches_white`/`matches_extra`/`prize_level`/`prize_amount`, y que preserva
      `id` del ticket de entrada vía `{**ticket, ...}`), `src/worker.js`
      (`evaluatePastCycle`/`generateNextCycle`/`persistStrategyResult`,
      `nextDrawDate()` espejo de `lastDrawDate()`), `src/container.js`
      (`generateEngineCycle`/`evaluateEngineCycle` nuevos, coinciden con los
      endpoints de `server.py`), `public/game.html`/`game.js`/`styles.css`
      (Top Pick eliminado de punta a punta, `Current Jackpot` mock agregado
      correctamente). Confirmado con `grep` repo-wide: cero referencias colgantes a
      `top-pick`/`generateEngineTickets`/`GenerateTicketsRequest`.
- [x] **Verificado contra D1 de producción real** (no solo el código): la migración
      de `tickets.draw_date` + `idx_tickets_draw_date` (aplicada en sesión 17 vía
      MCP) confirmada presente con `PRAGMA table_info`/`PRAGMA index_list` — no es
      solo lo que dice `schema/d1_schema.sql`, es lo que hay de verdad en D1.
- [x] **Hallazgo menor investigado y descartado como bug**: `game.html` usa la clase
      `.jackpot-card`, que no existe en `styles.css` -- pero tampoco existe
      `.countdown-card` (mismo patrón ya usado antes), porque el estilo real de
      ambas cards lo da la clase compartida `.hero-card`. No es una regresión.
- [x] **`node --check`/`py_compile`** en los 6 archivos tocados (worker.js,
      container.js, game.js, home.js, server.py, evaluate.py) -- todos limpios.
- [x] **Smoke test funcional local** (WSL2 + Docker, antes de tocar producción):
      migración `tickets.draw_date` ya existía en D1 local (de una corrida previa);
      cron simulado (`/cdn-cgi/handler/scheduled`) corrió el pipeline de dos fases
      real -- Powerball hizo skip correcto (`draw_not_available` para el próximo
      sorteo, `already_generated` para el ciclo futuro ya armado), Mega Millions
      ejecutó el catch-up (Opción B) de punta a punta, evaluando 8 estrategias
      contra el draw real 2026-07-03 vía `/run-cycle`. **La ruta más nueva y de
      mayor riesgo -- evaluar tickets PRE-generados (la que hace `UPDATE` en vez de
      `INSERT`, nunca ejercida hasta ahora porque todos los ciclos previos habían
      usado el camino catch-up -- se probó aparte**, directo contra `/evaluate-cycle`
      vía `TestClient` con tickets reales (`id` 16/17) leídos de un ciclo
      `status='generated'` que ya existía en D1 local: confirmado que el `id` del
      ticket de entrada se preserva en la respuesta, cerrando el contrato completo
      JS↔Python que `persistStrategyResult()` necesita para el `UPDATE`.
      `/generate-cycle` probado aparte también, las 8 estrategias devuelven tickets
      válidos.
- [x] **Deploy real a producción** (Windows nativo, mismo checklist de siempre:
      Docker Desktop, `node_modules` reinstalado, sesión OAuth confirmada; esta vez
      sin la carrera de `.env` de la sesión 16 -- se corrió un solo comando de
      deploy sin ningún otro comando tocando `.env` en paralelo). Container
      reconstruido (capas de `pip install` cacheadas, build casi instantáneo),
      aplicación de Container actualizada, cron triggers re-confirmados. Versión
      activa: `ba01dc2b-642b-4324-a5ad-12676a529a08`. Container pasó a `ready` en
      ~90s.
- [x] **Verificación POST-deploy contra producción real**: `/api/health` (200),
      `/` (200), `/game.html?game=powerball` y `?game=mega_millions` (ambos sirven
      bien, título correcto), `/api/games` (los dos juegos activos),
      `/api/top-pick` (**404 confirmado, correctamente eliminado**),
      `/api/latest-cycle?game=powerball` (datos previos intactos, sin pérdida),
      `/api/latest-cycle?game=mega_millions` (`"No cycles yet"` -- correcto, el
      cron real todavía no volvió a correr desde que se activó Mega Millions).
- [x] **Limpieza de Docker post-deploy** (preferencia de Orlando): imágenes
      obsoletas borradas (build de prueba WSL2, tag `:worker` huérfano, versión de
      producción anterior `7f002ddc` superseded, tag local redundante), build
      cache vaciado. Quedó solo la imagen real en uso + el sidecar de Wrangler.
- [ ] **Pendiente, no se puede confirmar hasta que pase**: el próximo cron real
      (martes 2026-07-07) hará catch-up (Opción B) para el primer sorteo desde que
      se activó Mega Millions, y a partir de ahí el flujo de dos fases debería
      asentarse solo (generar el próximo ciclo por adelantado, evaluar el pasado
      leyendo esos tickets pre-generados -- la ruta que en esta sesión solo se
      probó de forma aislada con `TestClient`, todavía no de punta a punta con un
      cron real disparando ambas fases en producción).

## Hecho (2026-07-04)

- [x] Backfill de 91 sorteos faltantes (2025-12-03 -> 2026-07-01) en CSV local y D1.
- [x] Primer ciclo del pipeline corrido y sincronizado a D1.
- [x] Bug fix: la fuente de datos de sorteos (nclottery.com CSV) devolvia 404 -- se
      reemplazo por data.ny.gov (Socrata) como fuente primaria en
      `lab/pipeline/fetch_draw.py`, `lab/games/powerball.py`, `lab/games/mega_millions.py`
      y `src/worker.js`. El CSV viejo se dejo como fallback por si vuelve a funcionar.
- [x] Bug fix: los cron triggers de `wrangler.toml` nunca se habian registrado en
      Cloudflare porque usaban numeracion Unix de dia de semana (0=domingo). Cloudflare
      usa 1=domingo...7=sabado. Se corrigio usando abreviaciones (SUN/TUE/THU) en vez de
      numeros -- evita la ambiguedad para siempre.
- [x] Deploy hecho via `npx wrangler deploy` desde Windows (con OAuth, no con el token
      de .env que solo tiene scope D1:Edit).

## Hecho (2026-07-04, sesión 2 — rediseño de frontend)

- [x] `public/` confirmado como fuente de verdad del frontend (Orlando lo aclaró explícitamente).
      Se creó `build.js`: lee `public/index.html`, `public/styles.css`, `public/app.js` y genera
      `src/frontend.generated.js` (gitignored), que `src/worker.js` ahora importa
      (`import { HTML, CSS, APP_JS } from './frontend.generated.js'`) en vez de tener el
      HTML/CSS/JS embebido a mano como antes. `package.json`: `deploy`/`dev` ahora corren
      `npm run build` primero automáticamente.
- [x] Nuevo endpoint de solo lectura `/api/top-pick?game=powerball`: identifica la estrategia
      activa con mayor `current_weight` y genera un ticket fresco en caliente con
      `generateTickets()` (la misma función que usa el pipeline real) — no persiste nada.
- [x] Frontend rediseñado con foco en el concepto real del producto (torneo de 8 estrategias,
      no "predicción única"): sección hero nueva con countdown en vivo al próximo sorteo
      (calculado en `public/app.js` vía `Intl.DateTimeFormat` con `America/New_York`, sin
      librerías) + "Top Pick" (estrategia líder + ticket generado en vivo). Tabla de
      Strategy Rankings ahora incluye una columna de sparkline (SVG inline) con la tendencia
      de peso de cada estrategia en los últimos 12 ciclos (`/api/history?strategy=X`). Hall of
      Wins ahora muestra el total acumulado ganado como titular.
      Explícitamente NO se agregó hot/cold de números (decisión de Orlando: no es el foco).
- [x] Verificado (sandbox Linux, sin poder correr `wrangler`): sintaxis de `worker.js`,
      `build.js` y `frontend.generated.js` con `node --check`; las 8 estrategias generan
      tickets válidos (`generateTickets` probado con datos falsos); la lógica de countdown
      probada contra fechas reales en EDT y EST — resuelve correctamente a 22:59 ET del
      próximo Mon/Wed/Sat en ambos casos.
- [ ] **Falta**: probar de verdad con `npm run dev` (`wrangler dev`) desde Windows antes de
      `npm run deploy` — este sandbox no puede correr `wrangler` (ver gotcha de abajo), así
      que el flujo completo build→sirve→API nunca se ejecutó end-to-end, solo se verificó
      por partes (sintaxis + lógica pura). Revisar visualmente el hero, el countdown corriendo,
      el top pick, y los sparklines antes de desplegar a producción.

## Hecho (2026-07-04, sesión 3 — fix bugs en lab/pipeline/sync_d1.py)

- [x] Bug fix: `sync_d1.py --date YYYY-MM-DD` armaba el nombre de archivo legacy
      `cycle_{date}.json`, pero `run.py` genera `cycle_{game_id}_{date}.json` desde el
      refactor game-agnostic. Se agregó `--game` (default `powerball`) y ahora `--date`
      arma el nombre correcto. `--latest` y `--file` no tenían este problema.
- [x] Bug fix (más serio, no reportado antes): todas las funciones de `sync_d1.py`
      (`sync_draw`, `sync_cycle`, `sync_strategy_stats`, `sync_strategy_weights`) tenían
      `lottery_id='powerball'` hardcodeado como default y `sync_cycle_file` las llamaba
      sin pasar `lottery_id`, ignorando el `game_id` real que sí viene en el JSON. Hoy no
      se notaba porque solo hay Powerball activo, pero al activar Mega Millions esto iba a
      escribir silenciosamente todos los datos bajo `lottery_id='powerball'` en D1,
      mezclando ambas loterías sin ningún error visible. Ahora `sync_cycle_file` lee
      `data.get('game_id', 'powerball')` y lo pasa explícito a las 4 funciones.
- [x] Verificado con mocks (sin tocar D1 real): sintaxis (`py_compile`), `--date` arma el
      path correcto, y las 8 llamadas SQL (draws/cycles/strategy_stats/strategies) reciben
      el `lottery_id` real del JSON en vez de `powerball` fijo.

## Hecho (2026-07-04, sesión 4 — auditoría completa + decisión arquitectónica)

- [x] Auditoría completa de `src/worker.js`, todo `lab/pipeline/` y todo
      `lab/strategies/`. Hallazgo principal: **6 de las 8 estrategias implementan
      algoritmos distintos en JS vs Python bajo el mismo nombre** (`xgboost_ml` en JS
      no usa ML real, `hybrid_ensemble` en JS no toca XGBoost pese a su descripción,
      `intelligent_scoring` en JS no tiene decay temporal real, `cooccurrence` en JS
      pierde la estructura de pares, `range_balanced` usa 3 vs 5 rangos distintos).
      También se confirmó un bug nuevo en `lab/games/register.py`: genera IDs de
      estrategia con sufijo de juego (`frequency_weighted_mega_millions`) que
      `run.py`/`sync_d1.py` nunca esperan (siempre usan el nombre plano) — al activar
      un segundo juego, los pesos de esas estrategias nunca se actualizarían.
- [x] **Decisión arquitectónica tomada, luego revisada el mismo día** (ver
      [`docs/adr/0001-python-first-engine-docker-cloudflare-standby.md`](docs/adr/0001-python-first-engine-docker-cloudflare-standby.md)):
      versión final — el motor de estrategias (`engine/`, antes `lab/`, renombre
      definitivo) corre en Python dentro de un **Cloudflare Container** (GA desde
      13 abr. 2026); todo lo demás (API, cron, frontend, base de datos) queda
      **100% nativo en Cloudflare**, sin salir de la plataforma: D1 sigue siendo
      la única base de datos (en local, `wrangler dev`/`vite dev` la simulan
      automáticamente, sin SQLite paralela), y el frontend se sirve como
      **Workers Static Assets** en vez de Cloudflare Pages separado. Orlando ya
      activó el plan **Workers Paid (US$5/mes)**, requisito para usar Containers.
      Esto resuelve automáticamente el punto 5 original (ya no hay dos fórmulas
      de peso conviviendo — solo existe la de Python, corriendo en el Container).

## Hecho (2026-07-04, sesión 5 — Fase 1 de la migración: engine/ + server.py)

- [x] Renombrado `lab/` → `engine/` en todo el repo (directorio + los ~20 imports
      internos `from lab...`/`import lab...` + menciones en docstrings, comentarios
      de `src/worker.js` y el diagrama de `README.md`). Confirmado con grep que no
      queda ninguna referencia viva a `lab.*` en el proyecto (fuera de node_modules).
- [x] Creado `engine/server.py`: API HTTP interna con FastAPI, **stateless** (no toca
      disco ni red externa — reemplaza el flujo de CLI+JSON en disco de `run.py` para
      el camino de producción; `run.py` se mantiene intacto para uso manual/backtest).
      Dos endpoints:
      - `GET /games` — config completa de todos los juegos (prize_table serializado a
        lista JSON-safe, ya que sus keys son tuplas). Es la fuente única de verdad que
        el Worker sincronizará a la tabla `lotteries` de D1 (Fase 2/3).
      - `POST /run-cycle` — recibe `game_id`, `draw`, `draws_history`,
        `current_weights`, `total_cycles`, `tickets_per_strategy`; genera tickets,
        evalúa contra el draw real, calcula pesos nuevos, y devuelve el resultado
        completo (mismo shape que los `cycle_*.json` viejos) para que el Worker lo
        escriba a D1 con su binding nativo.
      - Fix de raíz aprovechado al diseñar el contrato: el wire format usa `extra`
        (igual que la columna de D1) en vez de `pb` (nombre interno que usan las 8
        estrategias) — la conversión se hace en un solo lugar (`server.py`), en vez
        de propagar la ambigüedad pb/extra que ya había causado una fragilidad menor
        en `evaluate.py` (detectada en la auditoría de la sesión 4).
- [x] `requirements.txt`: agregado `fastapi>=0.115` y `uvicorn[standard]>=0.32`.
- [x] Creado `engine/Dockerfile` (python:3.11-slim, build context = raíz del repo,
      `CMD uvicorn engine.server:app`). Sin probar con Docker real todavía (no hay
      Docker en el sandbox de desarrollo) — pendiente probarlo desde Windows.
- [x] Verificado (sin Docker, con `fastapi.testclient.TestClient`): `py_compile` de
      todos los módulos de `engine/`; `/games` responde 200 y es 100% JSON-serializable
      para powerball y mega_millions; `/run-cycle` llamado con el draw real de
      2026-07-01 + 500 draws históricos reales + los `weight_before` reales del
      `cycle_powerball_2026-07-01.json` — la fórmula de peso devuelta por el endpoint
      coincide exactamente (diferencia < 1e-6) con recalcularla a mano usando
      `engine/pipeline/weights.py` sin cambios, para las 8 estrategias. (Los valores
      de ROI/premio no se comparan 1:1 contra el JSON viejo porque la generación de
      tickets es aleatoria por diseño — lo que se valida es que el pipeline de cálculo
      de pesos sigue siendo el mismo de siempre, ahora servido por HTTP.)
- [x] De paso, arreglado un archivo `data/cycle_powerball_2026-07-01.json` truncado
      por el bug de mount-desync (ver gotcha de abajo) — reescrito vía heredoc,
      confirmado válido con `json.load`.

## Hecho (2026-07-05, sesión 6 — Fase 2: Container en wrangler.toml + src/container.js)

- [x] `wrangler.toml`: agregado `[[containers]]` (`class_name = "EngineContainer"`,
      `image = "./engine/Dockerfile"`, `image_build_context = "."` — necesario porque
      por defecto Wrangler usa como contexto la carpeta del Dockerfile, no la raíz),
      `instance_type = "basic"` (1/4 vCPU, 1 GiB RAM, 4 GB disco — punto de partida
      razonable para pandas/numpy/xgboost/scikit-learn con el volumen de datos actual;
      subir a `standard-1` si en la práctica no alcanza), `max_instances = 1` (proyecto
      personal, sin concurrencia real). Agregado también el binding
      `[[durable_objects.bindings]]` (`name = "ENGINE"`) y la migración
      `[[migrations]] tag = "v1" new_sqlite_classes = ["EngineContainer"]` (primera
      Durable Object del proyecto, sin conflicto de tags).
- [x] Creado `src/container.js`: clase `EngineContainer extends Container`
      (`defaultPort = 8000` para calzar con `uvicorn --port 8000` del Dockerfile,
      `sleepAfter = "2m"` porque el motor solo se usa unas pocas veces por semana —
      apagarlo rápido ahorra el costo de CPU activo) + dos helpers, `getEngineGames(env)`
      y `runEngineCycle(env, payload)`, que usan una instancia singleton
      (`getContainer(env.ENGINE, "engine")`) para hablarle al contenedor por HTTP.
- [x] `src/worker.js`: agregado `export { EngineContainer } from './container.js'`
      (obligatorio — Wrangler necesita que la clase Durable Object esté exportada
      desde el entrypoint del Worker para resolver el binding). **A propósito NO se
      tocó nada más de `worker.js`**: el cron y los endpoints siguen usando la lógica
      JS vieja (`generateTickets`/`evaluateTickets`/`updateWeight`) por ahora — conectar
      de verdad `runEngineCycle()` al pipeline de producción es la Fase 3, un paso
      separado para no arriesgar el pipeline en producción de una sola vez.
- [x] `package.json`: agregada la dependencia `@cloudflare/containers` (`^0.2.0`).
- [x] Verificado sin Docker/wrangler (no disponibles en este sandbox): `node --check`
      en `src/container.js` y `src/worker.js` (sintaxis válida), y el `wrangler.toml`
      parseado con un parser TOML real (`tomli`) para confirmar que `[[containers]]`,
      `[[durable_objects.bindings]]` y `[[migrations]]` quedaron bien formados. **Falta
      probar de verdad** con Docker Desktop + `wrangler dev`/`vite dev` desde Windows
      (no se pudo hacer end-to-end en este sandbox) antes de cualquier deploy real.

## Hecho (2026-07-05, sesión 6 — Fase 3: runPipeline() llama al Container)

- [x] `runPipeline(game, env, ticketsPerStrategy)` reescrita (antes recibía `db`,
      ahora recibe `env` completo porque necesita el binding `env.ENGINE`). El cron
      sigue trayendo el draw real (`fetchDrawFromNyData`/`fetchDrawFromCSV`, JS —
      eso nunca fue parte del "motor", solo es HTTP+parseo) y sigue leyendo/escribiendo
      D1 directamente, pero **generar tickets, evaluar contra el draw, y calcular los
      pesos nuevos ahora lo hace `engine/server.py` vía `runEngineCycle()`** — ya no
      hay una segunda implementación JS de las 8 estrategias corriendo en producción.
      El SELECT de histórico ahora incluye `draw_date` (antes faltaba — hacía falta
      para armar el payload del motor).
- [x] Los resultados que devuelve el Container se escriben a D1 con el binding nativo
      (`env.DB.prepare(...).bind(...).run()`), reemplazando el flujo viejo de
      `engine/pipeline/sync_d1.py` (que subía resultados por la API REST de D1 desde
      un proceso Python separado, corrido a mano). `tickets_total` del ciclo se corrige
      con el valor real que devuelve el motor (antes quedaba con la estimación inicial).
- [x] Eliminado de `worker.js` el código que ya no usa nadie: `evaluateTickets()`,
      `updateWeight()`, `PRIZE_TABLES`, y las constantes
      `LEARNING_RATE`/`PROBATION_THR`/`ARCHIVE_THR`/`MIN_CYCLES` — esa lógica solo
      existe en `engine/pipeline/weights.py` y `evaluate.py` ahora.
      **`generateTickets()` y sus helpers (`buildFreqMap`, `buildCoocMap`,
      `weightedSample`, `randomTicket`) NO se borraron** — `/api/top-pick` (preview
      en vivo, de solo lectura) todavía los usa. Sigue siendo una divergencia JS/Python
      menor y consciente, no resuelta en esta fase — ver nota abajo.
- [x] Verificado sin Docker/wrangler: `node --check` en el `worker.js` reescrito, y una
      prueba con mocks (D1 falso + Container falso vía un shim de
      `@cloudflare/containers` en `node_modules`, solo para el test) que ejecuta
      `scheduled()` de punta a punta y confirma: el payload enviado al motor tiene el
      shape correcto, se escriben exactamente N `strategy_stats` y N updates de
      `strategies` (N = estrategias activas), y los valores (`weight_before`,
      `weight_after`, `matches_4`, `total_prize`, etc.) llegan correctos a las queries
      de D1. **Nota de limpieza**: el shim de prueba en
      `node_modules/@cloudflare/containers/` no se pudo borrar por un problema de
      permisos del sandbox (archivos quedaron con `Operation not permitted` al
      intentar `rm`) — no es un problema real (`node_modules` no se versiona y un
      `npm install` real lo va a sobreescribir), pero **correr `npm install` antes de
      `wrangler dev`/`vite dev`** para asegurarse de tener el paquete real y no el shim.

## Hecho (2026-07-05, sesión 7 — resuelto: /api/top-pick también usa el Container)

- [x] Nuevo endpoint `POST /generate-tickets` en `engine/server.py`: genera N tickets
      para UNA estrategia, sin evaluar contra ningún draw y sin tocar pesos (a
      diferencia de `/run-cycle`, que hace las tres cosas). Pensado para previews de
      solo lectura como el Top Pick del dashboard.
- [x] Nuevo helper `generateEngineTickets(env, payload)` en `src/container.js`, mismo
      patrón que `runEngineCycle`/`getEngineGames`.
- [x] `/api/top-pick` en `worker.js` migrado para usar `generateEngineTickets()` en vez
      de la función JS `generateTickets()`. El SELECT de histórico ahora incluye
      `draw_date` (lo pide el contrato del motor). Si el Container falla o está
      arrancando, el endpoint devuelve un 503 con mensaje amigable en vez de un 500
      crudo o un crash — es solo un preview, no hay nada que perder.
- [x] **Borrado por completo el código JS de estrategias** (`generateTickets`,
      `buildFreqMap`, `buildCoocMap`, `weightedSample`, `randomTicket`) — ya nadie lo
      usa. **Con esto, `engine/` es ahora la única implementación de las 8 estrategias
      en todo el proyecto** — la divergencia JS/Python que motivó el ADR-0001 queda
      completamente eliminada, no solo en el pipeline de producción sino también en el
      preview del dashboard.
- [x] Verificado sin Docker: `TestClient` de FastAPI contra `/generate-tickets`
      (estrategia válida con distintos `tickets_count`, estrategia inválida → 400,
      juego inválido → 400); y una prueba con mocks de `worker.js` cubriendo los 3
      casos de `/api/top-pick` — motor responde bien, motor falla (→ 503 amigable, no
      crash), y sin estrategias activas (→ 404 sin siquiera llamar al Container).

## Hecho (2026-07-05, sesión 7 — Fase 4: frontend a Workers Static Assets)

- [x] `wrangler.toml`: agregado `[assets] directory = "./public" binding = "ASSETS"`.
      `public/` se sirve directo — Cloudflare lo despliega junto con el Worker en un
      solo `wrangler deploy`, sin paso de build intermedio.
- [x] `worker.js`: sacado el import de `frontend.generated.js` y los handlers manuales
      de `/`, `/styles.css`, `/app.js`. El `fetch()` ahora es: `OPTIONS` → 204,
      `/api/*` → `handleAPI()`, todo lo demás → `env.ASSETS.fetch(request)` (mismo
      patrón que recomienda la documentación de Cloudflare para apps full-stack).
- [x] **Borrados `build.js` y `src/frontend.generated.js`** — ya no hacen falta, el
      "empaquetado a mano" del frontend en un string de JS era exactamente el problema
      que Static Assets resuelve nativo. (Nota: estos archivos vivían en una carpeta
      donde el borrado directo estaba bloqueado por el sandbox — se resolvió pidiendo
      permiso explícito antes de borrar, no fue necesario tocar nada fuera de lo ya
      aprobado para esta fase).
- [x] `package.json`: scripts `deploy`/`dev` ya no corren `npm run build` primero
      (no existe más ese paso) — quedan `wrangler deploy` y `wrangler dev` directo.
      Se quitó también el script `build` (ya no tiene nada que ejecutar).
- [x] `.gitignore`: quitada la entrada de `src/frontend.generated.js` (el archivo ya
      no existe ni se genera).
- [x] Confirmado que `public/index.html` referencia `styles.css` y `app.js` con rutas
      relativas (sin `/` inicial) — se resuelven correctamente contra la raíz del
      sitio tal como Cloudflare los sirve desde `public/`, sin cambios necesarios.
- [x] **Decisión: NO se suma el plugin de Vite de Cloudflare por ahora.** Vite aporta
      HMR para frontends compilados/bundleados — este es HTML/CSS/JS plano sin build,
      y `wrangler dev` ya sirve los archivos de `public/` frescos en cada request
      (alcanza con refrescar el navegador). Se puede reconsiderar si el frontend crece
      a necesitar un framework o un paso de build real.
- [x] Verificado sin Docker/wrangler: `node --check` en `worker.js`, y el `wrangler.toml`
      parseado con `tomli` confirmando que `[assets]` quedó bien formado. **Falta
      probar de verdad** que Cloudflare sirve `public/` correctamente vía
      `wrangler dev`/`vite dev` desde Windows (Fase 6).

## Hecho (2026-07-05, sesión 8 — Fase 5: bugs puros de Python)

- [x] **Bug fix (sufijo de `register.py` nunca se traducía)**: `register.py` sufija el
      id de estrategia en D1 con `_{game_id}` para cualquier juego que no sea powerball
      (necesario: `strategies.id` es PRIMARY KEY de una sola columna, dos juegos no
      pueden compartir el mismo id). Pero ni `worker.js` (`runPipeline`, `/api/top-pick`)
      ni `sync_d1.py` (ruta manual/backtest) traducían ese sufijo al hablar con el motor
      Python, que siempre usa nombres planos (`frequency_weighted`, sin sufijo, de
      `ALL_STRATEGIES`). Resultado real: para cualquier juego que no fuera powerball, el
      motor nunca encontraba el peso real (caía al default 1.0) y el `UPDATE strategies`
      de vuelta afectaba 0 filas — los pesos nunca se hubieran actualizado, y
      `/api/top-pick` habría devuelto 400 siempre.
      Fix: se agregaron `toEngineStrategyName()`/`toD1StrategyId()` en `src/worker.js`
      (aplicadas en `runPipeline()` al armar `current_weights`/`total_cycles` y al
      escribir `strategy_stats`/`strategies`, y en `/api/top-pick` antes de llamar al
      motor) y `_to_d1_strategy_id()` en `engine/pipeline/sync_d1.py` (aplicada en
      `sync_strategy_stats()`/`sync_strategy_weights()`, mismo bug en la ruta manual).
      No se tocó `register.py` ni el schema — el sufijo en sí es correcto y necesario,
      el bug era que nadie lo traducía de vuelta.
- [x] **Bug fix (`fetch_draw.py` fuentes no conscientes del juego)**:
      `_from_powerball_web()` y `_from_musl_api()` son fallbacks 3º/4º (tras
      `ny_data_api` y `nc_csv`, que sí son game-aware) pero estaban hardcodeadas a
      Powerball — si se llegaran a usar para otro juego, habrían devuelto datos reales
      de Powerball etiquetados como si fueran de ese otro juego. Ahora ambas reciben
      `game_id` y devuelven `None` de entrada si no es `'powerball'`, en vez de datos
      incorrectos. No se implementó scraping nuevo para Mega Millions (sería una
      feature nueva, no un bug fix).
- [x] Verificado: `node --check` en `worker.js`, `py_compile` en `sync_d1.py` y
      `fetch_draw.py`. Test funcional con mocks simulando un ciclo completo de
      `mega_millions` vía `scheduled()`: confirmado que `current_weights`/`total_cycles`
      leen el peso real (0.85, no el default 1.0) y que la escritura final
      (`strategy_stats` + `UPDATE strategies`) apunta al id sufijado correcto
      (`frequency_weighted_mega_millions`). Test separado para `/api/top-pick`:
      confirmado que el motor recibe el nombre plano y la respuesta al frontend
      mantiene el id de D1. Confirmado round-trip de los helpers para las 8
      estrategias en ambos juegos, y que powerball (sin sufijo) sigue idéntico
      (las funciones son identidad cuando `gameId === 'powerball'`).

## Hecho (2026-07-05, sesión 9 — Fase 6: end-to-end 100% local, Worker+D1+Container)

- [x] **Bloqueo de entorno descubierto**: Wrangler no soporta desarrollo local con
      Containers en Windows nativo (`enable_containers`/Docker Desktop en Windows no
      alcanza) — el propio wrangler lo dice explícito: *"Local development with
      containers is currently not supported on Windows. You should use WSL instead."*
      Se resolvió corriendo `wrangler dev` desde **WSL2 (Ubuntu-22.04)**, con el repo
      accedido vía `/mnt/c/...` (mismo filesystem, sin copiar nada). Docker Desktop
      ya tenía WSL2 instalado pero **sin la integración habilitada** para esa distro
      (`Settings → Resources → WSL Integration`) — Orlando la activó a mano (no hay
      equivalente por CLI en esta versión de Docker Desktop).
- [x] **Bug de entorno (no de código) — red rota dentro de contenedores tras habilitar
      la integración WSL**: el primer intento de build se quedó colgado ~20 minutos en
      `pip install` sin avisar error ni progresar (0 bytes/seg de red, proceso `curl`
      de prueba en estado `D` — bloqueado en el kernel). Diagnóstico: activar la
      integración Docker Desktop↔WSL en caliente dejó el networking de la VM en un
      estado roto (problema conocido de Docker Desktop+WSL2). Fix: `wsl --shutdown`
      (reinicia toda la VM WSL2) + reabrir Docker Desktop → confirmado con
      `curl https://pypi.org` (200 OK) y un `docker run` de prueba antes de reintentar
      el build real. **Nota para el futuro**: si un `pip install`/`npm install` dentro
      de un contenedor en WSL se cuelga sin error visible, sospechar primero de la red
      (revisar `ps aux` por procesos en estado `D`), no de recursos (CPU/RAM no eran
      el problema — WSL2 ya tenía las 16 CPUs y ~7GB libres del host).
- [x] **Segundo hallazgo (gotcha de workflow, no bug de código) — mojibake de UTF-8
      al cargar el schema local desde Windows**: `npx wrangler d1 execute --local
      --file=schema/d1_schema.sql` corrido desde **Git Bash de Windows** dejó las
      descripciones de estrategias con acentos corrompidos (`histÃ³rica` en vez de
      `histórica`) en el SQLite local (`.wrangler/state`, compartido por path con
      WSL). El archivo fuente en disco está bien codificado (UTF-8 real, confirmado
      con `file`/inspección de bytes) — la corrupción la introduce wrangler/la consola
      de Windows al leerlo. Confirmado que el D1 **remoto** nunca tuvo este problema
      (las mismas estrategias se ven bien vía la API en producción). Fix: recargar el
      schema local (`wrangler d1 execute --local --file=...`) **desde dentro de WSL**,
      no desde Windows — el mismo comando ahí produjo texto correcto. **Regla nueva**:
      cualquier comando que escriba texto con acentos al D1 local debe correrse desde
      el mismo entorno (WSL) donde corre `wrangler dev`, nunca mezclar Windows/WSL para
      escribir, solo para lectura vale cualquiera.
- [x] Verificado con Docker Desktop + WSL2 reales (primera vez, nunca antes probado):
      - `npm install` (dentro de WSL, node_modules con binarios Linux — necesario,
        los de Windows no sirven para correr `wrangler dev` en WSL) reemplazó
        cualquier shim de `@cloudflare/containers`; confirmado `@cloudflare/containers`
        real v0.2.4 instalado, no un mock.
      - Schema cargado en D1 local (`schema/d1_schema.sql`), 8 estrategias seed.
      - `wrangler dev --local --persist-to .wrangler/state --port 8788` levanta
        Worker + D1 local + Container juntos. El build de `engine/Dockerfile` corrió
        limpio una vez arreglada la red: base image `python:3.11-slim`, `pip install`
        de todo `requirements.txt` (numpy/pandas/xgboost/scikit-learn/fastapi/uvicorn
        incluidos) en 76s, imagen final exportada y arrancada sin errores de sintaxis
        ni de import.
      - `GET /`, `/styles.css`, `/app.js` → 200 OK (Workers Static Assets sirviendo
        `public/` correctamente). Título confirmado (`SHIOL+ · Strategy Analytics`)
        y JSON de `/api/games`/`/api/strategies` con las 8 estrategias.
      - `GET /api/top-pick?game=powerball` → llama al Container real (no mock):
        primera llamada 2052ms (cold start del container, con un mensaje benigno
        `Could not bind egress listener... falling back to loopback` — no bloqueante,
        el propio wrangler lo resuelve solo) devolviendo un ticket generado real;
        segunda llamada con el container ya caliente, 296ms.
      - Draw de prueba insertado en D1 local; **cron simulado disparado** con
        `curl "http://localhost:8788/cdn-cgi/handler/scheduled?cron=0+5+*+*+TUE"` →
        200 OK. Log confirma el flujo completo real: `[cron] fired` → `[pipeline]
        powerball draw=2026-07-04` (trajo el draw real desde internet, no el de
        prueba insertado a mano, porque el pipeline busca el draw pendiente más
        reciente) → `8 strategies evaluated (via engine container)` → `[cron] done`.
        Confirmado en D1 local: `cycles` (1 fila, status=evaluated), `strategy_stats`
        (8 filas con ROI real), `strategies` (pesos bajaron de 1.0 a 0.90/0.91,
        `total_cycles=1` en las 8) — el binding nativo de D1 escribió todo, sin pasar
        por `sync_d1.py` (confirma el diseño de Fase 3 del ADR).
      - **NO se corrió `wrangler deploy` en ningún momento** — confirmado revisando
        el historial de comandos de la sesión.
- [x] **Cerrado por decisión (2026-07-05, sesión 11)**: la revisión visual real en
      navegador (hero/countdown en vivo/sparklines/Hall of Wins) quedó sin hacerse en
      la sesión 9 — solo se había confirmado por texto (`curl`, status codes, JSON)
      que el HTML/CSS/JS se sirven bien. Orlando decidió cerrar la Fase 6 sin ese
      chequeo adicional (la validación funcional real vía `/api/top-pick` + cron
      completo ya cubre la parte que importa: que el Container y D1 local funcionan
      de punta a punta). Si aparece algo visualmente raro en producción después del
      deploy, revisar primero countdown/sparklines ya que es la única parte nunca
      vista en un browser real.
- [x] **Efecto secundario esperado, ya resuelto**: al terminar las pruebas, se
      reinstaló `node_modules` desde Windows (`rm -rf node_modules && npm install`)
      para dejarlo listo para un futuro `wrangler deploy` real desde Windows — esto
      rompió la sesión de `wrangler dev` que seguía corriendo en WSL (mismo
      `node_modules` compartido por path, pero necesita binarios nativos distintos
      por SO: `workerd-linux-64` vs el de Windows). Es exactamente el mismo problema
      que ya advertía el gotcha "Deploy solo funciona desde terminal real de Windows"
      de abajo, ahora confirmado también entre Windows↔WSL (antes solo se sabía
      Windows↔sandbox Linux). **Regla operativa**: no correr `npm install` en un SO
      mientras `wrangler dev` sigue vivo en el otro — parar el dev server primero.

## Hecho (2026-07-05, sesión 10 — reducir tamaño de la imagen del Container)

- [x] **Motivo**: la imagen `enginecontainer` pesaba 1.83GB (confirmado con Docker
      Desktop: la capa `RUN pip install -r requirements.txt` sola pesa 1.08GB, 59%
      del total) — inviable de subir en cada deploy con conexión doméstica limitada.
      Auditoría previa (misma sesión, antes de este cambio) cruzó los imports reales
      de `engine/server.py` (el único entrypoint que corre en producción) contra
      `requirements.txt` y midió tamaño real por paquete instalado (`du -sh` dentro
      del container, no el tamaño del wheel descargado).
- [x] **`loguru` eliminado de `requirements.txt`** — cero referencias en todo
      `engine/` (confirmado con grep), paquete chico pero 100% muerto.
- [x] **Hallazgo corregido a mitad de la auditoría, con una prueba real**: se creyó
      inicialmente que `scikit-learn` (50MB) + `joblib` (2.6MB, dependencia exclusiva
      de sklearn) también estaban muertos porque ningún archivo de `engine/` hace
      `import sklearn`. Al sacarlos y probar en un container descartable,
      `XGBClassifier(...)` falló con `ImportError: sklearn needs to be installed in
      order to use this module` — la API sklearn-compatible de `xgboost`
      (`XGBClassifier`, la clase que usa `xgboost_ml.py`) exige `scikit-learn`
      internamente, sin que el código del proyecto lo importe nunca directo. Se
      revirtió: `scikit-learn` se queda en `requirements.txt`. **Lección**: un grep
      de imports directos no alcanza para auditar dependencias de paquetes con APIs
      compatibles/wrappers de otros paquetes — hace falta probar la instalación real.
- [x] **`nvidia-nccl-cu12` eliminado — el ahorro grande (~400MB, ~22% de la imagen
      original)**: es una dependencia transitiva que el paquete `xgboost` de PyPI
      declara siempre (soporte multi-GPU/distribuido vía NCCL), independiente de si
      el código la usa. Este proyecto entrena `XGBClassifier` 100% CPU, sin ningún
      flag de GPU. En vez de pelear con el resolver de pip (no se puede excluir una
      dependencia transitiva declarada solo con `requirements.txt`), se borra el
      paquete después de instalar, **en la misma capa** (`RUN pip install ... && rm
      -rf .../site-packages/nvidia*` en un solo `RUN`) — necesario porque si el
      borrado va en un `RUN` separado, Docker no reduce el tamaño final de la
      imagen, solo oculta los archivos en una capa nueva mientras la capa anterior
      (con el peso completo) sigue existiendo.
      Verificado exhaustivamente antes de tocar el Dockerfile real (primero en un
      container descartable con `docker run --rm ... rm -rf .../nvidia*`, después
      con el Dockerfile ya modificado): `XGBClassifier` entrena y predice bien sin
      el paquete; `engine.server` importa sin error; y las **8 estrategias**
      (incluidas `xgboost_ml` y `hybrid_ensemble`, las dos que realmente entrenan
      XGBoost) corren `generate()` end-to-end con datos falsos y devuelven
      `confidence: 0.82`/`0.87` (no el `0.50` del fallback aleatorio, que hubiera
      indicado que el entrenamiento falló silenciosamente).
- [x] **Resultado medido**: imagen final **1.1GB** (antes 1.83GB) — **-730MB, -40%**.
      Imagen de prueba (`shiolplus-engine-test`) borrada tras confirmar.
- [ ] **Pendiente, no evaluado en esta sesión**: `scipy` (143MB) sigue en la imagen
      porque lo requieren tanto `xgboost` como `scikit-learn` — no hay forma simple
      de sacarlo sin sacar a alguno de los dos. `requests`/`beautifulsoup4`/
      `python-dotenv` (usados solo por `register.py`/`fetch_draw.py`/`sync_d1.py`,
      herramientas de CLI manual que `server.py` nunca importa) no se tocaron —
      pesan poco individualmente y sacarlos implicaría decidir si esos 3 archivos
      dejan de copiarse a la imagen del Container o no (cambio de alcance mayor,
      no solo de tamaño). No evaluado: comprimir vía multi-stage build (impacto
      esperado bajo, ya se usa `--no-cache-dir`) ni cambiar de base image (Alpine
      descartado — forzaría compilar numpy/scipy/xgboost desde source, sin wheels
      manylinux precompilados).

## Hecho (2026-07-05, sesión 11 — Fase 7: deploy real a producción)

- [x] **Checklist pre-deploy, todo verificado antes de tocar nada**: `docker info`
      respondió sano (0 containers, 2 imágenes — coincide con lo dejado en la Fase 6).
      Se detuvo primero el `wrangler dev` que seguía corriendo en WSL2 de la sesión
      anterior (mataron los PIDs de `wrangler`/`node`/`workerd` explícitos — el kill
      con `awk` genérico falló por el warning de `screen size bogus` de WSL
      colándose como PID; hubo que listar y matar PIDs uno por uno). Se reinstaló
      `node_modules` desde **Windows nativo** (`rm -rf node_modules && npm install`)
      para tener los binarios correctos del SO antes del deploy. `npx wrangler whoami`
      confirmó sesión OAuth válida (cuenta `Orlando Dev Account`) con el scope
      `containers (write)` presente — crítico para este deploy en particular.
      `wrangler.toml` revisado completo una vez más (containers, durable_objects,
      migrations, d1_databases, assets, triggers) — sin cambios respecto a lo ya
      validado en fases anteriores. Confirmado `export { EngineContainer }` presente
      en `src/worker.js` (requisito de Wrangler para resolver el binding del Durable
      Object).
- [x] **Confirmada la hipótesis del checklist**: `wrangler deploy` **sí funcionó
      desde Windows nativo sin necesidad de WSL2** — la restricción de la Fase 6
      ("no soportado en Windows") es específica del proxy de runtime en vivo de
      `wrangler dev`, no aplica al flujo de `deploy` (build de imagen + push al
      registry + deploy del Worker). No hizo falta el plan B de WSL2 para esta fase.
- [x] **Deploy ejecutado y exitoso**: `npx wrangler deploy` — 3 assets subidos
      (`index.html`, `styles.css`, `app.js`), Worker deployado con los bindings
      correctos (`env.ENGINE` Durable Object, `env.DB` D1, `env.ASSETS`), imagen del
      Container construida (`shiol-plus-enginecontainer`, con la reducción de tamaño
      de la sesión 10 ya aplicada — 1.1GB, no 1.83GB) y pusheada al registro de
      Cloudflare (`registry.cloudflare.com/.../shiol-plus-enginecontainer`).
      Aplicación de Container creada: `shiol-plus-enginecontainer`
      (Application ID `a03cfd96-a494-4a00-a00e-86a5832e9678`). Los 6 cron triggers
      se registraron sin error (ya se sabía que el formato `SUN/TUE/THU` era correcto
      desde el fix de 2026-07-04). Versión activa:
      `988b07a2-00c8-4d8b-af9f-0bfd6babe62f`.
      Dato para Orlando (preocupado por su ancho de banda): el push mostró una capa
      reusada (`Layer already exists`, probablemente la base `python:3.11-slim` ya
      cacheada en el registry de Cloudflare de otro build) y Docker comprime cada
      capa al pushear — el tráfico real subido fue menor al tamaño descomprimido
      de 1.1GB de la imagen, aunque no se capturó el número exacto de bytes.
- [x] **Aprovisionamiento del Container**: `npx wrangler containers list` mostró
      `state: provisioning` inmediatamente después del deploy (esperado, documentado
      por Cloudflare). Tras ~90 segundos de espera, pasó a `state: ready`,
      `LIVE INSTANCES: 1`.
- [x] **Verificación POST-deploy contra producción real** (no local):
      - `GET /api/health` → 200, `{"status":"ok","version":"v9",...}`.
      - `GET /` → 200, `<title>SHIOL+ · Strategy Analytics</title>` — Workers Static
        Assets sirviendo bien, sin regresión de la Fase 4.
      - `GET /api/top-pick?game=powerball` → 200, **llamó al Container real en
        producción** (no un mock): devolvió `xgboost_ml` con `weight: 0.82262`
        (coincide con los pesos reales ya acumulados en D1 de sesiones anteriores,
        confirmando que el Container leyó el estado real, no datos de prueba) y un
        ticket generado. Cold start real de producción: **~20 segundos** (vs ~2s que
        se veía en Docker local — esperable, documentado por Cloudflare como más
        lento que el Container local en la primera invocación tras aprovisionar).
- [x] **Confirmado en el dashboard de Cloudflare** (navegador, `Workers & Pages →
      shiol-plus → Settings → Trigger Events`): los 6 cron triggers aparecen
      correctamente configurados con sus próximas fechas de ejecución (ej. `Next:
      Tue, 07 Jul 2026 05:00:00`).
- [ ] **Pendiente explícito — punto 12 del checklist no se pudo completar tal cual
      se pidió**: se investigó si el dashboard de Cloudflare permite disparar
      manualmente un Cron Trigger en un Worker ya desplegado — **no existe tal
      botón**, confirmado contra la documentación oficial de Cloudflare. El
      dashboard solo ofrece "View events" (historial de las últimas 100
      invocaciones) y edición/borrado del cron; el endpoint de prueba
      `/cdn-cgi/handler/scheduled` **solo existe en `wrangler dev` local** (ya usado
      en la Fase 6), no tiene equivalente para Workers en producción. **No hay forma
      de confirmar el pipeline completo (cron real → fetch draw → Container →
      D1) contra producción hasta que dispare un cron real** — el próximo es martes
      2026-07-07 a las 05:00 UTC (evalúa el sorteo del lunes). Se dejó `npx wrangler
      tail shiol-plus` corriendo para poder capturar ese log cuando llegue (nota:
      `wrangler tail` expira a las 3 horas por defecto — hay que relanzarlo cerca
      del horario real si la sesión se cierra antes).
- [x] Ningún `wrangler rollback` fue necesario — no se detectó ningún problema que
      lo ameritara.

## Hecho (2026-07-05, sesión 12 — activación de Mega Millions)

- [x] **Bug bloqueante 1, encontrado y arreglado**: `_from_ny_data()` en
      `fetch_draw.py` asumía que `winning_numbers` del dataset de Socrata
      siempre trae los 6 números juntos ('n1 n2 n3 n4 n5 extra'), formato
      real de Powerball (`d6yy-54nr`). Probado en vivo contra el dataset
      real de Mega Millions (`5xaw-6ayf`, consistente desde 2002 hasta hoy):
      `winning_numbers` ahí solo trae las 5 blancas, la Mega Ball viene en
      un campo separado (`mega_ball`). Sin este fix, `fetch_draw()` hubiera
      devuelto `None` para siempre con Mega Millions. Fix: nuevo campo de
      config por juego `ny_extra_ball_field` (`None` para Powerball,
      `'mega_ball'` para Mega Millions) en `engine/games/*.py`, y
      `_from_ny_data()` ahora recibe ese campo y arma el draw según
      corresponda. Verificado contra la API real para ambos juegos, sin
      regresión en Powerball.
- [x] **Bug bloqueante 2, encontrado y arreglado**: `cmd_backfill()` en
      `register.py` seguía pegándole directo a `nc_csv_url` — el mismo
      endpoint que ya sabíamos 404 desde el 2026-07-04, pero el fix a
      `ny_data_api` nunca se aplicó acá (solo en `fetch_draw.py`/
      `worker.js`). Confirmado el 404 en vivo para ambos juegos — correr
      el backfill de Mega Millions tal como estaba hubiera fallado al
      toque. Fix: `cmd_backfill()` ahora hace un fetch bulk a `ny_data_api`
      (un solo request con `$limit=5000`, sin paginar — confirmado que
      Socrata devuelve el dataset completo así) y parsea con la misma
      lógica game-aware de `ny_extra_ball_field`.
- [x] **Rango de backfill elegido con datos reales, no a ojo**: Mega
      Millions cambió de reglas varias veces en su historia. Se descargó
      el dataset completo (2516 filas, 2002-2026) y se validó cada fila
      contra el rango actual del juego (blancas 1-70, Mega Ball 1-25):
      desde 2017-10-31 en adelante, las 906 filas caen 100% dentro de
      rango; antes de esa fecha, 682 de 2516 (27%) quedan fuera (blancas
      hasta 75, de una era con reglas distintas). Se eligió
      `--from 2017-10-31` para no meter datos estructuralmente inválidos
      bajo las reglas de hoy.
- [x] **Hallazgo de paso, revisado y confirmado que NO es un bug**: el
      histórico de Powerball ya en producción (2351 draws desde
      2006-05-31) tiene 173 filas (2006-2015) con el número Powerball
      fuera del rango actual (esa bola bajó de 1-35 a 1-26 en 2015).
      Revisadas las 3 estrategias que usan ese campo
      (`frequency_weighted`, `intelligent_scoring`, `xgboost_ml`): las 3
      ya filtran `pb` dentro de `[1, extra_max]` antes de contar
      frecuencias — los valores viejos se ignoran solos, correctamente.
      No se tocó nada acá.
- [x] `engine/games/mega_millions.py`: `active` cambiado de `False` a
      `True`.
- [x] Verificado todo con mocks (sin tocar D1 real -- este sandbox no tiene
      `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID` en `.env`, solo
      `D1_DATABASE_ID`): `_from_ny_data()` probado contra la API real para
      ambos juegos; `cmd_backfill()` corrido contra la API real con `d1()`
      mockeado — confirmó exactamente 906 filas para Mega Millions desde
      2017-10-31 (coincide con el análisis manual) y 15 filas recientes
      para Powerball sin regresión, todas dentro de rango; `cmd_register()`
      corrido con `d1()` mockeado — confirmó `active=1` propagado
      correctamente y las 8 estrategias seeded con el id sufijado
      `_mega_millions` (exactamente lo que el fix de Fase 5 en
      `worker.js`/`sync_d1.py` ya espera).
- [ ] **Pendiente — ejecutar contra D1 real** (requiere el `.env` con
      credenciales reales, solo existe en la máquina de Orlando):
      ```
      python -m engine.games register mega_millions
      python -m engine.games backfill mega_millions --from 2017-10-31
      ```
      Después de correr esto, Mega Millions va a aparecer activo en
      `/api/games` y el cron ya lo va a recoger solo (`scheduled()` ya
      recorre todos los juegos activos genéricamente, no hace falta tocar
      `wrangler.toml`). Timing esperado: el sorteo del martes recién se
      detecta con el cron del jueves (~30h de atraso, decisión de Orlando
      de no agregar triggers nuevos mié/sáb — aceptado explícitamente,
      simplicidad sobre timing ajustado).
- [x] **Bug bloqueante real, encontrado por auditoría externa (no por mi
      propia verificación) — corregido en el momento**: la verificación de
      esta sesión probó `_from_ny_data()` en Python con mocks/API real,
      pero nunca revisó si `src/worker.js` (el que el cron real de
      producción usa de verdad) tenía su propia implementación. La tiene:
      `fetchDrawFromNyData()` en `worker.js` es una función JS
      independiente que nunca comparte código con
      `engine/pipeline/fetch_draw.py` -- son dos lenguajes, dos
      implementaciones. Tenía exactamente el mismo bug sin arreglar
      (`nums.length !== 6` siempre falso para Mega Millions). Consecuencia
      real si no se corregía: Mega Millions hubiera aparecido activo en
      `/api/games` y el frontend, pero el cron real nunca lo hubiera
      evaluado -- `runPipeline()` reporta `draw_not_available` sin ninguna
      excepción ni error visible en logs, así que nadie se hubiera
      enterado hasta notar que nunca aparecen ciclos nuevos para ese
      juego. Fix aplicado: mismo patrón que en Python -- `ny_extra_ball_field`
      agregado a `GAME_CONFIGS` (`null` powerball, `'mega_ball'` mega
      millions) y `fetchDrawFromNyData()` actualizada para leer el campo
      separado cuando corresponde. Verificado con `node --check` y contra
      la API real (mismos valores que confirmó el lado Python: Powerball
      2026-07-04 pb=20, Mega Millions 2026-07-03 mega_ball=16).
      **Lección para la próxima activación de juego**: verificar SIEMPRE
      los dos lados (Python y JS) cuando el fix toca lógica de fetch de
      datos -- son implementaciones separadas a propósito (ver ADR-0001,
      "fetchDrawFromNyData(), fetchDrawFromCSV(), lastDrawDate() ... nunca
      fueron parte del motor") y no hay ningún mecanismo que avise si una
      se arregla y la otra no.

## Hecho (2026-07-05, sesión 13 — consolidar fetch-draw: cerrar la duplicación JS/Python de raíz)

- [x] **Contexto**: una auditoría externa, a raíz del bug de `fetchDrawFromNyData()`
      arreglado en la sesión 12, encontró que el proyecto tenía **cuatro
      implementaciones paralelas** de "traer/parsear un sorteo desde una fuente
      externa": (1) `engine/pipeline/fetch_draw.py::fetch_draw()` (Python,
      single-date, usado por el CLI `run.py`), (2) `worker.js::fetchDrawFromNyData()`/
      `fetchDrawFromCSV()` (JS, single-date, el que usa el cron real de producción),
      (3) `worker.js`'s `/api/admin/backfill` (JS, bulk/rango, roto — usaba el CSV de
      NC Lottery 404 desde 2026-07-04, sin uso real conocido), (4)
      `engine/games/register.py::cmd_backfill()` (Python, bulk/rango, CLI, la única
      correcta y mantenida). Orlando pidió explícitamente no parchear solo el bug
      puntual: *"no quiero dejar cosas sueltas que después aparezcan en JS y no en
      Python... ayudame a tomar una decisión lógica y mantener siempre el proyecto
      organizado y limpio."*
- [x] **Decisión**: mover el fetch *single-date* (el que corre en el cron real) al
      motor Python, expuesto al Worker vía el Container — mismo patrón que ya se usa
      para `runEngineCycle()`/`generateEngineTickets()` desde la Fase 3 del ADR-0001.
      El backfill masivo (operación manual/rara, se corre una vez al activar un juego
      nuevo) se queda **solo** en el CLI de Python — no necesita vivir en el Container.
- [x] **`engine/server.py`**: nuevo endpoint `POST /fetch-draw` — recibe
      `{game_id, draw_date}`, llama a `fetch_draw()` (cero lógica duplicada, es un
      wrapper delgado) y devuelve `{found: false}` (caso normal, sorteo no publicado
      aún) o `{found: true, draw: {..., extra, source}}`. Módulo docstring actualizado
      para documentar esta excepción intencional a "sin red externa".
- [x] **`src/container.js`**: nuevo `fetchDrawFromEngine(env, payload)`, mismo patrón
      que `runEngineCycle()`/`generateEngineTickets()` — POST a `http://engine/fetch-draw`
      dentro del Container.
- [x] **`src/worker.js`**: borradas `fetchDrawFromNyData()` y `fetchDrawFromCSV()`
      completas (eran las únicas responsables del bug de la sesión 12). El paso 2 de
      `runPipeline()` ahora llama a `fetchDrawFromEngine()` y traduce `extra → pb`
      para el resto del pipeline (`draw = {...result.draw, pb: result.draw.extra}`).
      Borrado también el endpoint `/api/admin/backfill` completo (era la tercera copia
      de esta lógica, y estaba roto). `GAME_CONFIGS` recortado a solo `{id, draw_days}`
      por juego — todos los campos de fetch (`ny_dataset_id`, `ny_extra_ball_field`,
      `nc_csv_url`, `nc_csv_cols`) quedaron muertos tras el borrado y se eliminaron
      para no dejar una segunda copia inerte de esa config (ya vive en
      `engine/games/*.py`, la única fuente de verdad).
- [x] **Verificado**:
      - `engine/server.py` vía `TestClient` real contra la API externa real (sin
        mocks): Powerball 2026-07-04 → `extra: 20`; Mega Millions 2026-07-03 →
        `extra: 16` (mismos valores que ya había confirmado el fix de la sesión 12);
        fecha sin sorteo → `{found: false}`, 200 (no error); `game_id` inexistente →
        400 con mensaje claro.
      - Paso 2 de `runPipeline()` reproducido como unit test aislado en Node: confirma
        que `draw.pb` se propaga bien a los pasos 3 (insert en `draws`) y 7 (payload al
        Container), y que `found: false` deja `draw = null` (mismo comportamiento
        `skipped: draw_not_available` que antes).
      - `node --check` en `worker.js`/`container.js`, `py_compile` en `server.py`.
      - Grep de limpieza en todo el repo: cero referencias reales a
        `fetchDrawFromNyData`/`fetchDrawFromCSV`/`/api/admin/backfill` fuera de
        comentarios históricos explicativos; `wrangler.toml` no las menciona.
- [x] **Regla nueva del proyecto** (agregada a `docs/adr/0001-...md` como adenda, y
      aplicada de acá en adelante): ninguna lógica de fetch/parseo de datos de
      lotería por-juego vive en `worker.js`. Vive en `engine/`, expuesta al Worker vía
      el Container cuando hace falta en producción, o vía CLI cuando es una operación
      manual/rara. Extiende la misma lógica que ya regía para las estrategias (punto 1
      de la Decisión del ADR) a cualquier lógica de negocio por-juego.
- [x] **Pendiente para el próximo deploy**: este cambio modifica el comportamiento del
      cron real (ahora el fetch de cada sorteo despierta al Container, no solo el
      `run-cycle` posterior) — falta un `wrangler deploy` para que llegue a
      producción. Aceptado el trade-off de cold-start extra (~20s medido en la sesión
      11) en cada disparo de cron, incluso los que no encuentran sorteo todavía —
      volumen de cron de este proyecto (6-12/semana) lo hace intrascendente en costo.

## Hecho (2026-07-05, sesión 14 — auditoría: register.py sin modo local + fix)

- [x] **Hallazgo crítico del auditor, antes de correr nada contra D1**: al ir a
      ejecutar `python -m engine.games register mega_millions` +
      `backfill --from 2017-10-31` (pendientes de la sesión 12), el auditor
      notó que `d1()` en `register.py` **no tiene modo local** — pega
      siempre directo a la API REST de D1 de **producción** con las
      credenciales reales de `.env`, sin flag `--local` ni ambiente de
      prueba. Correr esos comandos tal cual los había dejado yo hubiera
      activado Mega Millions **en producción, en caliente**. Agravante: la
      consolidación de fetch-draw de la sesión 13 (mover el fetch al
      Container) todavía no estaba desplegada (`wrangler deploy` pendiente)
      — si Mega Millions se activaba en D1 de producción antes de ese
      deploy, el cron real lo hubiera recogido como activo pero seguiría
      corriendo el código viejo hasta el próximo deploy: **"activo pero
      roto"** en producción, con las mismas señales silenciosas del bug
      original (sin excepción, sin error visible).
- [x] **Corregido antes de tocar producción**: se sembró Mega Millions
      (register + backfill de los 906 sorteos reales desde 2017-10-31)
      contra **D1 LOCAL** (el SQLite que simula `wrangler dev --local`),
      no contra producción. Producción sigue intacta, solo con Powerball
      activo. El seed local sirvió además como QA manual real: confirmado
      en `http://localhost:8788` con `wrangler dev` corriendo (sin
      reiniciar el server, mismo archivo SQLite) — `/api/games` con ambos
      juegos `active:1`, `/api/strategies?game=mega_millions` con las 8
      estrategias sufijadas, `/api/draws?game=mega_millions` con los 906
      sorteos reales, `/api/top-pick?game=mega_millions` generando un
      ticket real con blancas 1-70 + Mega Ball 1-25 (el Container ya sabe
      manejar el juego nuevo sin cambios de código).
- [x] **Gotcha de shell descubierto durante el seed local**: pasar SQL con
      valores a `wrangler d1 execute --local --command "..."` a través de
      Windows→WSL sufría una doble expansión de shell (la variable `$f` de
      un loop se perdía/vaciaba en el shell externo de Windows antes de
      llegar a WSL). Se resolvió evitando variables de shell — listar los
      comandos explícitos en vez de iterar — pero quedó claro que
      `--command` es frágil para este flujo. Fix permanente (ver abajo):
      `d1_local()` ahora usa `--file=<temp.sql>` en vez de `--command`,
      evitando por completo el problema de escaping entre shells.
- [x] **Fix permanente aplicado a `register.py`** (no solo un workaround de
      una vez): nuevo helper `d1_local()` + `_sql_literal()` — arma un
      archivo `.sql` temporal con los valores ya interpolados (escapados
      correctamente: comillas simples dobladas, `NULL` real para `None`) y
      lo ejecuta con `npx wrangler d1 execute shiol-plus-db --local
      --file=...`. No requiere credenciales de Cloudflare (D1 local no usa
      la API en absoluto) — solo requiere `node`/`wrangler` y correrse desde
      la raíz del repo. Nuevo flag `--local` en los subcomandos `register` y
      `backfill`; ambos comandos ahora imprimen explícito el destino
      (`💻 LOCAL` o `⚠️ PRODUCCIÓN`) antes de escribir, para que sea
      imposible confundir contra cuál D1 se está corriendo. Verificado con
      un test aislado de `_sql_literal()`/interpolación (comillas, `NULL`,
      números) y de `argparse` (`--local` default `False`, explícito
      `True`) — sin ejecutar `wrangler` real (este sandbox no lo tiene
      instalado); la ejecución end-to-end del flag queda para probarse en
      la máquina de Orlando la próxima vez que se use.
- [x] **Orden de pasos corregido** (quedaba invertido en la sesión 12/13):
      el orden correcto para activar un juego nuevo en producción, de acá en
      adelante, es (1) desplegar primero cualquier código relacionado
      pendiente (`wrangler deploy` — en este caso, la consolidación de
      fetch-draw de la sesión 13), y recién (2) correr `register`/`backfill`
      contra D1 de producción. Así un juego nunca queda "activo" en
      producción antes de que el código que lo soporta esté ahí.

## Hecho (2026-07-05, sesión 15 — Home multi-juego + dashboard por juego)

- [x] **Motivo**: con Mega Millions por activarse, el QA manual local de la
      sesión 14 mostró el problema de raíz — `public/index.html` era un
      dashboard único hardcodeado a `GAME = 'powerball'` (variable fija en
      `app.js`), sin ninguna forma de ver Mega Millions desde el frontend
      aunque la API ya soportara `?game=` en casi todos los endpoints.
- [x] **`public/index.html` reescrito como Home**: grid de cards, una por
      juego devuelto por `/api/games` (activos e inactivos). Cada card activa
      muestra: estrategia líder + su peso (`/api/strategies?game=`), total
      ganado (`/api/wins?game=`), cantidad de estrategias, y un link
      "View details →" a `game.html?game=<id>`. Los juegos inactivos
      (`active:0`) se muestran atenuados con badge "coming soon", sin
      pedir stats (evita requests innecesarios/errores para un juego que
      todavía no tiene datos).
- [x] **`public/game.html` + `public/game.js` (nuevos)**: es el dashboard
      completo que antes vivía en `index.html`/`app.js` (countdown, top pick,
      último sorteo, ranking de estrategias, último ciclo, hall of wins),
      movido tal cual pero parametrizado — `GAME` ahora se lee de
      `?game=` en la URL (`new URLSearchParams(location.search)`, fallback a
      `'powerball'`), en vez de estar fijo. Se agregó `renderGameIdentity()`:
      pone el `<title>` de la página, el nombre del juego junto al logo, y el
      texto del footer dinámicamente (antes decían "Powerball" fijo). Link
      "← Home" arriba para volver al selector.
- [x] **`public/app.js` borrado** — reemplazado por `game.js` (dashboard) +
      `home.js` (selector); cero lógica duplicada entre los dos, cada uno
      tiene un rol distinto. Confirmado con grep que no queda ninguna
      referencia real a `app.js` en el repo (solo menciones históricas en
      este mismo `TODO.md`, de sesiones previas).
- [x] **Fix real en `worker.js`, necesario para que el Home tenga sentido**:
      `/api/wins` no filtraba por juego (`SELECT * FROM wins ...` sin
      `WHERE lottery_id`) — con un solo juego activo nunca se notó, pero con
      dos juegos el Hall of Wins habría mezclado premios de Powerball y Mega
      Millions sin distinguirlos. Ahora acepta `?game=` opcional (sin él,
      se comporta igual que antes — compatibilidad hacia atrás) y filtra por
      `lottery_id` (la columna ya existía en el schema, solo faltaba usarla).
- [x] **`public/styles.css`**: nuevas clases para el grid de cards del Home
      (`.games-grid`, `.game-card`, `.game-card-stats`, etc.) y para el header
      de `game.html` (`.logo-group`, `.back-link`, `.nav-tagline`) —
      reutilizan las mismas variables de color/sombra/radius que el resto del
      sitio, sin introducir un sistema de diseño nuevo.
- [x] **Verificado**:
      - `node --check` en `worker.js`, `game.js`, `home.js`.
      - `home.js` corrido en un contexto `vm` de Node con `/api/games`,
        `/api/strategies`, `/api/wins` mockeados (incluyendo un tercer juego
        inactivo ficticio para probar el path "coming soon" con un ícono
        genérico de fallback): confirmado que arma los links correctos a
        `game.html?game=<id>` solo para juegos activos, calcula bien el total
        ganado (suma de `prize_amount`), y no genera link para el juego
        inactivo.
      - `game.js` corrido igual en `vm` con `location.search =
        '?game=mega_millions'` mockeado: confirmado que **todas** las
        llamadas a la API (`/api/draws`, `/api/top-pick`, `/api/strategies`,
        `/api/latest-cycle`, `/api/wins`, `/api/history`) usan
        `mega_millions`, que el `<title>`/logo/footer/countdown muestran
        "Mega Millions" dinámicamente (nada hardcodeado a "Powerball"), y que
        `/api/wins?game=mega_millions` confirma el fix del punto anterior
        siendo usado de verdad por el frontend.
      - Grep de limpieza: sin referencias colgantes a `app.js`; `game.html`/
        `index.html` sin links a anchors inexistentes; `wrangler.toml` no
        necesita cambios (`[assets] directory = "./public"` sirve cualquier
        archivo que exista ahí, sin listarlos por nombre).
- [x] **Pendiente para el próximo deploy**: igual que la consolidación de
      fetch-draw de la sesión 13, este cambio de frontend vive solo en el
      repo local hasta el próximo `wrangler deploy` — no afecta el cron ni
      D1, es 100% assets estáticos + un fix chico de `worker.js`.

## Pendiente — Migración a arquitectura Cloudflare-nativa + Container Python (ver ADR-0001)

Fase 1. ✅ **Completa** — ver "Hecho, sesión 5" arriba.
Fase 2. ✅ **Completa** — ver "Hecho, sesión 6" arriba.
Fase 3. ✅ **Completa, incluyendo `/api/top-pick`** — ver "Hecho, sesión 6" y "sesión 7"
   arriba. Ya no queda ninguna lógica de estrategias en JS.
Fase 4. ✅ **Completa** — ver "Hecho, sesión 7" arriba. Se descartó sumar Vite (no
   hace falta para HTML/CSS/JS plano sin build).
Fase 5. ✅ **Completa** — ver "Hecho, sesión 8" arriba. El sufijo de `register.py`
   ahora se traduce correctamente en `worker.js` y `sync_d1.py`, y las fuentes de
   `fetch_draw.py` no conscientes del juego (`_from_powerball_web`, `_from_musl_api`)
   se saltan explícitamente para juegos que no sean powerball.
Fase 6. ✅ **Completa** — ver "Hecho, sesión 9" arriba. Worker + D1 local + Container
   reales probados end-to-end desde WSL2: build de Docker limpio, `/api/top-pick` y
   el cron completo (fetch real → Container → 8 strategy_stats + pesos actualizados
   en D1) verificados funcionando. La revisión visual en navegador (único ítem que
   había quedado sin verificar) se cerró por decisión el 2026-07-05 sin bloquear el
   avance — ver nota en "Hecho, sesión 9". Requiere WSL2 + integración Docker
   Desktop habilitada para desarrollar en Windows de ahora en adelante — ver gotchas
   nuevos arriba antes de repetir esto.
Fase 7. ✅ **Completa** — ver "Hecho, sesión 11" arriba. `wrangler deploy` corrió
   exitosamente desde Windows nativo (se confirmó la hipótesis: la restricción de
   Windows de la Fase 6 era solo del proxy de runtime de `wrangler dev`, no de
   `deploy`). Worker, assets, D1 binding y Container (imagen reducida de la sesión
   10) desplegados; Container pasó de `provisioning` a `ready`. Verificaciones
   POST-deploy contra producción real: `/api/health`, `/`, y `/api/top-pick`
   (Container real respondiendo) — todas OK.
   **Punto 12 cerrado sin esperar al martes**: el cron real `0 9 * * SUN` disparó
   solo el mismo día del deploy (2026-07-05 09:00 UTC) y corrió el pipeline completo
   contra el Container real en producción — confirmado directamente en D1: cycle_id=2
   (draw 2026-07-04, fetch real vía `ny_data_api`), 8 filas de `strategy_stats` con
   `weight_before` de cada estrategia coincidiendo exacto con el `weight_after` del
   ciclo anterior (cadena de pesos continua, sin salto ni incompatibilidad), y
   `strategies.current_weight` actualizado en consecuencia (ej. `xgboost_ml`:
   0.8918 → 0.82262). Confirma que el mismo módulo Python (`engine/pipeline/weights.py`)
   sigue siendo la única fórmula de pesos, sin importar si lo invoca un script
   manual o el Container en producción — no quedó ningún dato generado por la
   lógica JS vieja mezclado en D1 (los cron nunca dispararon con esa lógica antes
   de la migración a Python/Container).
   **Hallazgo menor sin resolver**: `strategies.total_cycles` quedó en 3 para las 8
   estrategias, pero solo hay 2 ciclos reales (`cycles`/`strategy_stats` coinciden
   en 2 cada uno) — desfase de +1 en el contador, cosmético, no afecta
   `current_weight` (ese sí coincide exacto con el último ciclo real). Pendiente de
   investigar el origen del +1 de más si se quiere prolijidad, no es urgente.

## Hecho (2026-07-05, sesión 16 — deploy a producción de sesiones 13 y 15)

- [x] **Auditoría independiente de la consolidación de fetch-draw (sesión 13) y del
      Home multi-juego (sesión 15)** antes de tocar nada: se leyó el código real de
      `engine/server.py` (`/fetch-draw`), `src/container.js` (`fetchDrawFromEngine`),
      `src/worker.js` (`runPipeline`, `GAME_CONFIGS`, `/api/wins`), `public/index.html`,
      `public/home.js`, `public/game.html`, `public/game.js`, sin confiar solo en el
      resumen del implementador. Verificado: `node --check`/`py_compile` limpios,
      `/fetch-draw` probado contra la API real (Powerball sin regresión, Mega
      Millions con datos reales, fecha sin sorteo → `found:false`, juego inválido →
      400), cero referencias colgantes a `fetchDrawFromNyData`/`fetchDrawFromCSV`/
      `/api/admin/backfill`, todos los IDs de `game.html` coinciden con lo que
      `game.js` busca, y las clases CSS nuevas (`game-card`, `games-grid`, etc.)
      existen en `styles.css`. `wins.lottery_id` confirmado en el schema (necesario
      para el fix de `/api/wins?game=`).
- [x] **QA local completo** (WSL2 + Docker, servidor reiniciado limpio) antes de
      tocar producción: Mega Millions activado **solo en D1 local** (registro +
      backfill de 906 sorteos corridos a mano contra `wrangler d1 execute --local`,
      sin usar `register.py` para no arriesgar producción todavía) para poder probar
      el Home con dos juegos reales. Confirmado: `/api/games`, `/api/strategies`,
      `/api/draws`, `/api/top-pick` funcionando para ambos juegos; `game.html` y
      `home.js` sirviendo bien.
- [x] **Deploy real a producción** (`wrangler deploy`, Windows nativo, mismo
      checklist de siempre: Docker Desktop corriendo, `node_modules` reinstalado
      desde Windows, sesión OAuth confirmada). Assets nuevos subidos (`index.html`,
      `game.html`, `game.js`, `home.js`, `styles.css`), Container reconstruido con
      la imagen ya optimizada (1.1GB, sesión 10) + el código de `/fetch-draw`
      (sesión 13), aplicación de Container actualizada (`EDIT
      shiol-plus-enginecontainer`, mismo Application ID de siempre), cron triggers
      re-confirmados. Versión activa: `7f002ddc-3a1e-455d-b0bf-4f4ef5d66edc`.
      Container pasó a `ready` casi de inmediato (más rápido que un aprovisionamiento
      nuevo — era solo un swap de imagen sobre la aplicación ya existente).
- [x] **Verificación POST-deploy contra producción real**: `/api/health` (200),
      `/` (200, Home nuevo, título correcto), `/game.html?game=powerball` (307 →
      `/game?game=powerball`, 200, contenido correcto — confirmado que es
      comportamiento default de Workers Static Assets sirviendo `.html`, no un
      bug), `/api/games` (solo powerball activo, correcto — Mega Millions no se
      activó en producción todavía, a propósito), `/api/wins?game=powerball`
      (`[]`, filtro funcionando), `/api/top-pick?game=powerball` (Container real
      respondió, `xgboost_ml` peso `0.82262` — mismo valor consistente de
      siempre, confirma que el Container leyó el estado real de D1 y no un
      mock). Confirmado también vía `wrangler tail` en vivo durante la
      verificación: todos los requests `Ok`, sin errores.
- [x] **Incidente real durante el deploy, resuelto sin pérdida de datos**: el
      patrón de "esconder `.env` para forzar OAuth" (usado en cada deploy desde
      la Fase 7) tuvo una carrera de condición entre dos comandos en paralelo
      (un `wrangler whoami` de verificación previa terminando de restaurar su
      propio `.env.backup` justo cuando el comando de `deploy` hacía su propio
      `cp .env .env.backup`) — el deploy salió bien, pero al final el `.env` quedó
      con el contenido temporal (sin `CLOUDFLARE_ACCOUNT_ID`/`CLOUDFLARE_API_TOKEN`
      reales) en vez de restaurarse. Detectado de inmediato (el script de
      restauración final tiró `mv: cannot stat '.env.backup'`), diagnosticado, y
      recuperado restaurando el contenido real de `.env` (leído anteriormente en
      esta misma sesión, no adivinado) y confirmado con una query de solo lectura
      real contra D1 de producción (`SELECT id, active FROM lotteries` vía
      `engine.games.register.d1()`) antes de seguir. **Lección**: no correr dos
      comandos que tocan el mismo `.env` en paralelo/consecutivos sin esperar a
      que el primero termine de restaurarlo.
- [x] **Limpieza de Docker post-deploy** (preferencia ya establecida de Orlando):
      se pararon los containers locales de WSL2 que quedaban de la sesión de QA
      (bloqueaban el borrado de su imagen), se borraron las imágenes obsoletas
      (`cloudflare-dev/enginecontainer:79523f0a`/`:635792ad`, builds de prueba
      locales; el tag de producción viejo `988b07a2`, superseded), se sacó el tag
      local redundante (`shiol-plus-enginecontainer:7f002ddc`, mismo contenido que
      el tag del registro), y se vació el build cache. Quedó solo la imagen real
      en uso + el sidecar de Wrangler.
- [x] **Paso (b) completado en la misma sesión**: Orlando pidió activar Mega
      Millions en producción de una. Corridos, contra D1 real (sin `--local`):
      `python -m engine.games register mega_millions` (lottery + 8 estrategias
      sufijadas seed) y `python -m engine.games backfill mega_millions --from
      2017-10-31` (906 draws, uno por uno vía la API REST de producción — tardó
      varios minutos por ser 906 requests HTTP secuenciales, no un problema, solo
      lento). Verificado en D1 real: `COUNT(*)=906`, rango `2017-10-31` a
      `2026-07-03`. Verificado en producción real: `/api/games` devuelve los dos
      juegos activos, `/api/strategies?game=mega_millions` las 8 estrategias
      sufijadas, `/game.html?game=mega_millions` sirve bien, y
      `/api/top-pick?game=mega_millions` llamó al Container real y devolvió un
      ticket válido (blancas 1-70, Mega Ball 1-25). **Mega Millions activo de
      punta a punta en producción — migración + activación 100% completas.**

## Pendiente — otros (sin relación con la migración, siguen abiertos)

1. Conectar dominio propio `shiolplus.com` (deferido, sin fecha; aplica sin importar
   qué arquitectura de backend se use).
2. ✅ **Mega Millions activo en producción (sesión 16)** — 906 sorteos, 8
   estrategias, dashboard funcionando de punta a punta. Ver "Hecho, sesión 16".
3. ✅ **Automatización de `wins` + Scoreboard + Next Draw Tickets (sesión 21, ver
   "Hecho, sesión 21")**: `wins` ahora se llena automático para CUALQUIER ticket con
   `prize_amount > 0` (ya no solo 4+), con `ticket_id` real e idempotencia garantizada
   por índice único parcial. Nuevos endpoints `/api/ticket-performance` y
   `/api/upcoming-tickets`, nueva sección Scoreboard y modal de 20 tickets por
   estrategia en el frontend. **Auditado y deployado a producción en la misma
   sesión 21** — versión `f21aca55-82d0-444e-9117-875ca39aca9d`, ver "Hecho, sesión
   21" para el detalle del hallazgo (try/catch faltante en `insertWinsForTickets()`,
   corregido antes de deployar) y la verificación post-deploy.
4. ✅ **Encoding cp1252/mojibake confirmado como ya resuelto (revisado 2026-07-07)**:
   es el mismo incidente ya documentado arriba (mojibake de UTF-8 al escribir a D1
   local desde Windows en vez de WSL) — no hay ningún otro bug de encoding suelto en
   el código. Regla permanente ya anotada en "Notas / gotchas importantes". Sin
   acción de código pendiente.
5. ✅ **Limpieza hecha (2026-07-07)**: `frontend/public/` y `frontend/src/` confirmadas
   vacías (cero archivos) y sin ninguna referencia en el código (`worker.js`,
   `container.js`, `package.json`, `wrangler.toml`), borradas junto con `frontend/`.
   El frontend real sigue siendo `public/` y `src/` en la raíz.

## Hecho (2026-07-07)

- [x] **Item 4 (encoding)**: revisado todo `TODO.md` buscando cp1252/mojibake/
      UnicodeEncodeError — solo existe un incidente documentado (sesión con
      Docker+WSL2), ya resuelto y con regla permanente. Cerrado sin cambios de código.
- [x] **Item 5 (limpieza)**: borradas `frontend/public/`, `frontend/src/` y
      `frontend/` (vacías, sin referencias en el repo).

## Notas / gotchas importantes

- **Mount desync Windows↔sandbox Linux**: al editar archivos de este proyecto, el sandbox
  bash a veces lee una versión truncada/vieja justo después de un Edit/Write (confirmado con
  `package.json`, `src/worker.js`, `public/app.js`, `.gitignore`, `TODO.md`,
  `engine/pipeline/fetch_draw.py` en varias sesiones). El archivo real (Windows) estaba
  bien; solo la vista de bash quedaba desincronizada. Fix: reescribir el archivo desde
  bash con `cat > archivo << 'EOF' ... EOF` y verificar con `wc -l` / `tail` antes de
  confiar en scripts que lo consuman (build, tests, etc.).

- El proyecto correcto es `C:\Dev\apps\shiol-plus-v9` (NO `C:\Dev\apps\shiol-plus`,
  que es el monolito viejo Python/FastAPI v8, proyecto totalmente distinto).
- El worker debe quedarse como UNO SOLO llamado `shiol-plus`. Nunca crear un segundo
  worker -- actualizar siempre el existente.
- Deploy solo funciona desde una terminal real de Windows (`npx wrangler deploy` con
  OAuth cacheado). Entornos sandbox/Linux con node_modules instalado en Windows fallan
  por incompatibilidad de binario nativo (workerd).
- El token de Cloudflare en `.env` solo tiene scope D1:Edit -- sirve para sync_d1.py y
  consultas D1, pero NO para deploys de Workers ni para leer cron schedules via API.
- Si un futuro deploy falla en el paso de cron triggers, revisar primero si el cron
  string usa numeros para el dia de semana -- usar nombres (SUN, MON, etc.) en su lugar.
- **Desarrollo local con Containers requiere WSL2** (Windows nativo no soportado por
  wrangler). Docker Desktop necesita la integración WSL habilitada a mano para la
  distro usada (Settings → Resources → WSL Integration) -- no hay forma por CLI.
- Si tras habilitar/cambiar la integración Docker Desktop↔WSL algo se cuelga sin
  error (`pip install`, `npm install`, cualquier descarga dentro de un contenedor),
  sospechar primero de la red de la VM WSL2, no de recursos. Diagnóstico rápido:
  `ps aux` buscando procesos en estado `D` (bloqueados en kernel/red). Fix: `wsl
  --shutdown` + reabrir Docker Desktop, y confirmar con un `curl`/`docker run` de
  prueba antes de reintentar el build real.
- No correr `npm install` en Windows y en WSL contra el mismo `node_modules`
  compartido (`/mnt/c/...`) sin parar primero cualquier `wrangler dev` que siga
  vivo en el otro entorno -- los binarios nativos (`workerd`) son distintos por SO
  y un `npm install` los pisa, rompiendo la sesión activa del otro lado.
- Comandos que escriben texto con acentos/UTF-8 al D1 **local** (`wrangler d1
  execute --local`) deben correrse desde el mismo entorno donde vive `wrangler dev`
  (WSL, en este proyecto) -- correrlos desde Git Bash de Windows contra el mismo
  archivo puede corromper los acentos (mojibake) aunque el archivo fuente en disco
  esté bien codificado. Esto no afecta al D1 remoto (nunca tuvo este problema).
