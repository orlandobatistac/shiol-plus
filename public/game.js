/**
 * SHIOL+ v9 — Frontend App (dashboard de detalle de UN juego)
 * Llama al Worker API y renderiza el dashboard para el juego dado en
 * `?game=` de la URL (ej. game.html?game=mega_millions). Sin ese parámetro,
 * cae a 'powerball' por compatibilidad.
 *
 * En dev: el Worker sirve desde localhost via `wrangler dev`
 * En prod: mismo origen (shiol-plus.orlandob.workers.dev / shiolplus.com)
 */

const API  = ''; // mismo origen — Worker maneja /api/*
const GAME = new URLSearchParams(location.search).get('game') || 'powerball';

// ── Fetch helpers ──────────────────────────────────────────
async function api(path) {
  try {
    const res = await fetch(API + path);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.error('API error:', path, e);
    return null;
  }
}

// ── Format helpers ─────────────────────────────────────────
const fmt$ = n => n >= 1_000_000
  ? '$' + (n / 1_000_000).toFixed(1) + 'M'
  : n >= 1_000
    ? '$' + (n / 1_000).toFixed(0) + 'K'
    : '$' + n.toLocaleString();

const fmtROI = r => {
  const pct = (r * 100).toFixed(1);
  const cls = r >= 0 ? 'pos' : 'neg';
  return `<span class="${cls}">${r >= 0 ? '+' : ''}${pct}%</span>`;
};

const statusPill = s => {
  const map = {
    active: 'pill-active',
    probation: 'pill-probation',
    archived: 'pill-archived',
  };
  return `<span class="pill ${map[s] || 'pill-active'}">${s}</span>`;
};

const titleCase = s => s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

function ballsHTML(numbers, extra) {
  return numbers.map(n => `<span class="ball white">${n}</span>`).join('') +
    (extra != null ? `<span class="ball pb">${extra}</span>` : '');
}

// ── Identidad del juego (nombre, título de página, footer) ──
// Un solo fetch de /api/games se reutiliza acá y en renderCountdown() para
// no pedir la lista dos veces.
let gameInfoPromise = null;
function getGameInfo() {
  if (!gameInfoPromise) {
    gameInfoPromise = api('/api/games').then(games => {
      const g = games && games.find(g => g.id === GAME);
      return g || { id: GAME, name: titleCase(GAME), draw_days: 'mon,wed,sat', active: false };
    });
  }
  return gameInfoPromise;
}

async function renderGameIdentity() {
  const game = await getGameInfo();
  document.title = `SHIOL+ · ${game.name}`;
  const logoGameEl = document.getElementById('logo-game');
  if (logoGameEl) logoGameEl.textContent = `· ${game.name}`;
  const footer = document.getElementById('page-footer');
  if (footer) {
    const days = game.draw_days.split(',').map(d => titleCase(d)).join('/');
    footer.innerHTML = `<p>SHIOL+ v9 · Strategy Analytics Engine · Data updated after each ${game.name} draw (${days})</p>`;
  }
}

// ── Latest Draw ────────────────────────────────────────────
async function renderDraw() {
  const data = await api(`/api/draws?game=${GAME}&limit=1`);
  if (!data || !data.length) return;

  const d = data[0];
  document.getElementById('draw-balls').innerHTML =
    ballsHTML([d.n1, d.n2, d.n3, d.n4, d.n5], d.pb);
  document.getElementById('draw-date').textContent = d.draw_date;
}

// ── Countdown to next draw ──────────────────────────────────
// Calcula el próximo sorteo en hora del Este (America/New_York) a partir de
// draw_days (viene de /api/games, ej. "mon,wed,sat") y una hora fija de sorteo
// (~22:59 ET, igual que asume src/worker.js para el cron). No usa librerías de
// zona horaria — para un hobby project con margen de minutos es suficiente;
// puede desviarse por unos minutos justo en el cambio de horario de verano.
const ET_TZ = 'America/New_York';
const DRAW_HOUR_ET = 22;
const DRAW_MIN_ET = 59;
const DAY_ABBR = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };

