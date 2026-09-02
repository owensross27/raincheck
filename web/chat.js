/* "Ask the map" - a DeepSeek-powered agent that drives THIS page's own tools, never a
 * generic assistant bolted on beside it. Every capability it has is something the wiring
 * module (app.js) handed in as `registry`, and every call it makes renders as a STEP the
 * user watches happen and can click to run again - that repeatability is the product, not
 * a debug affordance.
 *
 * chat.js NEVER imports another page module (the orchestrator's rule: this file ships
 * standalone). The whole contract with the rest of the page is:
 *   - `initChat(registry)` - registry: {name: {description, parameters, run}}, an
 *     OpenAI-style function table with real functions behind it.
 *   - one endpoint: POST /api/chat (webserve.py's proxy - the only thing on this page that
 *     ever sees the DeepSeek key; chat.js never does).
 *
 * No innerHTML ever touches model- or tool-produced text in this file: every dynamic string
 * lands via `textContent`. The one `innerHTML` assignment below is the static panel shell,
 * authored entirely by this file - nothing dynamic is ever interpolated into it.
 */

const SYSTEM_PROMPT = `You are "Ask the map" on raincheck, an NYC map of rain vs bus speed.
The page has three modes - storms (a past storm's delay), history (the flood record) and
live (the current fleet) - shown through map layers you can toggle, and a static read API
you can query for the numbers behind them. Answer ONLY from what your tools return - never
invent a number, a count or a date. When a tool can put something on the map, call it rather
than only describing what the reader could click. Keep answers short; the map is the answer.`;

const MAX_ROUNDS = 8;          // total /api/chat round trips for one user message
const TOOL_RESULT_CAP = 4000;  // chars of JSON.stringify(result) sent back to the model

let registry = {};
let messages = [];             // the running conversation, sans the system prompt
let busy = false;

let launcherBtn, panelEl, logEl, formEl, textareaEl;

export function initChat(reg) {
  registry = reg || {};
  buildDom();
  wireEvents();
  // the proxy lives only in `make web`'s server - the public static host has no
  // /api/chat at all. Probe the FREE health GET (answered locally, never forwarded, so
  // a page load costs no upstream tokens) and say so on the launcher instead of letting
  // the first question die on a mystery error. A proxy without a key stays live: the
  // panel's own no_key message explains what to do.
  fetch("/api/chat")
    .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
    .then(d => { if (!d || d.proxy !== true) offline(); })
    .catch(() => offline());
}

function offline() {
  launcherBtn.disabled = true;
  launcherBtn.textContent = "Ask the map (local preview only)";
  launcherBtn.title = "The chat needs the local server: run `make web` on the repo. " +
    "This host serves static files only.";
}

// ------------------------------------------------------------------------------- the DOM
function buildDom() {
  launcherBtn = document.createElement("button");
  launcherBtn.type = "button";
  launcherBtn.id = "chat-launcher";
  launcherBtn.className = "chat-launcher";
  launcherBtn.textContent = "Ask the map";
  launcherBtn.setAttribute("aria-expanded", "false");
  document.body.append(launcherBtn);

  panelEl = document.createElement("section");
  panelEl.id = "chat-panel";
  panelEl.className = "chat-panel";
  panelEl.hidden = true;
  panelEl.setAttribute("aria-labelledby", "chat-h");
  // static shell only - nothing below is ever filled from a model or tool string
  panelEl.innerHTML = `
    <div class="chat-head">
      <h2 id="chat-h" class="chat-title">Ask the map</h2>
      <button type="button" class="chat-close" aria-label="Close chat">&times;</button>
    </div>
    <div class="chat-log" aria-live="polite"></div>
    <form class="chat-form">
      <textarea class="chat-textarea" rows="2" aria-label="Ask the map a question"
        placeholder="e.g. show the storms mode, then flag flooded stations"></textarea>
      <button type="submit" class="chat-send">Send</button>
    </form>`;
  document.body.append(panelEl);

  logEl = panelEl.querySelector(".chat-log");
  formEl = panelEl.querySelector(".chat-form");
  textareaEl = panelEl.querySelector(".chat-textarea");
}

function wireEvents() {
  launcherBtn.addEventListener("click", () => setOpen(true));
  panelEl.querySelector(".chat-close").addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panelEl.hidden) setOpen(false);
  });
  formEl.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = textareaEl.value.trim();
    if (!text || busy) return;
    textareaEl.value = "";
    send(text);
  });
  // Enter sends, Shift+Enter inserts a newline - the ordinary chat-box convention; nothing
  // else on this page has a free-text control to conflict with it.
  textareaEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      formEl.requestSubmit();
    }
  });
}

function setOpen(open) {
  panelEl.hidden = !open;
  launcherBtn.setAttribute("aria-expanded", String(open));
  if (open) textareaEl.focus();
}

function setBusy(v) {
  busy = v;
  textareaEl.disabled = v;
  formEl.querySelector(".chat-send").disabled = v;
}

// --------------------------------------------------------------------- rendering the log
function appendMsg(cls, text) {
  const div = document.createElement("div");
  div.className = `chat-msg ${cls}`;
  div.textContent = text;          // textContent only - see the file header
  logEl.append(div);
  logEl.scrollTop = logEl.scrollHeight;
  return div;
}

/** One step row PER CALL, always a fresh element - the same function renders the first run
 *  and every replay, which is what makes "click to run it again" free: nothing here
 *  distinguishes a replay from the original. Returns the row so the caller can flip it. */
