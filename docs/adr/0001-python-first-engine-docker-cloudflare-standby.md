# ADR-0001: Consolidar el motor de estrategias en Python (Cloudflare Container), resto 100% Cloudflare-nativo

## Estado

Aceptado — 2026-07-04. **Revisado el mismo día** tras investigar la documentación
oficial de Cloudflare: la versión original de este ADR proponía sacar todo el backend
de Cloudflare (FastAPI + Docker Compose + SQLite local + Cloudflare Pages separado).
Se corrigió el enfoque — ver "Decisión", "Stack propuesto" y "Estructura de carpetas"
actualizados abajo — porque Cloudflare Containers alcanzó disponibilidad general
(GA, 13 abr. 2026) y permite correr el motor Python **dentro** de la misma cuenta y
del mismo Worker de Cloudflare, sin salir de la plataforma. El contexto y los
hallazgos de la auditoría (sección siguiente) no cambiaron; lo que cambió es cómo se
implementa la decisión.

**Revisado de nuevo el 2026-07-05** (sesión 12-13, activación de Mega Millions): ver
"Adenda — fetch de datos de lotería también centralizado" al final de este documento.
El punto 4 de "Contexto" (fuentes de `fetch_draw.py` no conscientes del juego) se
resolvió del lado Python, pero la auditoría original no había detectado que
`worker.js` tenía **su propia implementación JS independiente** del mismo fetch
(`fetchDrawFromNyData`/`fetchDrawFromCSV`) — es decir, quedó una quinta duplicación
fuera del radar de este ADR. Se corrigió moviendo esa lógica también a `engine/`,
cerrando el patrón por completo (no solo el bug puntual).

## Contexto

SHIOL+ v9 nació con dos implementaciones paralelas del mismo motor de predicción,
por diseño original (ver README anterior): `lab/` en Python para "laboratorio local
y backtest", y `src/worker.js` en JavaScript para correr automáticamente en
Cloudflare Workers (cron + API + D1) en producción.

Una auditoría completa del código (2026-07-04) encontró que esa duplicación ya
había producido divergencias reales, no solo teóricas:

1. **6 de las 8 estrategias implementan algoritmos distintos en JS vs Python bajo
   el mismo nombre.** `xgboost_ml` en Python entrena un `XGBClassifier` real;
   en JS es una heurística de frecuencia con penalización por recencia, sin
   machine learning real. `hybrid_ensemble` en Python es literalmente "70%
   XGBoost + 30% Co-occurrence" (como dice su propia descripción); en JS es una
   mezcla de frecuencia + co-ocurrencia + aleatorio con proporciones distintas
   (50/30/20) que nunca toca XGBoost. `intelligent_scoring` en Python implementa
   decay temporal exponencial + bonus por números atrasados (como dice su
   descripción); en JS es solo una suma de dos ventanas de frecuencia, sin decay
   real. `cooccurrence` en Python preserva pares reales de números; en JS se
   colapsa a un peso por número individual, perdiendo la estructura de pares.
   `range_balanced` en Python usa 3 tercios (2 low/2 mid/1 high, como dice su
   descripción); en JS usa 5 rangos iguales de 1 número cada uno. `coverage_optimizer`
   en Python es puramente aleatorio evitando repetición; en JS mezcla eso con peso
   de frecuencia. Solo `random_baseline` y `frequency_weighted` son
   conceptualmente equivalentes entre ambas versiones.
2. **La fórmula de ajuste de peso adaptativo difiere entre `worker.js` y
   `lab/pipeline/weights.py`**, aunque comparten las mismas constantes
   (LEARNING_RATE, umbrales de probation/archive). Con el mismo ROI, producen
   pesos distintos.
3. **`lab/games/register.py` genera IDs de estrategia con sufijo de juego**
   (`frequency_weighted_mega_millions`) para cualquier lotería que no sea
   Powerball, pero `lab/pipeline/run.py` y `sync_d1.py` siempre usan el nombre
   plano sin sufijo. Es un bug puramente de Python, independiente de la
   duplicación JS/Python, pero agrava el mismo problema de fondo: nadie diseñó
   un único contrato de datos compartido.
4. `lab/pipeline/fetch_draw.py` tiene fuentes de respaldo (`_from_powerball_web`,
   `_from_musl_api`) que no son conscientes del juego — quedan hardcodeadas a
   Powerball sin importar qué lotería se les pida.