function getEtNowParts() {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: ET_TZ, hourCycle: 'h23',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', weekday: 'short',
  });
  const parts = Object.fromEntries(fmt.formatToParts(new Date()).map(p => [p.type, p.value]));
  return {
    year: +parts.year, month: +parts.month, day: +parts.day,
    hour: +parts.hour, minute: +parts.minute, second: +parts.second,
    weekday: DAY_ABBR[parts.weekday.toLowerCase().slice(0, 3)],
  };
}

function nextDrawDate(drawDayAbbrs) {
  const targets = new Set(drawDayAbbrs.map(d => DAY_ABBR[d.trim().toLowerCase()]));
  const now = new Date();
  const et = getEtNowParts();

  // offset entre "ahora real" (UTC) y "ahora en ET interpretado como si fuera UTC"
  const etNowAsUTC = Date.UTC(et.year, et.month - 1, et.day, et.hour, et.minute, et.second);
  const offsetMs = now.getTime() - etNowAsUTC;

  for (let addDays = 0; addDays <= 7; addDays++) {
    const weekday = (et.weekday + addDays) % 7;
    if (!targets.has(weekday)) continue;
    const targetWallAsUTC = Date.UTC(et.year, et.month - 1, et.day + addDays, DRAW_HOUR_ET, DRAW_MIN_ET, 0);
    const targetRealUTC = targetWallAsUTC + offsetMs;
    if (targetRealUTC > now.getTime()) return new Date(targetRealUTC);
  }
  return null;
}

let countdownTimer = null;

async function renderCountdown() {
  const game = await getGameInfo();
  const drawDays = game.draw_days.split(',');

  const label = document.getElementById('next-draw-label');
  label.textContent = `${game.name} · ${drawDays.map(d => titleCase(d)).join('/')} · 10:59 PM ET`;

  function tick() {
    const target = nextDrawDate(drawDays);
    if (!target) return;
    const diff = Math.max(0, target.getTime() - Date.now());

    const days = Math.floor(diff / 86400000);
    const hours = Math.floor((diff % 86400000) / 3600000);
    const mins = Math.floor((diff % 3600000) / 60000);
    const secs = Math.floor((diff % 60000) / 1000);

    document.getElementById('cd-days').textContent = String(days);
    document.getElementById('cd-hours').textContent = String(hours).padStart(2, '0');
    document.getElementById('cd-mins').textContent = String(mins).padStart(2, '0');
    document.getElementById('cd-secs').textContent = String(secs).padStart(2, '0');
  }

  tick();
  if (countdownTimer) clearInterval(countdownTimer);
  countdownTimer = setInterval(tick, 1000);
}

// ── Current Jackpot (real, vía /api/jackpot -- ver worker.js y
// engine/pipeline/fetch_jackpot.py) ──────────────────────────
async function renderJackpot() {
  const amountEl = document.getElementById('jackpot-amount');
  const subEl = document.getElementById('jackpot-sub');

  const data = await api(`/api/jackpot?game=${GAME}`);
  if (!data || !data.found) {
    amountEl.textContent = '—';
    subEl.textContent = 'No estimate available';
    return;
  }

  amountEl.textContent = fmt$(data.amount);
  const cash = `Cash value ${fmt$(data.cash_value)}`;
  // `stale` = el scraper viene fallando su validador de sanidad hace rato
  // (ver refreshJackpot() en worker.js) -- se sigue mostrando el último
  // valor bueno, pero avisando que puede estar desactualizado.
  subEl.textContent = data.stale ? `${cash} — estimate may be outdated` : `${cash}, next draw`;
}