function renderStep(name, args) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "chat-step chat-step-run";
  btn.title = "Run this step again";
  const nameEl = document.createElement("span");
  nameEl.className = "chat-step-name";
  nameEl.textContent = `${name}(${oneLine(args)})`;
  const stateEl = document.createElement("span");
  stateEl.className = "chat-step-state";
  stateEl.textContent = "running…";
  const sumEl = document.createElement("span");
  sumEl.className = "chat-step-summary";
  btn.append(nameEl, stateEl, sumEl);
  btn.addEventListener("click", () => executeTool(name, args));
  logEl.append(btn);
  logEl.scrollTop = logEl.scrollHeight;
  return { btn, stateEl, sumEl };
}

function finishStep(row, ok, summary) {
  row.btn.classList.remove("chat-step-run");
  row.btn.classList.add(ok ? "chat-step-ok" : "chat-step-fail");
  row.stateEl.textContent = ok ? "ok" : "fail";
  row.sumEl.textContent = summary;
  logEl.scrollTop = logEl.scrollHeight;
}

// ------------------------------------------------------------------------- string helpers
/** A short one-liner for the step row and for a failure message - NOT what is sent back to
 *  the model (see toolContent below), just what a human glances at. */
function oneLine(v) {
  if (v === undefined) return "ok";
  let s;
  try { s = typeof v === "string" ? v : JSON.stringify(v); } catch { s = String(v); }
  s = s.replace(/\s+/g, " ").trim();
  return s.length > 140 ? s.slice(0, 140) + "…" : s;
}

/** What actually goes back to the model as the `tool` message's content: the full JSON,
 *  truncated past TOOL_RESULT_CAP with a note - a route/history payload can run to
 *  megabytes (docs/read-api-contract.md), and every truncated char still costs a token. */
function toolContent(result) {
  let s;
  try { s = JSON.stringify(result); } catch { s = String(result); }
  if (s === undefined) s = "null";
  if (s.length > TOOL_RESULT_CAP)
    s = s.slice(0, TOOL_RESULT_CAP) + `… [truncated, ${s.length} chars total]`;
  return s;
}

// ----------------------------------------------------------------------- running one tool
async function executeTool(name, args) {
  const row = renderStep(name, args);
  const tool = registry[name];
  if (!tool || typeof tool.run !== "function") {
    finishStep(row, false, "unknown tool");
    return { ok: false, summary: "unknown tool" };
  }
  try {
    const result = await tool.run(args);
    const summary = oneLine(result);
    finishStep(row, true, summary);
    return { ok: true, summary, content: toolContent(result) };
  } catch (err) {
    const summary = err && err.message ? err.message : String(err);
    finishStep(row, false, summary);
    return { ok: false, summary };
  }
}

// -------------------------------------------------------------------------- the API round
function toolSpecs() {
  return Object.entries(registry).map(([name, t]) => ({
    type: "function",
    function: { name, description: t.description,
                parameters: t.parameters || { type: "object", properties: {} } },
  }));
}

async function callChat(forceFinal) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "deepseek-chat",
      messages: [{ role: "system", content: SYSTEM_PROMPT }, ...messages],
      tools: toolSpecs(),
      tool_choice: forceFinal ? "none" : "auto",
    }),
  });
  let data = null;
  try { data = await res.json(); } catch { /* an empty or non-JSON body reads as null below */ }
  if (!res.ok) {
    if (res.status === 503 && data && data.error === "no_key")
      throw new Error("No DeepSeek key configured. Add DEEPSEEK_API_KEY=<key> to " +
        "/Users/ross/raincheck/.env and restart `make web`.");
    const upstream = data && data.error && (data.error.message || data.error);
    throw new Error(typeof upstream === "string" ? upstream : `chat request failed (HTTP ${res.status})`);
  }
  return data;
}

// ------------------------------------------------------------------------------ the loop
async function send(text) {
  if (busy) return;
  setBusy(true);
  appendMsg("chat-msg-user", text);
  messages.push({ role: "user", content: text });
  try {
    await runLoop();
  } finally {
    setBusy(false);
  }
}

async function runLoop() {
  for (let round = 0; round < MAX_ROUNDS; round++) {
    const forceFinal = round === MAX_ROUNDS - 1;
    let reply;
    try {
      reply = await callChat(forceFinal);
    } catch (err) {
      // covers both a 4xx/5xx from /api/chat (DeepSeek's own error, or the no-key notice
      // above) and an outright network failure reaching it - either way the loop cannot
      // continue without a reply, so it stops here with the message on screen.
      appendMsg("chat-msg-error", err.message || String(err));
      return;
    }
    const msg = reply && reply.choices && reply.choices[0] && reply.choices[0].message;
    if (!msg) { appendMsg("chat-msg-error", "no reply from the model."); return; }
    messages.push(msg);
    if (msg.content) appendMsg("chat-msg-assistant", msg.content);
    const calls = msg.tool_calls || [];
    if (!calls.length) return;   // a text-only reply ends this turn

    for (const call of calls) {
      let args = {};
      try { args = JSON.parse(call.function.arguments || "{}"); }
      catch { /* malformed tool-call JSON from the model: run with no args rather than die */ }
      const outcome = await executeTool(call.function.name, args);
      // a failed TOOL is a result, not the end: the error goes back as the tool message
      // and the model decides what to try instead (MEASURED: the first real session died
      // twice on recoverable mistakes - a directory path, a blocked docs/ path - with
      // the answer three fields away). The step row already shows the fail; only the
      // transport (callChat above) can end the turn.
      messages.push({ role: "tool", tool_call_id: call.id,
                      content: outcome.ok ? outcome.content
                        : JSON.stringify({ error: outcome.summary }) });
    }
  }
  appendMsg("chat-msg-error", "stopped after 8 tool round-trips without a final answer.");
}
