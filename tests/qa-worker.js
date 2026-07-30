import { handlePresentationAPI } from '../src/presentation-api.js';

const PRODUCTION = 'https://shiol-plus.orlandob.workers.dev';

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      const response = await handlePresentationAPI(url.pathname, url, env);
      if (response) return response;
      if (url.pathname.startsWith('/api/')) {
        const upstream = new URL(url.pathname + url.search, PRODUCTION);
        return fetch(upstream, { headers: { Accept: 'application/json' } });
      }
      return env.ASSETS.fetch(request);
    } catch (error) {
      return new Response(JSON.stringify({ error: error.message }), {
        status: 500,
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
      });
    }
  },
};