// ── Sparkline (mini gráfico de tendencia de peso) ───────────
function sparklineSVG(values) {
  if (!values || values.length < 2) return '<span class="spark-empty">—</span>';

  const w = 72, h = 26, pad = 3;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = (max - min) || 1;
  const step = (w - pad * 2) / (values.length - 1);

  const points = values.map((v, i) => {
    const x = pad + i * step;
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');

  const trendUp = values[values.length - 1] >= values[0];
  const color = trendUp ? 'var(--green)' : 'var(--red)';

  return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
    <polyline points="${points}" fill="none" style="stroke:${color};stroke-width:2;stroke-linecap:round;stroke-linejoin:round" />
  </svg>`;
}

async function renderSparklines(strategyIds) {
  const histories = await Promise.all(
    strategyIds.map(id => api(`/api/history?game=${GAME}&strategy=${id}&limit=12`))
  );

  strategyIds.forEach((id, i) => {
    const cell = document.getElementById(`spark-${id}`);
    if (!cell) return;
    const rows = histories[i];
    if (!rows || !rows.length) {
      cell.innerHTML = '<span class="spark-empty">—</span>';
      return;
    }
    const weights = rows.slice().reverse().map(r => r.weight_after);
    cell.innerHTML = sparklineSVG(weights);
  });
}

// ── Strategy Rankings ────────────────────────────────────────
async function renderStrategies() {
  const data = await api(`/api/strategies?game=${GAME}`);
  const tbody = document.getElementById('strategies-body');

  if (!data || !data.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="loading">No strategy data yet.</td></tr>';
    return;
  }

  const maxWeight = Math.max(...data.map(s => s.current_weight));

  tbody.innerHTML = data.map((s, i) => {
    const fillPct = maxWeight > 0 ? (s.current_weight / maxWeight * 100).toFixed(1) : 0;
    const name = titleCase(s.name);

    return `
      <tr>
        <td style="color:var(--muted)">${i + 1}</td>
        <td>
          <div style="font-weight:600">${name}</div>
          <div style="font-size:0.75rem;color:var(--muted)">${s.description || ''}</div>
        </td>
        <td>${statusPill(s.status)}</td>
        <td>
          <div class="weight-bar-wrap">
            <div class="weight-bar"><div class="weight-fill" style="width:${fillPct}%"></div></div>
            <span class="weight-val">${s.current_weight.toFixed(4)}</span>
          </div>
        </td>
        <td id="spark-${s.id}"><span class="spark-empty">…</span></td>
        <td>${fmtROI(s.avg_roi || 0)}</td>
        <td>${s.lifetime_prize > 0 ? fmt$(s.lifetime_prize) : '—'}</td>
      </tr>`;
  }).join('');

  renderSparklines(data.map(s => s.id));
}

// ── Last Cycle ─────────────────────────────────────────────
async function renderLastCycle() {
  const data = await api(`/api/latest-cycle?game=${GAME}`);
  const tbody = document.getElementById('cycle-body');
  const meta  = document.getElementById('cycle-meta');

  if (!data || data.message) {
    tbody.innerHTML = '<tr><td colspan="8" class="loading">No cycles evaluated yet.</td></tr>';
    return;
  }

  const { cycle, strategy_results } = data;
  meta.textContent = `Draw: ${cycle.draw_date} · ${cycle.n1}-${cycle.n2}-${cycle.n3}-${cycle.n4}-${cycle.n5} PB:${cycle.pb}`;

  if (!strategy_results || !strategy_results.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="loading">No strategy results in this cycle.</td></tr>';
    return;
  }

  tbody.innerHTML = strategy_results.map(r => {
    const name = titleCase(r.strategy_id);
    const delta = (r.weight_after - r.weight_before);
    const deltaStr = `<span class="${delta >= 0 ? 'pos' : 'neg'}">${delta >= 0 ? '+' : ''}${delta.toFixed(4)}</span>`;

    return `
      <tr>
        <td>${name}</td>
        <td>${r.tickets_count}</td>
        <td>${r.matches_3 || 0}</td>
        <td>${r.matches_4 || 0}</td>
        <td>${r.matches_5 || 0}</td>
        <td>${r.total_prize > 0 ? fmt$(r.total_prize) : '—'}</td>
        <td>${fmtROI(r.roi)}</td>
        <td>${deltaStr}</td>
      </tr>`;
  }).join('');
}

// ── Hall of Wins ───────────────────────────────────────────
// Sesión 21: /api/wins ahora devuelve { total_amount, total_count, wins }
// -- el total es un SUM() real de TODA la tabla (ya no solo lo visible),
// porque `wins` se llena automático para cualquier premio desde esta sesión
// y puede tener muchas más filas que el LIMIT de la lista.
async function renderWins() {
  const data = await api(`/api/wins?game=${GAME}`);
  const grid = document.getElementById('wins-grid');
  const totalEl = document.getElementById('wins-total');

  if (!data || !data.total_count) {
    grid.innerHTML = '<p style="color:var(--muted);font-style:italic">No recorded wins yet. The algorithm is hunting... 🎯</p>';
    totalEl.textContent = '';
    return;
  }

  const { total_amount, total_count, wins } = data;
  totalEl.innerHTML = `<span class="wins-total-amount">${fmt$(total_amount)}</span> won across ${total_count} recorded win${total_count === 1 ? '' : 's'}`;

  grid.innerHTML = wins.map(w => {
    const isJackpot = w.prize_level === 'jackpot';
    const amount = w.prize_amount > 0 ? fmt$(w.prize_amount) : 'Jackpot';
    const levelLabel = w.prize_level.replace(/([+])/g, ' $1').replace(/_/g, ' ').toUpperCase();

    return `
      <div class="win-card ${isJackpot ? 'jackpot' : ''}">
        <div class="prize-level">${levelLabel} ${w.verified ? '✓' : ''}</div>
        <div class="prize-amount">${amount}</div>
        <div class="win-meta">
          <span>📅 ${w.draw_date || w.created_at?.slice(0, 10) || '—'}</span>
          ${w.strategy_id ? `<span>🧠 ${titleCase(w.strategy_id)}</span>` : ''}
          ${w.notes ? `<span>📝 ${w.notes}</span>` : ''}
        </div>
      </div>`;
  }).join('');
}

// ── Ranking Podium (sesión 23 -- reemplaza el Scoreboard separado) ──
// "¿Quién va ganando?" en lenguaje simple: top 3 por $ ganado / win rate real,
// mismo endpoint que antes alimentaba el Scoreboard (/api/ticket-performance,
// sesión 21). Las 8 estrategias completas con weight/ROI técnico quedan en el
// <details> de abajo (ver renderStrategies()) -- ya no se duplica la misma
// información en dos tablas distintas.
async function renderRankingPodium() {
  const data = await api(`/api/ticket-performance?game=${GAME}`);
  const podium = document.getElementById('podium');

  if (!data || !data.length) {
    podium.innerHTML = '<p style="color:var(--muted);font-style:italic">No evaluated tickets yet — check back after the next draw.</p>';
    return;
  }

  const medals = ['🥇', '🥈', '🥉'];
  podium.innerHTML = data.slice(0, 3).map((s, i) => {
    const rate = s.win_rate || 0;
    const sub = rate > 0
      ? `Wins a prize on ${rate.toFixed(1)}% of tickets played`
      : 'No prizes yet';
    return `
      <div class="podium-row ${i === 0 ? 'podium-top' : ''}">
        <span class="podium-rank">${medals[i]}</span>
        <div class="podium-info">
          <div class="podium-name">${titleCase(s.strategy_id)}</div>
          <div class="podium-sub">${sub}</div>
        </div>
        <div class="podium-amount">${s.total_won > 0 ? fmt$(s.total_won) : '—'}</div>
      </div>`;
  }).join('');
}

// ── Info tooltips (glosario simple, sesión 23) ──────────────
// El texto de cada tooltip vive directo en el HTML (.info-popover) -- acá
// solo se maneja el toggle de abrir/cerrar al click, y cerrar cualquier otro
// popover abierto para que no queden varios abiertos a la vez.
function initInfoTooltips() {
  document.addEventListener('click', e => {
    const icon = e.target.closest('.info-icon');
    document.querySelectorAll('.info-popover.open').forEach(p => {
      if (!icon || p !== icon.nextElementSibling) p.classList.remove('open');
    });
    if (icon) icon.nextElementSibling?.classList.toggle('open');
  });
}

// ── Next Draw Tickets + Modal (sesión 21) ───────────────────
// 8 cards compactas (una por estrategia); click abre un modal con las 20
// bolitas de esa estrategia para el próximo sorteo, ordenadas por
// confidence de mayor a menor (ver /api/upcoming-tickets en worker.js).
let strategyNamesCache = null;

async function renderNextTickets() {
  const strategies = await api(`/api/strategies?game=${GAME}`);
  const grid = document.getElementById('next-tickets-grid');

  if (!strategies || !strategies.length) {
    grid.innerHTML = '<p style="color:var(--muted);font-style:italic">No strategies to show.</p>';
    return;
  }
  strategyNamesCache = Object.fromEntries(strategies.map(s => [s.id, titleCase(s.id)]));

  const previews = await Promise.all(
    strategies.map(s => api(`/api/upcoming-tickets?game=${GAME}&strategy=${s.id}`))
  );

  grid.innerHTML = strategies.map((s, i) => {
    const p = previews[i];
    const top = p && p.found && p.tickets.length ? p.tickets[0] : null;
    const preview = top
      ? ballsHTML([top.n1, top.n2, top.n3, top.n4, top.n5], top.extra)
      : '<span class="stc-empty">Not generated yet</span>';

    return `
      <button class="strategy-ticket-card" data-strategy="${s.id}" ${top ? '' : 'disabled'}>
        <div class="stc-head">
          <span class="stc-name">${titleCase(s.id)}</span>
          <span class="stc-weight">${s.current_weight.toFixed(3)}</span>
        </div>
        <div class="stc-preview">${preview}</div>
        <div class="stc-cta">${top ? 'View all 20 →' : '—'}</div>
      </button>`;
  }).join('');

  grid.querySelectorAll('.strategy-ticket-card:not([disabled])').forEach(card => {
    card.addEventListener('click', () => openTicketsModal(card.dataset.strategy));
  });
}

async function openTicketsModal(strategyId) {
  const overlay = document.getElementById('tickets-modal-overlay');
  const title   = document.getElementById('tickets-modal-title');
  const sub     = document.getElementById('tickets-modal-sub');
  const list    = document.getElementById('tickets-modal-list');

  title.textContent = strategyNamesCache?.[strategyId] || titleCase(strategyId);
  sub.textContent = 'Loading tickets…';
  list.innerHTML = '';
  overlay.classList.add('open');

  const data = await api(`/api/upcoming-tickets?game=${GAME}&strategy=${strategyId}`);
  if (!data || !data.found || !data.tickets.length) {
    sub.textContent = 'No tickets generated yet for the next draw.';
    return;
  }

  sub.textContent = `20 tickets for ${data.draw_date} — sorted best to worst by model confidence`;
  list.innerHTML = data.tickets.map((t, i) => `
    <div class="ticket-row">
      <span class="ticket-rank">#${i + 1}</span>
      <div class="ticket-balls">${ballsHTML([t.n1, t.n2, t.n3, t.n4, t.n5], t.extra)}</div>
      <span class="ticket-confidence">${((t.confidence ?? 0) * 100).toFixed(0)}%</span>
    </div>`).join('');
}

function closeTicketsModal() {
  document.getElementById('tickets-modal-overlay').classList.remove('open');
}

function initTicketsModal() {
  document.getElementById('tickets-modal-close').addEventListener('click', closeTicketsModal);
  document.getElementById('tickets-modal-overlay').addEventListener('click', e => {
    if (e.target.id === 'tickets-modal-overlay') closeTicketsModal();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeTicketsModal();
  });
}

// ── Nav highlight on scroll ────────────────────────────────
function initScrollSpy() {
  const sections = document.querySelectorAll('section[id], .draw-banner[id]');
  const links    = document.querySelectorAll('.nav-link');

  const observer = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        const id = e.target.id;
        links.forEach(a => {
          a.classList.toggle('active', a.getAttribute('href') === '#' + id);
        });
      }
    });
  }, { threshold: 0.4 });

  sections.forEach(s => observer.observe(s));
}

// ── Boot ───────────────────────────────────────────────────
(async function init() {
  initTicketsModal();
  initInfoTooltips();
  await Promise.all([
    renderGameIdentity(),
    renderCountdown(),
    renderJackpot(),
    renderDraw(),
    renderRankingPodium(),
    renderStrategies(),
    renderNextTickets(),
    renderLastCycle(),
    renderWins(),
  ]);
  initScrollSpy();
})();
