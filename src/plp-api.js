/**
 * PLP (PatternLottoPro) external API — consumed server-to-server by
 * the patternlottopro.com backend (shiol_client.py).
 *
 * Authenticated routes (/api/v2/*): require Authorization: Bearer <PREDICTLOTTOPRO_API_KEY>
 * Public routes (/api/v1/public/*): no auth
 *
 * All endpoints are Powerball-only (PLP does not consume other games).
 */

import { handlePresentationAPI } from './presentation-api.js';

const GAME = 'powerball';

const JSON_H = {
  'Content-Type': 'application/json',
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
};

function plpJson(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: JSON_H });
}

function verifyAuth(request, env) {
  const key = env.PREDICTLOTTOPRO_API_KEY;
  if (!key) return false;
  const header = request.headers.get('Authorization') || '';
  const token = header.startsWith('Bearer ') ? header.slice(7) : '';
  return token === key;
}

// ─────────────────────────────────────────────────────────────
// Hot/cold numbers from the last N draws (Powerball)
// ─────────────────────────────────────────────────────────────
async function calcHotCold(db, limit = 100) {
  const { results: draws } = await db.prepare(
    `SELECT n1,n2,n3,n4,n5,extra FROM draws WHERE lottery_id=? ORDER BY draw_date DESC LIMIT ?`
  ).bind(GAME, limit).all();

  if (!draws.length) {
    return {
      hot_numbers: { white_balls: [], powerballs: [] },
      cold_numbers: { white_balls: [], powerballs: [] },
      draws_analyzed: 0,
    };
  }

  const wf = new Map();
  const pf = new Map();
  for (let i = 1; i <= 69; i++) wf.set(i, 0);
  for (let i = 1; i <= 26; i++) pf.set(i, 0);

  for (const d of draws) {
    for (const n of [d.n1, d.n2, d.n3, d.n4, d.n5]) wf.set(n, (wf.get(n) || 0) + 1);
    pf.set(d.extra, (pf.get(d.extra) || 0) + 1);
  }

  const ws = [...wf.entries()].sort((a, b) => b[1] - a[1]);
  const ps = [...pf.entries()].sort((a, b) => b[1] - a[1]);

  return {
    hot_numbers: {
      white_balls: ws.slice(0, 10).map(([n]) => n),
      powerballs: ps.slice(0, 5).map(([n]) => n),
    },
    cold_numbers: {
      white_balls: ws.slice(-10).map(([n]) => n),
      powerballs: ps.slice(-5).map(([n]) => n),
    },
    draws_analyzed: draws.length,
  };
}

// Next Powerball draw date (Mon=1, Wed=3, Sat=6)
function nextPowerballDate() {
  const now = new Date();
  for (let i = 1; i <= 7; i++) {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() + i);
    if ([1, 3, 6].includes(d.getUTCDay())) return d.toISOString().slice(0, 10);
  }
  return null;
}