A esto se suma fricción operativa real: `wrangler`/`workerd` no corre en el
sandbox Linux usado para desarrollo asistido, el deploy a Cloudflare solo
funciona desde una terminal real de Windows con OAuth cacheado, y Cloudflare
Workers no puede ejecutar `numpy`/`pandas`/`xgboost`/`scikit-learn` de ninguna
forma — es decir, la versión JS nunca pudo ser un port real del motor Python,
solo una aproximación forzada desde el día uno.

## Decisión

1. El motor de predicción (estrategias, evaluación, cálculo de pesos adaptativos)
   se implementa y mantiene **únicamente en Python**, en la carpeta `engine/`
   (antes `lab/` — se renombra de forma definitiva, no opcional).
2. **Todo lo demás queda 100% nativo en Cloudflare**, en la misma cuenta/proyecto,
   sin salir de la plataforma:
   - El Worker `shiol-plus` (JS) sigue siendo la API pública, el cron, y ahora
     también sirve el frontend como **Workers Static Assets** (reemplazo actual
     de Cloudflare Pages para este caso de uso).
   - **D1 sigue siendo la única base de datos**, en producción y en local —
     `wrangler dev` / `vite dev` simulan D1 localmente de forma automática y
     persistente, con el mismo esquema. No hace falta una SQLite paralela.
   - El motor Python corre dentro de un **Cloudflare Container** (GA desde el
     13 abr. 2026), un contenedor Docker administrado directamente por el
     Worker vía binding (`@cloudflare/containers`), no en un host externo.
3. El Worker orquesta: en cada cron o request administrativo, le pide al
   Container que corra un ciclo (`POST /run-cycle`), recibe el JSON de
   resultados, y escribe a D1 usando su binding nativo (reemplaza el
   `sync_d1.py` actual, que hoy le pega a la API REST de D1 por HTTP).
4. Cloudflare Workers/JS **ya no queda en standby** (corrección respecto a la
   versión original de este ADR) — vuelve a ser la ruta de producción activa,
   pero ahora sin lógica de estrategias duplicada: el Worker solo orquesta y
   sirve, el Container calcula.
5. Flujo de trabajo obligatorio: **todo se prueba en local (`vite dev`, que
   levanta Worker + D1 local + Container local con Docker) antes de considerar
   cualquier despliegue**.
6. Orlando ya activó el plan **Workers Paid de Cloudflare (US$5/mes)**, requisito
   para usar Containers — confirmado 2026-07-04, no es un costo pendiente de
   aprobar.

## Consecuencias

**Positivas**

- Elimina de raíz la clase de bug más grave de la auditoría (algoritmos
  divergentes entre JS y Python): ya no existe una segunda implementación con
  la que desincronizarse.
- La pregunta "¿cuál fórmula de peso es la correcta, JS o Python?" queda
  resuelta automáticamente — solo existe una desde ahora, y corre en el Container.
- **Local y producción son topológicamente idénticos** (Worker + D1 + Container,
  en ambos casos) — se elimina el riesgo de "funciona en mi setup local pero no
  en producción" que tenía la propuesta original de FastAPI+SQLite+Pages.
- No hace falta migrar el histórico de D1 a ninguna otra base — D1 remoto y D1
  local (simulado por Wrangler/Vite) usan el mismo esquema sin conversión.
- Se reutiliza el 100% de las estrategias ya correctas y más sofisticadas de
  `engine/strategies/` (XGBoost real, pares de co-ocurrencia reales, decay
  temporal real) como única fuente de verdad del "torneo de algoritmos".
- Se mantiene la ejecución "siempre activa" de Cloudflare (Workers + cron) que
  la versión original de este ADR iba a sacrificar.

**Negativas / a vigilar**

- Nuevo costo fijo: US$5/mes (plan Workers Paid), ya aceptado por Orlando.
- Dos bugs de la auditoría **no se resuelven solos** con esta decisión, porque
  son bugs de Python puro: el sufijo de `register.py` para juegos no-Powerball,
  y las fuentes de `fetch_draw.py` no conscientes del juego. Siguen en la lista
  de pendientes.
- Cloudflare Containers requiere Docker (Desktop o Colima) instalado para
  desarrollo local — dependencia nueva que el proyecto no tenía.
- Los contenedores tardan unos minutos en aprovisionarse tras el primer deploy
  (según la documentación de Cloudflare) — no afecta al Worker, pero las
  llamadas al Container fallarán durante esa ventana inicial.
