import { handlePresentationAPI } from '../src/presentation-api.js';

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      const response = await handlePresentationAPI(url.pathname, url, env);
      return response || new Response('Not found', { status: 404 });
    } catch (error) {
      return new Response(JSON.stringify({ error: error.message }), {
        status: 500,
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
      });
    }
  },
};
