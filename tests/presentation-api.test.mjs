import test from 'node:test';
import assert from 'node:assert/strict';

import { handlePresentationAPI } from '../src/presentation-api.js';

const GAME = {
  id: 'powerball',
  name: 'Powerball',
  draw_days: 'mon,wed,sat',
  white_ball_count: 5,
  white_ball_max: 69,
  extra_ball_name: 'Powerball',
  extra_ball_max: 26,
  active: 1,
};

class FakeStatement {
  constructor(db, sql) {
    this.db = db;
    this.sql = sql;
    this.binds = [];
  }

  bind(...values) {
    this.binds = values;
    return this;
  }

  async first() {
    if (!this.db.firstResults.length) throw new Error(`Unexpected first(): ${this.sql}`);
    return this.db.firstResults.shift();
  }

  async all() {
    if (!this.db.allResults.length) throw new Error(`Unexpected all(): ${this.sql}`);
    return { results: this.db.allResults.shift() };
  }
}

class FakeDB {
  constructor({ first = [], all = [], batches = [] } = {}) {
    this.firstResults = [...first];
    this.allResults = [...all];
    this.batchResults = [...batches];
  }

  prepare(sql) {
    return new FakeStatement(this, sql);
  }

  async batch() {
    if (!this.batchResults.length) throw new Error('Unexpected batch()');
    return this.batchResults.shift();
  }
}

function request(path) {
  const url = new URL(`https://example.test${path}`);
  return { path: url.pathname, url };
}

async function responseJson(response) {
  return { status: response.status, body: await response.json() };
}

test('returns null for legacy routes', async () => {
  const { path, url } = request('/api/health');
  const response = await handlePresentationAPI(path, url, { DB: new FakeDB() });
  assert.equal(response, null);
});

test('overview uses full strategy history and reports partial ticket coverage', async () => {
  const db = new FakeDB({
    first: [GAME],
    batches: [[
      { results: [{ evaluated_draws: 4, evaluated_combinations: 640, total_won: 132 }] },
      { results: [{ strategy_id: 'hybrid_ensemble', name: 'Hybrid Ensemble', total_won: 32,
        evaluated_combinations: 80, evaluated_draws: 4, lifetime_roi: -0.8 }] },
      { results: [{ draw_date: '2026-07-08', n1: 12, n2: 29, n3: 37, n4: 43, n5: 55, extra: 18 }] },
      { results: [{ id: 4, draw_date: '2026-07-11', status: 'generated', tickets_total: 160,
        available_combinations: 160 }] },
      { results: [{ available_combinations: 320, covered_winning_combinations: 10 }] },
      { results: [{ amount: 457000000, cash_value: 205000000, source: 'nclottery.com',
        last_status: 'ok', last_success_at: new Date().toISOString() }] },
    ]],
  });
  const { path, url } = request('/api/overview?game=powerball');
  const { status, body } = await responseJson(await handlePresentationAPI(path, url, { DB: db }));

  assert.equal(status, 200);
  assert.equal(body.performance.total_won, 132);
  assert.equal(body.performance.total_cost, 1280);
  assert.equal(body.performance.lifetime_roi, -0.8969);
  assert.equal(body.detail_coverage.ratio, 0.5);
  assert.equal(body.top_strategy.strategy_id, 'hybrid_ensemble');
  assert.equal(body.next_draw.available_combinations, 160);
});

test('analyses hides winner metrics when ticket detail is unavailable', async () => {
  const db = new FakeDB({
    first: [GAME],
    batches: [[
      { results: [{ total: 1 }] },
      { results: [{
        cycle_id: 1, draw_date: '2026-07-01', evaluated_combinations: 160, total_won: 31,
        n1: 1, n2: 2, n3: 3, n4: 4, n5: 5, extra: 6,
        available_combinations: 0, winning_combinations: 0,
        best_match_score: null,
        best_strategy_id: 'hybrid_ensemble', best_strategy_name: 'Hybrid Ensemble',
        best_strategy_total_won: 12, best_strategy_roi: -0.7,
      }] },
    ]],
  });
  const { path, url } = request('/api/analyses?game=powerball&limit=10&offset=0');
  const { body } = await responseJson(await handlePresentationAPI(path, url, { DB: db }));

  assert.equal(body.items[0].combinations_available, false);
  assert.equal(body.items[0].detail_coverage, 0);
  assert.equal(body.items[0].winning_combinations, null);
  assert.equal(body.items[0].best_match, null);
});

test('analysis detail returns 404 for a draw SHIOL+ did not evaluate', async () => {
  const db = new FakeDB({ first: [GAME, null] });
  const { path, url } = request('/api/analyses/2026-06-30?game=powerball');
  const { status, body } = await responseJson(await handlePresentationAPI(path, url, { DB: db }));
  assert.equal(status, 404);
  assert.equal(body.error, 'evaluated analysis not found');
});