- El contrato HTTP interno Worker↔Container (`POST /run-cycle`, `GET /games`,
  etc.) es nueva superficie a diseñar y mantener con cuidado — es el nuevo
  "punto de unión" entre JS y Python, y hay que evitar que se convierta en el
  próximo lugar donde algo diverja silenciosamente.

## Alternativas consideradas

- **Mantener ambas implementaciones y forzar paridad estricta entre JS y
  Python.** Descartado: costo de mantenimiento continuo alto, y ya demostró
  divergir en la práctica sin que nadie lo notara durante semanas.
- **Portar el motor completo a JS/TypeScript para correr nativo en Cloudflare
  Workers.** Descartado: XGBoost y scikit-learn no tienen equivalente viable en
  el runtime de Workers; reescribir esa lógica en JS puro sería recrear el
  mismo problema de divergencia, ahora en sentido inverso.
- **Sacar el motor Python de Cloudflare por completo** (FastAPI + Docker Compose
  en un host genérico — VPS/Fly.io/Railway/Render — con SQLite local y
  Cloudflare Pages separado para el frontend). Era la versión original de este
  ADR. Descartada tras confirmar que Cloudflare Containers (GA) resuelve el
  mismo problema sin salir de la plataforma, sin pagar/administrar un segundo
  proveedor, y sin mantener dos bases de datos ni dos flujos de deploy distintos.

## Stack propuesto

| Capa | Elección | Por qué |
|------|----------|---------|
| Motor de estrategias | Python 3.11+, corre en un **Cloudflare Container** | Ya es el código correcto y validado (`engine/strategies/`); cero reescritura de lógica. El Container permite Docker completo (numpy/pandas/xgboost/scikit-learn) sin salir de Cloudflare. |
| API interna del motor | FastAPI (o incluso `http.server` de stdlib, a decidir en Fase 2) | Solo necesita exponer `/run-cycle` y `/games` al Worker — superficie pequeña, no es una API pública. |
| Orquestación + API pública + cron | Worker `shiol-plus` (JS, sin cambios de rol) | Ya existe, ya tiene el binding a D1 y los cron triggers correctos (SUN/TUE/THU). Ahora además orquesta el Container en vez de calcular estrategias él mismo. |
| Base de datos | **D1** (producción y local, sin capa intermedia) | `wrangler dev`/`vite dev` simulan D1 localmente de forma automática — mismo esquema en ambos entornos, sin migración. |
| Contenedores | **Cloudflare Containers** (`@cloudflare/containers`, GA) | Un solo `wrangler deploy` construye y publica el contenedor junto con el Worker — no hay Docker Compose ni host separado que mantener. |
| Frontend | Vite + HTML/CSS/JS vanilla, servido como **Workers Static Assets** | Reutiliza el 100% del frontend ya construido; Vite da dev server con recarga rápida en local, y el mismo Worker sirve los assets en producción (sin Cloudflare Pages como pieza separada). |
| Scheduling | Cron Triggers de Cloudflare (ya existentes en `wrangler.toml`) | Se mantiene sin cambios — el cron ahora dispara al Worker, que a su vez llama al Container. |
| Testing | pytest para `engine/`, y pruebas del Worker con Vitest/Miniflare | La auditoría completa existe porque nadie tenía un test que dijera "range_balanced debe repartir 2 low/2 mid/1 high" — vale la pena blindar eso ahora que hay una sola implementación que proteger. |

## Estructura de carpetas propuesta

```
shiol-plus-v9/
├── src/                       # Worker JS — API pública, cron, acceso D1, orquesta el Container
│   ├── index.js               # fetch() + scheduled()
│   ├── container.js           # clase Container (binding a @cloudflare/containers)
│   ├── routes/                # /api/draws, /api/strategies, /api/history, /api/wins, /api/games
│   └── db/                    # helpers de queries D1
├── engine/                    # antes "lab/" — SOLO el motor Python, corre en el Container
│   ├── Dockerfile
│   ├── server.py              # expone /run-cycle, /games al Worker
│   ├── games/                 # config por lotería/estado (escalable a más juegos)
│   ├── strategies/            # las 8 estrategias, sin cambios de lógica
│   └── pipeline/              # evaluate.py, weights.py (ya no necesitan CLI ni archivos en disco)
├── frontend/                  # antes "public/" — servido como Workers Static Assets
│   ├── index.html / app.js / styles.css
│   └── (Vite genera el build; sin build.js manual)
├── schema/
│   └── d1_schema.sql          # sin cambios, sigue siendo la única verdad de esquema
├── docs/adr/                  # este archivo
├── tests/                     # pytest (engine/) + Vitest/Miniflare (src/)
├── wrangler.toml              # define Worker + assets + D1 + container, todo en un archivo
├── vite.config.js
└── TODO.md
```

