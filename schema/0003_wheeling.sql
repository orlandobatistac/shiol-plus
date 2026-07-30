-- SHIOL+ v9 — Migración 0003: estrategia 9 "wheeling" (Fase 9, sesión 33)
-- Covering design / lottery wheel sobre pool de números calientes.
-- Seed para los 3 juegos activos. IDs siguen la convención de register.py:
-- powerball sin sufijo, resto con sufijo _<game_id>.

INSERT OR IGNORE INTO strategies (id, lottery_id, name, description, status, current_weight) VALUES
    ('wheeling',               'powerball',     'Wheeling', 'Covering design (lottery wheel) sobre pool de números calientes', 'active', 1.0),
    ('wheeling_mega_millions', 'mega_millions', 'Wheeling', 'Covering design (lottery wheel) sobre pool de números calientes', 'active', 1.0),
    ('wheeling_cash5',         'cash5',         'Wheeling', 'Covering design (lottery wheel) sobre pool de números calientes', 'active', 1.0);
