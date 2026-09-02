/* The public "Ask the map" proxy: a Cloudflare Worker routed on
 * rainchecknyc.com/api/chat*, so the page's relative fetch("/api/chat") works
 * IDENTICALLY on the public host and on `make web` (src/raincheck/webserve.py holds the
 * local twin - keep the two contracts in step: GET = the free health probe, POST = the
 * forward, same status codes).
 *
 * The key lives as the Worker secret DEEPSEEK_API_KEY (bound at deploy by
 * scripts/deploy-chat-worker.sh), never in this file and never in a response.
 *
 * EXPOSURE, stated plainly: this is a public endpoint that spends prepaid DeepSeek
 * credit. The Origin check binds browsers only (curl sends none and passes), the body
 * shape is forced (model pinned, fields allowlisted) so it cannot proxy arbitrary
 * OpenAI-style traffic, and the blast radius is bounded by the DeepSeek account being
 * PREPAID. If abuse ever shows in the dashboard: add Cloudflare rate-limiting on the
 * route, or a Turnstile token check here - deliberately not built until measured need.
 */

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj),
    { status, headers: { "Content-Type": "application/json" } });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname !== "/api/chat") return json({ error: "not found" }, 404);
    if (req.method === "GET")
      return json({ proxy: true, key: Boolean(env.DEEPSEEK_API_KEY) });
    if (req.method !== "POST") return json({ error: "method not allowed" }, 405);
    const origin = req.headers.get("Origin");
    if (origin && origin !== "https://rainchecknyc.com" && origin !== "https://www.rainchecknyc.com")
      return json({ error: "cross-origin refused" }, 403);
    if (!env.DEEPSEEK_API_KEY) return json({ error: "no_key" }, 503);
    const text = await req.text();
    if (text.length > 262144) return json({ error: "body too large" }, 413);
    let body;
    try { body = JSON.parse(text); } catch { return json({ error: "invalid JSON" }, 400); }
    if (!Array.isArray(body.messages) || body.messages.length > 80)
      return json({ error: "messages must be an array of at most 80" }, 400);
    // the forward is REBUILT, never passed through: the model is pinned and only the
    // three fields the page sends survive - a stray max_tokens/stream/model from a
    // non-page client is dropped, so this cannot serve as a general DeepSeek proxy
    const res = await fetch("https://api.deepseek.com/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json",
                 "Authorization": `Bearer ${env.DEEPSEEK_API_KEY}` },
      body: JSON.stringify({ model: "deepseek-chat", messages: body.messages,
                             tools: body.tools, tool_choice: body.tool_choice }),
    });
    // DeepSeek's own status and body pass through verbatim, the webserve contract
    return new Response(res.body, { status: res.status,
      headers: { "Content-Type": "application/json" } });
  },
};
