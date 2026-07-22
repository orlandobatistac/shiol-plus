-- SHIOL+ v9 — Cloudflare D1 Schema
-- SQLite compatible

-- ============================================================
-- LOTTERIES — Juegos de lotería registrados
-- ============================================================
CREATE TABLE IF NOT EXISTS lotteries (
    id              TEXT PRIMARY KEY,        -- 'powerball', 'mega_millions'
    name            TEXT NOT NULL,
    draw_days       TEXT NOT NULL,           -- 'mon,wed,sat'
    white_ball_count INTEGER NOT NULL,
    white_ball_max  INTEGER NOT NULL,
    extra_ball_name TEXT NOT NULL,           -- 'Powerball', 'Mega Ball'
    extra_ball_max  INTEGER NOT NULL,
    active          INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Seed inicial
INSERT OR IGNORE INTO lotteries VALUES (
    'powerball', 'Powerball', 'mon,wed,sat', 5, 69, 'Powerball', 26, 1, datetime('now')
);
INSERT OR IGNORE INTO lotteries VALUES (
    'cash5', 'NC Cash 5', 'sun,mon,tue,wed,thu,fri,sat', 5, 43, '', 0, 0, datetime('now')
);

-- ============================================================
-- DRAWS — Sorteos históricos y futuros
-- ============================================================
CREATE TABLE IF NOT EXISTS draws (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lottery_id  TEXT NOT NULL,
    draw_date   TEXT NOT NULL,               -- YYYY-MM-DD
    n1 INTEGER, n2 INTEGER, n3 INTEGER,
    n4 INTEGER, n5 INTEGER,
    extra       INTEGER,                     -- powerball / mega ball
    source      TEXT,                        -- 'csv', 'powerball.com', 'musl_api'
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(lottery_id, draw_date),
    FOREIGN KEY (lottery_id) REFERENCES lotteries(id)
);

CREATE INDEX IF NOT EXISTS idx_draws_date ON draws(lottery_id, draw_date DESC);

-- ============================================================
-- STRATEGIES — Registro de estrategias
-- ============================================================
CREATE TABLE IF NOT EXISTS strategies (
    id              TEXT PRIMARY KEY,        -- 'frequency_weighted'
    lottery_id      TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    status          TEXT DEFAULT 'active',   -- 'active' | 'probation' | 'archived'
    current_weight  REAL DEFAULT 1.0,
    total_cycles    INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    archived_at     TEXT,
    FOREIGN KEY (lottery_id) REFERENCES lotteries(id)
);

-- Seed: estrategias iniciales Powerball
INSERT OR IGNORE INTO strategies (id, lottery_id, name, description) VALUES
    ('frequency_weighted', 'powerball', 'Frequency Weighted',   'Probabilidad histórica de cada número'),
    ('cooccurrence',       'powerball', 'Co-occurrence',         'Pares de números que aparecen juntos frecuentemente'),
    ('range_balanced',     'powerball', 'Range Balanced',        'Distribución 2 low / 2 mid / 1 high'),
    ('coverage_optimizer', 'powerball', 'Coverage Optimizer',    'Maximiza cobertura evitando repetición de números'),
    ('xgboost_ml',         'powerball', 'XGBoost ML',            'Modelo XGBoost entrenado con histórico'),
    ('hybrid_ensemble',    'powerball', 'Hybrid Ensemble',       '70% XGBoost + 30% Co-occurrence'),
    ('intelligent_scoring','powerball', 'Intelligent Scoring',   'Scoring multi-criterio con decay temporal'),
    ('random_baseline',    'powerball', 'Random Baseline',       'Control científico — aleatorio puro'),
    ('wheeling',           'powerball', 'Wheeling',              'Covering design (lottery wheel) sobre pool de números calientes');

-- ============================================================
-- CYCLES — Un ciclo = una ejecución del pipeline por draw
-- ============================================================
CREATE TABLE IF NOT EXISTS cycles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lottery_id      TEXT NOT NULL,
    draw_date       TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',  -- 'pending' | 'generated' | 'evaluated'
    draw_source     TEXT,
    tickets_total   INTEGER DEFAULT 0,
    strategies_run  INTEGER DEFAULT 0,
    elapsed_seconds REAL,
    notes           TEXT,
    executed_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(lottery_id, draw_date)
);

