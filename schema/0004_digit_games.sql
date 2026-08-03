-- SHIOL+ v9 — Migración 0004: Juegos de dígitos (NC Pick 3 / NC Pick 4) + Multi-draw + Jurisdicción
-- Soporte para game_type ('lotto' vs 'digit'), jurisdiction ('national' vs 'NC'), y draw_number (1=Day/Single, 2=Evening).

PRAGMA foreign_keys = OFF;

-- 1. Actualizar tabla lotteries
ALTER TABLE lotteries ADD COLUMN game_type TEXT DEFAULT 'lotto';
ALTER TABLE lotteries ADD COLUMN jurisdiction TEXT DEFAULT 'national';

-- Actualizar jurisdicción de juegos existentes
UPDATE lotteries SET jurisdiction = 'national' WHERE id IN ('powerball', 'mega_millions');
UPDATE lotteries SET jurisdiction = 'NC' WHERE id = 'cash5';

-- 2. Actualizar tabla draws para multi-draw (draw_number)
CREATE TABLE IF NOT EXISTS draws_new (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lottery_id  TEXT NOT NULL,
    draw_date   TEXT NOT NULL,               -- YYYY-MM-DD
    draw_number INTEGER DEFAULT 1 NOT NULL,   -- 1 = Single/Day, 2 = Evening
    n1 INTEGER, n2 INTEGER, n3 INTEGER,
    n4 INTEGER, n5 INTEGER,
    extra       INTEGER,                     -- powerball / mega ball / fireball
    source      TEXT,                        -- 'csv', 'powerball.com', 'musl_api', 'nc_csv'
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(lottery_id, draw_date, draw_number),
    FOREIGN KEY (lottery_id) REFERENCES lotteries(id)
);

INSERT INTO draws_new (id, lottery_id, draw_date, draw_number, n1, n2, n3, n4, n5, extra, source, created_at)
  SELECT id, lottery_id, draw_date, 1, n1, n2, n3, n4, n5, extra, source, created_at FROM draws;

DROP TABLE draws;
ALTER TABLE draws_new RENAME TO draws;
CREATE INDEX IF NOT EXISTS idx_draws_date ON draws(lottery_id, draw_date DESC, draw_number DESC);

-- 3. Actualizar tabla cycles para multi-draw (draw_number)
CREATE TABLE IF NOT EXISTS cycles_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lottery_id      TEXT NOT NULL,
    draw_date       TEXT NOT NULL,
    draw_number     INTEGER DEFAULT 1 NOT NULL,
    status          TEXT DEFAULT 'pending',  -- 'pending' | 'generated' | 'evaluated'
    draw_source     TEXT,
    tickets_total   INTEGER DEFAULT 0,
    strategies_run  INTEGER DEFAULT 0,
    elapsed_seconds REAL,
    notes           TEXT,
    executed_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(lottery_id, draw_date, draw_number)
);

INSERT INTO cycles_new (id, lottery_id, draw_date, draw_number, status, draw_source, tickets_total, strategies_run, elapsed_seconds, notes, executed_at)
  SELECT id, lottery_id, draw_date, 1, status, draw_source, tickets_total, strategies_run, elapsed_seconds, notes, executed_at FROM cycles;

DROP TABLE cycles;
ALTER TABLE cycles_new RENAME TO cycles;

PRAGMA foreign_keys = ON;
