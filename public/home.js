/**
 * SHIOL+ v9 — Home (selector de juegos)
 * Lista todos los juegos que conoce SHIOL+ (vía /api/games) con un breve
 * resumen de cada uno, y linkea al dashboard de detalle (game.html?game=id)
 * para los que ya están activos.
 */

const API = ''; // mismo origen — Worker maneja /api/*

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

const fmt$ = n => n >= 1_000_000
  ? '$' + (n / 1_000_000).toFixed(1) + 'M'
  : n >= 1_000
    ? '$' + (n / 1_000).toFixed(0) + 'K'
    : '$' + n.toLocaleString();

const titleCase = s => s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

// Ícono puramente decorativo por juego -- no viene de D1 (el schema no tiene
// un campo de color/ícono por lotería), es solo un mapa chico en el cliente
// para diferenciar las cards a simple vista. Fallback genérico para
// cualquier juego futuro que no esté en la lista.
const GAME_ICON = {
  powerball: '🔴',
  mega_millions: '🟡',
};

// ── Resumen de un juego activo: top estrategia + total ganado ──
async function loadActiveGameStats(gameId) {
  const [strategies, wins] = await Promise.all([
    api(`/api/strategies?game=${gameId}`),
    api(`/api/wins?game=${gameId}`),
  ]);

  const top = strategies && strategies.length ? strategies[0] : null;
  const totalWon = wins && wins.length
    ? wins.reduce((sum, w) => sum + (w.prize_amount || 0), 0)
    : 0;

  return {
    topStrategyName: top ? titleCase(top.name) : null,
    topStrategyWeight: top ? top.current_weight : null,
    strategiesCount: strategies ? strategies.length : 0,
    totalWon,
    winsCount: wins ? wins.length : 0,
  };
}

function activeCardHTML(game, stats) {
  const icon = GAME_ICON[game.id] || '🎲';
  const days = game.draw_days.split(',').map(d => titleCase(d)).join('/');

  return `
    <a class="game-card" href="game.html?game=${game.id}">
      <div class="game-card-head">
        <span class="game-card-icon">${icon}</span>
        <div>
          <div class="game-card-title">${game.name}</div>
          <div class="game-card-days">${days}</div>
        </div>
        <span class="pill pill-active game-card-badge">active</span>
      </div>
      <div class="game-card-stats">
        <div class="game-card-stat">
          <div class="stat-label">Top Strategy</div>
          <div class="stat-value">
            ${stats.topStrategyName || '—'}
            ${stats.topStrategyWeight != null ? `<span class="stat-sub">weight ${stats.topStrategyWeight.toFixed(3)}</span>` : ''}
          </div>
        </div>
        <div class="game-card-stat">
          <div class="stat-label">Total Won</div>
          <div class="stat-value">${stats.totalWon > 0 ? fmt$(stats.totalWon) : '—'}</div>
        </div>
        <div class="game-card-stat">
          <div class="stat-label">Strategies</div>
          <div class="stat-value">${stats.strategiesCount || '—'}</div>
        </div>
      </div>
      <div class="game-card-cta">View details →</div>
    </a>`;
}

function comingSoonCardHTML(game) {
  const icon = GAME_ICON[game.id] || '🎲';
  const days = game.draw_days.split(',').map(d => titleCase(d)).join('/');

  return `
    <div class="game-card game-card-disabled">
      <div class="game-card-head">
        <span class="game-card-icon">${icon}</span>
        <div>
          <div class="game-card-title">${game.name}</div>
          <div class="game-card-days">${days}</div>
        </div>
        <span class="pill pill-archived game-card-badge">coming soon</span>
      </div>
      <div class="game-card-stats">
        <div class="game-card-stat game-card-stat-full">
          <div class="stat-value stat-muted">Not tracked yet — will appear here once activated.</div>
        </div>
      </div>
    </div>`;
}

async function renderGames() {
  const grid = document.getElementById('games-grid');
  const games = await api('/api/games');

  if (!games || !games.length) {
    grid.innerHTML = '<p style="color:var(--muted);font-style:italic">No games registered yet.</p>';
    return;
  }

  // Estadísticas de los juegos activos en paralelo (son pocos -- no hace
  // falta un endpoint agregado nuevo para esto).
  const activeGames = games.filter(g => g.active);
  const statsList = await Promise.all(activeGames.map(g => loadActiveGameStats(g.id)));
  const statsByGame = Object.fromEntries(activeGames.map((g, i) => [g.id, statsList[i]]));

  grid.innerHTML = games.map(g =>
    g.active ? activeCardHTML(g, statsByGame[g.id]) : comingSoonCardHTML(g)
  ).join('');
}

(async function init() {
  await renderGames();
})();
