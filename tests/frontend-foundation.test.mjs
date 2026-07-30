import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const root = new URL('../', import.meta.url);
const gameHtml = await readFile(new URL('public/game.html', root), 'utf8');
const legalHtml = await readFile(new URL('public/legal.html', root), 'utf8');
const homeHtml = await readFile(new URL('public/index.html', root), 'utf8');
const gameJs = await readFile(new URL('public/game.js', root), 'utf8');
const homeJs = await readFile(new URL('public/home.js', root), 'utf8');
const css = await readFile(new URL('public/styles.css', root), 'utf8');

test('desktop and mobile navigation expose the four approved report stages', () => {
  const expected = ['#overview', '#draw-history', '#rankings', '#next-analysis'];
  for (const href of expected) {
    const matches = gameHtml.match(new RegExp(`href="${href}"`, 'g')) || [];
    assert.ok(matches.length >= 2, `${href} must appear in desktop and mobile navigation`);
  }
  assert.doesNotMatch(gameHtml, /href="#wins" class="nav-link"/);
  assert.doesNotMatch(gameHtml, /href="#next-tickets" class="nav-link"/);
});

test('Phase 2 overview uses the aggregate contract and exposes lifetime context', () => {
  assert.match(gameJs, /api\('\/api\/overview\?game=' \+ GAME\)/);
  assert.match(homeJs, /api\('\/api\/overview\?game=' \+ gameId\)/);
  assert.doesNotMatch(homeJs, /api\('\/api\/wins\?game='/);
  assert.match(gameHtml, /id="overview-total-won"/);
  assert.match(gameHtml, /id="overview-draws"/);
  assert.match(gameHtml, /id="overview-leader"/);
  assert.match(gameHtml, /href="#draw-history">View past analyses/);
  assert.match(css, /\.performance-strip/);
});

test('each approved report stage has one labelled section', () => {
  const stages = ['overview', 'draw-history', 'rankings', 'next-analysis'];
  for (const id of stages) {
    assert.equal((gameHtml.match(new RegExp(`id="${id}"`, 'g')) || []).length, 1);
  }
  assert.match(gameHtml, /id="draw-history"[\s\S]*id="history-body"/);
});

test('literal game.js element references exist in game.html', () => {
  const ids = [...gameJs.matchAll(/getElementById\('([^']+)'\)/g)].map(match => match[1]);
  const missing = [...new Set(ids)].filter(id =>
    !gameHtml.includes(`id="${id}"`) && !gameJs.includes(`id="${id}"`)
  );
  assert.deepEqual(missing, []);
});

test('Phase 3 exposes paginated history and an accessible four-tab analysis dialog', () => {
  assert.match(gameJs, /\/api\/analyses\?game=/);
  assert.match(gameJs, /\/api\/analyses\/.*encodeURIComponent/);
  assert.match(gameHtml, /id="history-prev"/);
  assert.match(gameHtml, /id="history-next"/);
  assert.match(gameHtml, /id="analysis-modal-overlay" aria-hidden="true"/);
  assert.match(gameHtml, /role="dialog" aria-modal="true"/);
  for (const tab of ['summary', 'strategies', 'combinations', 'distribution']) {
    assert.match(gameHtml, new RegExp(`data-panel="${tab}"`));
  }
  assert.match(gameJs, /analysis-strategy-filter/);
  assert.match(gameJs, /analysis-result-filter/);
  assert.match(gameJs, /value="winning" selected>Winning combinations/);
  assert.match(gameJs, /event\.key === 'Escape'/);
  assert.match(css, /\.analysis-modal-card/);
  assert.match(css, /\.analysis-combination-row\.is-winning/);
});

test('Phase 4 uses the lifetime ranking contract and keeps technical metrics secondary', () => {
  assert.match(gameJs, /api\('\/api\/strategy-rankings\?game=' \+ GAME\)/);
  assert.doesNotMatch(gameJs, /api\('\/api\/ticket-performance\?game='/);
  assert.match(gameHtml, /Historical strategy ranking/);
  assert.match(gameHtml, /All evaluated draws, not the ranking inside one drawing/);
  assert.match(gameHtml, /id="rankings-coverage"/);
  assert.match(gameHtml, /View technical metrics/);
  assert.match(gameJs, /Winning combinations/);
  assert.match(gameJs, /Lifetime ROI/);
  assert.match(gameJs, /Best result/);
  assert.match(css, /\.historical-ranking-card/);
  assert.match(css, /\.historical-ranking-list\s*\{[\s\S]*?gap: 14px/);
  assert.match(css, /\.historical-ranking-card\s*\{[\s\S]*?border: 1px solid var\(--line-strong\)/);
  assert.match(css, /\.ranking-trend\.is-up/);
});

test('Phase 5 orders the next 160 combinations by a global pool position', () => {
  assert.match(gameJs, /\/api\/next-draw-analysis\?game=/);
  assert.match(gameJs, /NEXT_ANALYSIS_LIMIT = 10/);
  assert.match(gameHtml, /All 160 combinations/);
  assert.match(gameHtml, /ordered across the generated pool by raw internal score/);
  assert.match(gameHtml, /id="next-analysis-strategy"/);
  assert.match(gameHtml, /id="next-analysis-prev"/);
  assert.match(gameHtml, /id="next-analysis-next"/);
  assert.match(gameHtml, /<span>Position<\/span><span>Strategy and method/);
  assert.match(gameJs, /item\.pool_position/);
  assert.match(gameJs, /raw internal score/);
  assert.doesNotMatch(gameHtml, /id="tickets-modal-overlay"/);
  assert.doesNotMatch(gameJs, /api\('\/api\/upcoming-tickets/);
  assert.match(css, /\.next-analysis-context/);
  assert.match(css, /\.next-analysis-row/);
});

test('shared loading and skip-navigation foundations exist on both pages', () => {
  assert.match(gameHtml, /class="skip-link"/);
  assert.match(homeHtml, /class="skip-link"/);
  assert.match(gameHtml, /ui-state-loading/);
  assert.match(homeHtml, /ui-state-loading/);
  assert.match(css, /\.ui-state-error/);
  assert.match(css, /\.ui-state-empty/);
  assert.match(css, /\.filter-control/);
  assert.match(css, /\.pagination-button/);
  assert.match(css, /\.strategy-ticket-row\.is-extra\s*\{\s*display: none;/);
  assert.match(css, /\.ticket-list\.show-all \.strategy-ticket-row\.is-extra/);
});

test('Phase 6 exposes linked trust and policy content', () => {
  for (const section of ['about', 'privacy', 'terms', 'cookies', 'important-disclaimer']) {
    assert.match(legalHtml, new RegExp(`id="${section}"`));
  }
  assert.match(gameHtml, /legal\.html#about/);
  assert.match(gameHtml, /legal\.html#important-disclaimer/);
  assert.match(legalHtml, /guarantees a prize/);
  assert.match(legalHtml, /legal age and responsible-play rules/);
});

test('supplementary report links open one details modal instead of empty anchors', () => {
  assert.doesNotMatch(gameHtml, /href="#analytics-lab"/);
  assert.doesNotMatch(gameHtml, /href="#wins"/);
  assert.match(gameHtml, /data-report-details-open/);
  assert.match(gameHtml, /id="report-details-modal"/);
  assert.match(gameHtml, /More report details/);
});

test('HTML sections and CSS blocks remain balanced', () => {
  assert.equal((gameHtml.match(/<section/g) || []).length, (gameHtml.match(/<\/section>/g) || []).length);
  assert.equal((css.match(/\{/g) || []).length, (css.match(/\}/g) || []).length);
  assert.match(css, /@media \(max-width: 820px\)/);
  assert.match(css, /@media \(max-width: 560px\)/);
});