test('analysis detail returns summary, ranked strategies, combinations and distribution', async () => {
  const db = new FakeDB({
    first: [GAME, {
      id: 7, draw_date: '2026-07-08', status: 'evaluated',
      n1: 12, n2: 29, n3: 37, n4: 43, n5: 55, extra: 18,
    }],
    batches: [[
      { results: [{
        strategy_id: 'hybrid_ensemble', name: 'Hybrid Ensemble', description: 'Ensemble',
        tickets_count: 1, matches_3: 0, matches_4: 0, matches_5: 0,
        total_prize: 12, roi: -0.7, weight_before: 0.5, weight_after: 0.55,
        available_combinations: 1, winning_combinations: 1,
        best_match_score: 3,
      }] },
      { results: [{
        id: 501, strategy_id: 'hybrid_ensemble', strategy_name: 'Hybrid Ensemble',
        n1: 1, n2: 2, n3: 3, n4: 4, n5: 5, extra: 18, confidence: 0.8,
        matches_white: 1, matches_extra: 1, prize_level: 'match1+pb', prize_amount: 4,
        strategy_position: 1,
      }] },
      { results: [{
        matches_white: 1, matches_extra: 1, prize_level: 'match1+pb',
        combinations: 1, total_won: 4,
      }] },
    ]],
  });
  const { path, url } = request('/api/analyses/2026-07-08?game=powerball');
  const { status, body } = await responseJson(await handlePresentationAPI(path, url, { DB: db }));

  assert.equal(status, 200);
  assert.equal(body.summary.total_won, 12);
  assert.equal(body.summary.evaluated_combinations, 1);
  assert.equal(body.strategies[0].rank, 1);
  assert.deepEqual(body.strategies[0].best_match, { white: 1, extra: 1 });
  assert.equal(body.combinations[0].result.prize_amount, 4);
  assert.equal(body.distribution[0].combinations, 1);
});

test('strategy rankings expose partial coverage without claiming a lifetime win rate', async () => {
  const db = new FakeDB({
    first: [GAME],
    all: [[{
      strategy_id: 'hybrid_ensemble', name: 'Hybrid Ensemble', description: '', status: 'active',
      current_weight: 0.66, evaluated_draws: 4, evaluated_combinations: 80, total_won: 32,
      matches_3: 0, matches_4: 0, matches_5: 0,
      available_combinations: 40, winning_combinations: 1,
      best_match_score: 3,
      latest_total_won: 0, previous_total_won: 4, latest_roi: -1, previous_roi: -0.9,
    }]],
  });
  const { path, url } = request('/api/strategy-rankings?game=powerball');
  const { body } = await responseJson(await handlePresentationAPI(path, url, { DB: db }));
  const ranking = body.rankings[0];

  assert.equal(ranking.detail_coverage.ratio, 0.5);
  assert.equal(ranking.win_rate, null);
  assert.equal(ranking.winning_combinations, null);
  assert.equal(ranking.covered_win_rate, 2.5);
  assert.deepEqual(ranking.covered_best_match, { white: 1, extra: 1 });
  assert.equal(ranking.trend.total_won_delta, -4);
  assert.deepEqual(body.ordering.tie_breakers, ['lifetime_roi_desc', 'strategy_id_asc']);
});

test('next draw analysis assigns a global pool position by raw internal score', async () => {
  const db = new FakeDB({
    first: [GAME, { id: 9, draw_date: '2026-07-11', tickets_total: 160 }],
    batches: [[
      { results: [{ total: 160 }] },
      { results: [{
        id: 101, strategy_id: 'hybrid_ensemble', strategy_name: 'Hybrid Ensemble',
        strategy_description: 'Ensemble', pool_position: 1, strategy_position: 1,
        n1: 1, n2: 2, n3: 3, n4: 4, n5: 5, extra: 6, confidence: 0.87,
      }] },
      { results: [] },
      { results: [{ id: 'hybrid_ensemble', name: 'Hybrid Ensemble', description: 'Ensemble' }] },
    ]],
  });
  const { path, url } = request('/api/next-draw-analysis?game=powerball&limit=10&offset=0');
  const { body } = await responseJson(await handlePresentationAPI(path, url, { DB: db }));

  assert.equal(body.found, true);
  assert.equal(body.pagination.total, 160);
  assert.equal(body.ordering.type, 'pool_position_by_internal_score_desc');
  assert.equal(body.items[0].pool_position, 1);
  assert.equal(body.items[0].analytical_score, 0.87);
  assert.equal(body.items[0].score_scope, 'strategy_internal');
  assert.equal(body.strategies[0].id, 'hybrid_ensemble');
});

test('rejects invalid pagination before querying analysis data', async () => {
  const db = new FakeDB({ first: [GAME] });
  const { path, url } = request('/api/analyses?game=powerball&limit=0');
  const { status, body } = await responseJson(await handlePresentationAPI(path, url, { DB: db }));
  assert.equal(status, 400);
  assert.match(body.error, /limit/);
});