## Adenda — fetch de datos de lotería también centralizado (2026-07-05)

Al activar Mega Millions (sesión 12) se corrigió un bug real en
`engine/pipeline/fetch_draw.py::_from_ny_data()`: el dataset de Socrata de Mega
Millions trae la Mega Ball en un campo separado (`mega_ball`), no embebida en
`winning_numbers` como Powerball — sin el fix, el fetch fallaba en silencio para
todo sorteo de Mega Millions.

Una auditoría externa (sesión 12-13) encontró que ese fix **no alcanzaba** a la
implementación real usada en producción: `worker.js::fetchDrawFromNyData()` era
una segunda implementación JS del mismo fetch/parseo, independiente de la de
Python, y nunca recibió el fix. El cron real (que usa la copia JS) habría seguido
reportando `draw_not_available` para Mega Millions indefinidamente, sin ningún
error visible en los logs.

Al investigar más a fondo (a pedido explícito de Orlando: *"no quiero dejar cosas
sueltas que después aparezcan en JS y no en Python"*) aparecieron dos
implementaciones más del mismo problema de fondo:

- `worker.js`'s `/api/admin/backfill` — un endpoint HTTP de backfill masivo,
  usando el CSV de NC Lottery que ya estaba roto (404 desde 2026-07-04), nunca
  actualizado al fix de `ny_data_api`. Sin uso real conocido.
- `engine/games/register.py::cmd_backfill()` — la versión CLI correcta,
  correspondiente a la misma operación, que sí se mantenía actualizada.

En total: **cuatro implementaciones paralelas** de "traer/parsear un sorteo desde
una fuente externa" (Python single-date, JS single-date, JS bulk/backfill roto,
Python CLI bulk/backfill), de las cuales solo dos seguían funcionando y ninguna
compartía código con las demás.

**Resolución**: se consolidó todo el fetch/parseo *single-date* (el que usa el
cron real) en un nuevo endpoint del Container, `POST /fetch-draw`
(`engine/server.py`), expuesto al Worker vía `fetchDrawFromEngine()`
(`src/container.js`). Se borraron `fetchDrawFromNyData()`/`fetchDrawFromCSV()` de
`worker.js` y el endpoint `/api/admin/backfill` completo. El backfill masivo queda
como la única operación que sigue viviendo fuera del Container — es manual/rara
por naturaleza (se corre una vez al activar un juego nuevo), y vive solo en
`engine/games/register.py::cmd_backfill()` (CLI).

**Regla del proyecto, en adelante**: ninguna lógica de fetch/parseo de datos de
lotería por-juego vive en `worker.js`. Vive en `engine/`, expuesta al Worker vía
el Container cuando hace falta en producción (fetch de un sorteo en el cron), o
vía CLI cuando es una operación manual/rara (backfill masivo al activar un
juego). Esta regla extiende la misma lógica del punto 1 de "Decisión" (estrategias
solo en Python) a cualquier lógica de negocio por-juego, no solo a las
estrategias — el patrón de divergencia silenciosa es idéntico sin importar qué
lógica se duplique.

Ver `TODO.md`, sesión 12-13, para el detalle completo de los bugs y su
verificación.

## Referencias

- Auditoría completa: sesión de trabajo 2026-07-04 (ver `TODO.md`, sección
  "Hecho — auditoría de bugs").
- Cloudflare Containers — Getting started: https://developers.cloudflare.com/containers/get-started/
- Cloudflare Containers — GA changelog (13 abr. 2026): https://developers.cloudflare.com/changelog/post/2026-04-13-containers-sandbox-ga/
- Cloudflare Containers — desarrollo local con Vite plugin: https://developers.cloudflare.com/containers/local-dev/
- Cloudflare Vite plugin + Containers en local (ago. 2025): https://developers.cloudflare.com/changelog/post/2025-08-01-containers-in-vite-dev/
- Workers Static Assets: https://developers.cloudflare.com/workers/static-assets/
- Migración de Pages a Workers: https://developers.cloudflare.com/workers/static-assets/migration-guides/migrate-from-pages/
- D1 — desarrollo local: https://developers.cloudflare.com/d1/best-practices/local-development/
- Nuevo pricing de CPU para Containers (nov. 2025): https://developers.cloudflare.com/changelog/post/2025-11-21-new-cpu-pricing/