// ─────────────────────────────────────────────────────────────
// Main handler — called from worker.js before other routes
// ─────────────────────────────────────────────────────────────
export async function handlePlpAPI(path, url, request, env) {
  const db = env.DB;

  // ── Public endpoints — no auth ────────────────────────────

  if (path === '/api/v1/public/jackpot') {
    const row = await db.prepare(
      `SELECT amount, cash_value, last_status, last_success_at FROM jackpots WHERE lottery_id=?`
    ).bind(GAME).first();

    if (!row || row.amount == null) return plpJson({ found: false });

    const fmt = (v) =>
      v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(0)} Million` : `$${v.toLocaleString()}`;

    return plpJson({
      found: true,
      nextPrizeText: fmt(row.amount),
      nextPrizeCombined: `${fmt(row.amount)} / Cash Value ${fmt(row.cash_value)}`,
      nextDrawDate: nextPowerballDate(),
      amount: row.amount,
      cash_value: row.cash_value,
    });
  }

  if (path === '/api/v1/public/recent-draws') {
    const limit = Math.min(parseInt(url.searchParams.get('limit') || '12'), 50);
    const { results } = await db.prepare(`
      SELECT d.draw_date, d.n1, d.n2, d.n3, d.n4, d.n5, d.extra AS pb,
             c.status, c.tickets_total,
             COALESCE(ss.total_prize, 0) AS total_prize
      FROM draws d
      LEFT JOIN cycles c ON c.lottery_id = d.lottery_id AND c.draw_date = d.draw_date
      LEFT JOIN (
        SELECT draw_date, SUM(total_prize) AS total_prize
        FROM strategy_stats WHERE lottery_id=? GROUP BY draw_date
      ) ss ON ss.draw_date = d.draw_date
      WHERE d.lottery_id=?
      ORDER BY d.draw_date DESC LIMIT ?
    `).bind(GAME, GAME, limit).all();

    return plpJson({
      draws: results.map(r => ({
        draw_date: r.draw_date,
        n1: r.n1, n2: r.n2, n3: r.n3, n4: r.n4, n5: r.n5, pb: r.pb,
        has_predictions: r.status === 'evaluated',
        total_prize: r.total_prize,
        total_tickets: r.tickets_total || 0,
      })),
    });
  }

  if (path === '/api/v1/public/best-match') {
    const row = await db.prepare(`
      SELECT draw_date, matches_white, matches_extra, prize_level,
             prize_amount, n1, n2, n3, n4, n5, extra, strategy_id
      FROM tickets
      WHERE lottery_id=? AND evaluated=1 AND prize_amount > 0
      ORDER BY prize_amount DESC, matches_white DESC LIMIT 1
    `).bind(GAME).first();

    if (!row) return plpJson({ best_match: null });

    return plpJson({
      best_match: {
        draw_date: row.draw_date,
        white_matches: row.matches_white,
        extra_matches: row.matches_extra,
        prize_level: row.prize_level,
        prize_amount: row.prize_amount,
        numbers: [row.n1, row.n2, row.n3, row.n4, row.n5],
        extra: row.extra,
        strategy: row.strategy_id,
      },
    });
  }

  // /api/v1/public/analytics/draw/{date}
  const drawMatch = path.match(/^\/api\/v1\/public\/analytics\/draw\/(\d{4}-\d{2}-\d{2})$/);
  if (drawMatch) {
    const fakeUrl = new URL(request.url);
    fakeUrl.pathname = `/api/analyses/${drawMatch[1]}`;
    fakeUrl.searchParams.set('game', GAME);
    const resp = await handlePresentationAPI(`/api/analyses/${drawMatch[1]}`, fakeUrl, env);
    if (!resp) return plpJson({ error: 'Not found' }, 404);
    const data = await resp.json();
    return new Response(JSON.stringify(data), { status: resp.status, headers: JSON_H });
  }

  // ── Authenticated endpoints /api/v2/* ─────────────────────
  if (!path.startsWith('/api/v2/')) return null;

  if (!verifyAuth(request, env)) {
    return plpJson({ error: 'Unauthorized' }, 401);
  }

  // GET /api/v2/plp-dashboard
  if (path === '/api/v2/plp-dashboard' && request.method === 'GET') {
    const [drawStats, hotCold, { results: topStrats }, nextCycle] = await Promise.all([
      db.prepare(
        `SELECT COUNT(*) AS total_draws, MAX(draw_date) AS most_recent FROM draws WHERE lottery_id=?`
      ).bind(GAME).first(),

      calcHotCold(db, 100),

      db.prepare(`
        SELECT s.id AS name, s.current_weight AS weight,
               COALESCE(agg.total_plays, 0) AS total_plays,
               COALESCE(agg.win_rate, 0) AS win_rate
        FROM strategies s
        LEFT JOIN (
          SELECT strategy_id,
                 SUM(tickets_count) AS total_plays,
                 CASE WHEN SUM(tickets_count) > 0
                      THEN ROUND(1.0 * SUM(matches_3 + matches_4 + matches_5) / SUM(tickets_count), 4)
                      ELSE 0 END AS win_rate
          FROM strategy_stats WHERE lottery_id=? GROUP BY strategy_id
        ) agg ON agg.strategy_id = s.id
        WHERE s.lottery_id=? AND s.status != 'archived'
        ORDER BY s.current_weight DESC LIMIT 5
      `).bind(GAME, GAME).all(),

      db.prepare(
        `SELECT id, draw_date FROM cycles WHERE lottery_id=? AND status='generated' ORDER BY draw_date ASC LIMIT 1`
      ).bind(GAME).first(),
    ]);

    let predictions = { next_draw_date: nextPowerballDate(), total_tickets: 0, sets: [] };

    if (nextCycle) {
      const { results: pool } = await db.prepare(`
        SELECT n1, n2, n3, n4, n5, extra, strategy_id, confidence
        FROM tickets WHERE cycle_id=? ORDER BY confidence DESC LIMIT 5
      `).bind(nextCycle.id).all();

      predictions = {
        next_draw_date: nextCycle.draw_date,
        total_tickets: pool.length,
        sets: [{
          strategy: 'multi_strategy_blend',
          tickets: pool.map(t => ({
            white_balls: [t.n1, t.n2, t.n3, t.n4, t.n5],
            powerball: t.extra,
            confidence: t.confidence,
          })),
        }],
      };
    }

    return plpJson({
      success: true,
      from_cache: false,
      data: {
        draw_stats: {
          total_draws: drawStats?.total_draws ?? 0,
          most_recent: drawStats?.most_recent ?? null,
          current_era: 1992,
        },
        hot_cold: hotCold,
        top_strategies: topStrats,
        predictions,
      },
    });
  }

  // GET /api/v2/pipeline/pool?count=N&draw_date=?
  if (path === '/api/v2/pipeline/pool' && request.method === 'GET') {
    const count = Math.min(Math.max(1, parseInt(url.searchParams.get('count') || '5')), 55);
    const drawDateParam = url.searchParams.get('draw_date');

    const cycle = drawDateParam
      ? await db.prepare(
          `SELECT id, draw_date FROM cycles WHERE lottery_id=? AND status='generated' AND draw_date=? LIMIT 1`
        ).bind(GAME, drawDateParam).first()
      : await db.prepare(
          `SELECT id, draw_date FROM cycles WHERE lottery_id=? AND status='generated' ORDER BY draw_date ASC LIMIT 1`
        ).bind(GAME).first();

    if (!cycle) return plpJson({ error: 'No pool available for this draw' }, 404);

    const { results: tickets } = await db.prepare(`
      SELECT id, n1, n2, n3, n4, n5, extra AS pb, strategy_id AS strategy, confidence
      FROM tickets WHERE cycle_id=? ORDER BY confidence DESC LIMIT ?
    `).bind(cycle.id, count).all();

    return plpJson({ tickets, draw_date: cycle.draw_date });
  }

  // POST /api/v2/generate-multi-strategy
  if (path === '/api/v2/generate-multi-strategy' && request.method === 'POST') {
    const body = await request.json().catch(() => ({}));
    const count = Math.min(Math.max(1, parseInt(body.count ?? 5)), 20);

    const cycle = await db.prepare(
      `SELECT id, draw_date FROM cycles WHERE lottery_id=? AND status='generated' ORDER BY draw_date ASC LIMIT 1`
    ).bind(GAME).first();

    if (!cycle) return plpJson({ tickets: [], draw_date: null });

    const { results: tickets } = await db.prepare(`
      SELECT n1, n2, n3, n4, n5, extra, strategy_id AS strategy, confidence
      FROM tickets WHERE cycle_id=? ORDER BY confidence DESC LIMIT ?
    `).bind(cycle.id, count).all();

    return plpJson({
      tickets: tickets.map(t => ({
        numbers: [t.n1, t.n2, t.n3, t.n4, t.n5],
        powerball: t.extra,
        strategy: t.strategy,
        confidence: t.confidence,
      })),
      draw_date: cycle.draw_date,
    });
  }

  // GET /api/v2/analytics/context
  if (path === '/api/v2/analytics/context' && request.method === 'GET') {
    const [hotCold, { results: strats }, drawCount] = await Promise.all([
      calcHotCold(db, 100),
      db.prepare(`
        SELECT s.id AS strategy_id, s.current_weight AS weight,
               COALESCE(agg.avg_roi, 0) AS roi_trend
        FROM strategies s
        LEFT JOIN (
          SELECT strategy_id, AVG(roi) AS avg_roi
          FROM strategy_stats WHERE lottery_id=? GROUP BY strategy_id
        ) agg ON agg.strategy_id = s.id
        WHERE s.lottery_id=? AND s.status != 'archived'
        ORDER BY s.current_weight DESC
      `).bind(GAME, GAME).all(),
      db.prepare(`SELECT COUNT(*) AS total FROM draws WHERE lottery_id=?`).bind(GAME).first(),
    ]);

    return plpJson({
      success: true,
      from_cache: false,
      data: {
        hot_numbers: hotCold.hot_numbers,
        cold_numbers: hotCold.cold_numbers,
        draws_analyzed: hotCold.draws_analyzed,
        momentum_trends: strats.map(s => ({
          strategy: s.strategy_id,
          weight: s.weight,
          roi_trend: s.roi_trend,
        })),
        gap_patterns: [],
        data_summary: {
          total_draws_analyzed: drawCount?.total ?? 0,
          data_source: 'SHIOL+ D1 historical draws',
        },
      },
    });
  }

  // POST /api/v2/analytics/analyze-ticket
  if (path === '/api/v2/analytics/analyze-ticket' && request.method === 'POST') {
    const body = await request.json().catch(() => ({}));
    const white_balls = body.white_balls;
    const powerball = body.powerball;

    if (!Array.isArray(white_balls) || white_balls.length !== 5 || typeof powerball !== 'number') {
      return plpJson({ success: false, error: 'Need white_balls (array of 5) and powerball (number)' }, 400);
    }

    const { results: draws } = await db.prepare(
      `SELECT n1,n2,n3,n4,n5,extra FROM draws WHERE lottery_id=? ORDER BY draw_date DESC LIMIT 200`
    ).bind(GAME).all();

    const wf = new Map();
    const pf = new Map();
    for (const d of draws) {
      for (const n of [d.n1, d.n2, d.n3, d.n4, d.n5]) wf.set(n, (wf.get(n) || 0) + 1);
      pf.set(d.extra, (pf.get(d.extra) || 0) + 1);
    }

    const maxW = draws.length > 0 ? Math.max(...wf.values(), 1) : 1;
    const maxP = draws.length > 0 ? Math.max(...pf.values(), 1) : 1;

    const freqScore = white_balls.reduce((s, n) => s + (wf.get(n) || 0), 0) / (5 * maxW);
    const pbScore = (pf.get(powerball) || 0) / maxP;

    // Range diversity: how spread across low (1-23), mid (24-46), high (47-69)
    const low  = white_balls.filter(n => n <= 23).length;
    const mid  = white_balls.filter(n => n > 23 && n <= 46).length;
    const high = white_balls.filter(n => n > 46).length;
    const divScore = 1 - (Math.abs(low - mid) + Math.abs(mid - high) + Math.abs(low - high)) / 10;

    const total = Math.round(Math.min(100, Math.max(0, freqScore * 50 + pbScore * 25 + divScore * 25)));

    return plpJson({
      success: true,
      data: {
        total_score: total,
        details: {
          frequency_score: Math.round(freqScore * 100),
          powerball_score: Math.round(pbScore * 100),
          diversity_score: Math.round(divScore * 100),
        },
        recommendation: total >= 70 ? 'Strong combination' : total >= 50 ? 'Moderate combination' : 'Low frequency combination',
        draws_analyzed: draws.length,
      },
    });
  }

  // Any other /api/v2/* route that isn't implemented
  return plpJson({ error: 'Not found' }, 404);
}