-- ============================================================
-- TICKETS — Predicciones generadas por estrategia por ciclo
-- ============================================================
CREATE TABLE IF NOT EXISTS tickets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id        INTEGER NOT NULL,
    strategy_id     TEXT NOT NULL,
    lottery_id      TEXT NOT NULL,
    draw_date       TEXT NOT NULL DEFAULT '', -- sorteo contra el que se evalúa (denormalizado de cycles.draw_date)
    n1 INTEGER, n2 INTEGER, n3 INTEGER,
    n4 INTEGER, n5 INTEGER,
    extra           INTEGER,
    confidence      REAL DEFAULT 0.5,
    -- resultados (se llenan al evaluar)
    matches_white   INTEGER,
    matches_extra   INTEGER DEFAULT 0,
    prize_level     TEXT,                    -- 'jackpot','match5','match4+pb', etc.
    prize_amount    REAL DEFAULT 0.0,
    evaluated       INTEGER DEFAULT 0,
    FOREIGN KEY (cycle_id) REFERENCES cycles(id)
);

CREATE INDEX IF NOT EXISTS idx_tickets_cycle     ON tickets(cycle_id);
CREATE INDEX IF NOT EXISTS idx_tickets_strategy  ON tickets(strategy_id, lottery_id);
CREATE INDEX IF NOT EXISTS idx_tickets_draw_date ON tickets(lottery_id, draw_date);

-- ============================================================
-- STRATEGY_STATS — Resultados agregados por estrategia por ciclo
-- ============================================================
CREATE TABLE IF NOT EXISTS strategy_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id        INTEGER NOT NULL,
    strategy_id     TEXT NOT NULL,
    lottery_id      TEXT NOT NULL,
    draw_date       TEXT NOT NULL,
    tickets_count   INTEGER DEFAULT 0,
    matches_3       INTEGER DEFAULT 0,
    matches_4       INTEGER DEFAULT 0,
    matches_5       INTEGER DEFAULT 0,
    matches_jackpot INTEGER DEFAULT 0,
    total_prize     REAL DEFAULT 0.0,
    roi             REAL DEFAULT 0.0,        -- (prize - cost) / cost
    weight_before   REAL,
    weight_after    REAL,
    evaluated_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(cycle_id, strategy_id)
);

-- ============================================================
-- WINS — Hall of Fame (premios reales obtenidos)
-- Desde sesión 2026-07-07 (sesión 21) se llena automático para CUALQUIER
-- ticket evaluado con prize_amount > 0 (ya no solo premios grandes/manual)
-- -- ver persistStrategyResult() en worker.js. `ticket_id` + el índice único
-- parcial existen para que el INSERT OR IGNORE sea idempotente por ticket
-- real (no por combinación de números, que en teoría podría repetirse entre
-- dos tickets distintos de la misma estrategia en el mismo ciclo).
-- ============================================================
CREATE TABLE IF NOT EXISTS wins (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id     TEXT,
    lottery_id      TEXT NOT NULL,
    draw_date       TEXT NOT NULL,
    numbers         TEXT NOT NULL,           -- JSON: [n1,n2,n3,n4,n5]
    extra           INTEGER,
    prize_level     TEXT NOT NULL,
    prize_amount    REAL NOT NULL,
    verified        INTEGER DEFAULT 0,
    notes           TEXT,
    recorded_at     TEXT DEFAULT (datetime('now')),
    ticket_id       INTEGER REFERENCES tickets(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_wins_ticket_id ON wins(ticket_id) WHERE ticket_id IS NOT NULL;

-- El $50K que pegó 👀
-- INSERT INTO wins (lottery_id, draw_date, numbers, extra, prize_level, prize_amount, verified, notes)
-- VALUES ('powerball', 'YYYY-MM-DD', '[n1,n2,n3,n4,n5]', pb, 'match4', 50000, 1, 'Primer premio real registrado');

-- ============================================================
-- JACKPOTS — Jackpot estimado del próximo sorteo, por juego
-- (sesión 2026-07-07). Una sola fila por juego (upsert en cada fetch, no
-- historial) -- ver engine/pipeline/fetch_jackpot.py. last_status/last_attempt_at
-- existen para poder detectar (y avisar) si el scraper viene fallando el
-- validador de sanidad hace varios intentos seguidos, sin perder el último
-- valor bueno mientras tanto.
-- ============================================================
CREATE TABLE IF NOT EXISTS jackpots (
    lottery_id      TEXT PRIMARY KEY,        -- 'powerball', 'mega_millions'
    amount          REAL,                    -- jackpot anunciado (USD), último valor bueno
    cash_value      REAL,                    -- valor en efectivo (USD), último valor bueno
    source          TEXT,                    -- 'nclottery.com'
    last_status     TEXT DEFAULT 'unknown',  -- 'ok' | 'stale_parser_broken' | 'unknown'
    last_success_at TEXT,                    -- último fetch que pasó el validador
    last_attempt_at TEXT,                    -- último intento, haya pasado el validador o no
    FOREIGN KEY (lottery_id) REFERENCES lotteries(id)
);
