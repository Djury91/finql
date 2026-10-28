// FinQL web UI: login, conversations, and the agent's answer streamed (Server-Sent Events).
//
// Everything shown comes from the model, the database or the documents, so it is untrusted:
// the page is built from text nodes only, nothing is parsed as HTML, and the server's
// Content-Security-Policy forbids inline script. The token lives in sessionStorage: gone when
// the tab is closed.

const TOKEN_KEY = "finql.token";

const TOOL_LABELS = {
  query_database: "Adatbázis-lekérdezés",
  search_documents: "Dokumentumkeresés",
  describe_schema: "Séma",
  get_metric_definition: "Fogalom definíciója",
};
const ROLE_LABELS = {
  branch_manager: "fiókvezető",
  analyst: "elemző",
  auditor: "auditor",
  admin: "admin",
};

const state = {
  token: readToken(),
  user: null,
  config: null,
  conversationId: null,
  abort: null, // AbortController of the answer being streamed
};

const $ = (id) => document.getElementById(id);

// --- DOM helpers ---------------------------------------------------------------------------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (name === "class") node.className = value;
    else if (name === "text") node.textContent = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function show(id, visible) {
  $(id).hidden = !visible;
}

function formatNumber(value) {
  if (typeof value === "number") return value.toLocaleString("hu-HU");
  if (value === null || value === undefined) return "–";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatDate(iso) {
  return new Date(iso).toLocaleString("hu-HU", { dateStyle: "short", timeStyle: "short" });
}

function scrollToEnd() {
  const messages = $("messages");
  messages.scrollTop = messages.scrollHeight;
}

// --- Answer text: a small, safe subset of Markdown, and [n] citation links -----------------

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g;

function inline(text, citeId) {
  const nodes = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("**")) nodes.push(el("strong", { text: token.slice(2, -2) }));
    else if (token.startsWith("`")) nodes.push(el("code", { text: token.slice(1, -1) }));
    else {
      const number = token.slice(1, -1);
      nodes.push(
        citeId
          ? el("a", { class: "cite", href: `#${citeId}-${number}`, text: `[${number}]` })
          : token,
      );
    }
    last = match.index + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function tableRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

// Paragraphs, "- " lists, "#" headings and pipe tables. Anything else stays plain text.
function renderAnswer(text, citeId) {
  const root = el("div", { class: "answer" });
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
    } else if (/^\s*[-*•]\s+/.test(line)) {
      const list = el("ul");
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        list.append(el("li", {}, inline(lines[i].replace(/^\s*[-*•]\s+/, ""), citeId)));
        i += 1;
      }
      root.append(list);
    } else if (/^#{1,6}\s/.test(line)) {
      root.append(el("p", { class: "heading" }, inline(line.replace(/^#+\s*/, ""), citeId)));
      i += 1;
    } else if (line.trim().startsWith("|") && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1] ?? "")) {
      const header = tableRow(line);
      i += 2;
      const body = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        body.push(tableRow(lines[i]));
        i += 1;
      }
      root.append(
        el(
          "div",
          { class: "table-wrap" },
          el(
            "table",
            {},
            el("thead", {}, el("tr", {}, header.map((h) => el("th", {}, inline(h, citeId))))),
            el(
              "tbody",
              {},
              body.map((row) => el("tr", {}, row.map((c) => el("td", {}, inline(c, citeId))))),
            ),
          ),
        ),
      );
    } else {
      const paragraph = [];
      while (
        i < lines.length &&
        lines[i].trim() &&
        !/^\s*[-*•]\s+/.test(lines[i]) &&
        !/^#{1,6}\s/.test(lines[i]) &&
        !lines[i].trim().startsWith("|")
      ) {
        paragraph.push(lines[i]);
        i += 1;
      }
      const p = el("p");
      paragraph.forEach((part, index) => {
        if (index > 0) p.append(el("br"));
        p.append(...inline(part, citeId));
      });
      root.append(p);
    }
  }
  return root;
}

function renderCitations(citations, citeId) {
  if (!citations?.length) return null;
  return el(
    "ol",
    { class: "citations" },
    citations.map((c) =>
      el(
        "li",
        { id: `${citeId}-${c.number}`, value: c.number },
        el(
          "details",
          {},
          el(
            "summary",
            {},
            el("strong", { text: c.title }),
            c.section ? ` – ${c.section}` : "",
            el("span", { class: "muted", text: ` (hatályos: ${c.effective_from})` }),
          ),
          c.content
            ? el("blockquote", { text: c.content })
            : el("p", { class: "muted", text: c.source_path }),
        ),
      ),
    ),
  );
}

// --- Tool calls ----------------------------------------------------------------------------

function toolInputText(name, input) {
  if (name === "query_database") return input.question;
  if (name === "search_documents") return input.query;
  if (name === "describe_schema") return input.view ?? "nézetek listája";
  if (name === "get_metric_definition") return input.name;
  return JSON.stringify(input);
}

function resultTable(columns, rows) {
  return el(
    "div",
    { class: "table-wrap" },
    el(
      "table",
      { class: "data" },
      el("thead", {}, el("tr", {}, columns.map((c) => el("th", { text: c })))),
      el(
        "tbody",
        {},
        rows.map((row) =>
          el(
            "tr",
            {},
            row.map((value) =>
              el("td", { class: typeof value === "number" ? "num" : null, text: formatNumber(value) }),
            ),
          ),
        ),
      ),
    ),
  );
}

function toolResultBody(name, isError, details) {
  const parts = [];
  if (isError) {
    parts.push(el("p", { class: "error", text: details.message ?? details.code ?? "Hiba" }));
    if (details.sql) parts.push(el("pre", { class: "sql", text: details.sql }));
    return parts;
  }
  if (name === "query_database") {
    if (details.status === "declined") {
      parts.push(el("p", { text: `Nem futott lekérdezés: ${details.explanation}` }));
      return parts;
    }
    if (details.sql) parts.push(el("pre", { class: "sql", text: details.sql }));
    if (details.columns?.length) parts.push(resultTable(details.columns, details.rows ?? []));
    const shown = details.rows?.length ?? 0;
    let note = `${formatNumber(details.row_count)} sor`;
    if (details.row_count > shown) note += `, ebből ${shown} látszik`;
    if (details.limit_reached) note += ", a LIMIT levágta: lehet több is";
    parts.push(el("p", { class: "muted", text: `${note}. Napló: #${details.query_id}` }));
  } else if (name === "search_documents") {
    if (!details.sources?.length) parts.push(el("p", { class: "muted", text: "Nincs találat." }));
    else
      parts.push(
        el(
          "ul",
          { class: "sources" },
          details.sources.map((s) =>
            el("li", {}, `[${s.number}] `, el("strong", { text: s.title }), ` – ${s.section}`),
          ),
        ),
      );
  } else if (name === "describe_schema") {
    parts.push(el("p", { text: details.view ?? (details.views ?? []).join(", ") }));
  } else if (name === "get_metric_definition") {
    parts.push(el("p", { text: details.metric }));
  }
  return parts;
}

function toolCard(name, input) {
  const status = el("span", { class: "status running", text: "fut…" });
  const body = el("div", { class: "tool-body" });
  const card = el(
    "details",
    { class: "tool" },
    el(
      "summary",
      {},
      el("span", { class: "tool-name", text: TOOL_LABELS[name] ?? name }),
      el("span", { class: "tool-input", text: toolInputText(name, input ?? {}) }),
      status,
    ),
    body,
  );
  card.finish = (isError, details, durationMs) => {
    status.className = `status ${isError ? "failed" : "ok"}`;
    status.textContent = isError ? "hiba" : durationMs != null ? `${durationMs} ms` : "kész";
    body.replaceChildren(...toolResultBody(name, isError, details ?? {}));
  };
  return card;
}

// --- Turns ---------------------------------------------------------------------------------

function userBubble(text) {
  return el("div", { class: "msg user" }, el("div", { class: "bubble", text }));
}

// One answer: draft texts and tool cards in the order they came, then the checked answer.
function assistantTurn() {
  const node = el("div", { class: "msg assistant" });
  const bubble = el("div", { class: "bubble" });
  node.append(bubble);
  let draft = null;
  return {
    node,
    text(delta) {
      if (!draft) {
        draft = el("div", { class: "draft" });
        bubble.append(draft);
      }
      draft.textContent += delta;
    },
    tool(name, input) {
      draft = null; // the text after a tool call is a new step
      const card = toolCard(name, input);
      bubble.append(card);
      return card;
    },
    answer(text, citations, id) {
      const citeId = `cite-${id}`;
      const final = [renderAnswer(text, citeId), renderCitations(citations, citeId)];
      // The streamed text of the last step is replaced: the answer's markers are checked.
      if (draft) draft.replaceWith(...final.filter(Boolean));
      else bubble.append(...final.filter(Boolean));
      draft = null;
    },
    error(message) {
      draft = null;
      bubble.append(el("p", { class: "error", role: "alert", text: message }));
    },
  };
}

function renderHistory(messages) {
  const nodes = [];
  let turn = null;
  const cards = new Map();
  for (const message of messages) {
    const content = message.content;
    if (message.role === "user") {
      nodes.push(userBubble(content.text));
      turn = assistantTurn();
      nodes.push(turn.node);
    } else if (!turn || message.role === "summary") {
      continue;
    } else if (message.role === "tool") {
      const card = cards.get(content.tool_use_id) ?? turn.tool(content.name, content.input);
      card.finish(content.is_error, content.details, content.duration_ms);
    } else if (content.error) {
      turn.error(content.message);
    } else {
      for (const block of content.blocks ?? []) {
        if (block.type === "text" && content.answer === undefined) turn.text(block.text);
        if (block.type === "tool_use") cards.set(block.id, turn.tool(block.name, block.input));
      }
      if (content.answer !== undefined) turn.answer(content.answer, content.citations, message.id);
    }
  }
  return nodes;
}

// --- API -----------------------------------------------------------------------------------

class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function api(path, { method = "GET", body, form, signal } = {}) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let payload;
  if (form) payload = new URLSearchParams(form);
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const response = await fetch(path, { method, headers, body: payload, signal });
  if (!response.ok) {
    let error = { code: "http_error", message: `Hiba: HTTP ${response.status}` };
    try {
      error = (await response.json()).error ?? error;
    } catch {
      // not our JSON error format (e.g. a proxy's page)
    }
    if (response.status === 401 && state.token) logout("Lejárt a bejelentkezés, lépj be újra.");
    throw new ApiError(response.status, error.code, error.message);
  }
  return response;
}

// The SSE wire format: blocks separated by a blank line, "event:" and "data:" fields,
// ":" comments (keep-alive pings).
async function* serverSentEvents(response) {
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value.replace(/\r\n?/g, "\n");
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let event = "message";
      const data = [];
      for (const line of block.split("\n")) {
        if (!line || line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon < 0 ? line : line.slice(0, colon);
        const fieldValue = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (field === "event") event = fieldValue;
        else if (field === "data") data.push(fieldValue);
      }
      if (data.length) yield { event, data: JSON.parse(data.join("\n")) };
    }
  }
}

// --- Session -------------------------------------------------------------------------------

function readToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function saveToken(token) {
  state.token = token;
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage blocked: the token stays in memory for this page
  }
}

function logout(message) {
  state.abort?.abort();
  saveToken(null);
  state.user = null;
  state.conversationId = null;
  showLogin(message);
}

function showLogin(message) {
  show("chat-view", false);
  show("whoami", false);
  show("login-view", true);
  const error = $("login-error");
  error.textContent = message ?? "";
  error.hidden = !message;
}

async function loginWith(username, password) {
  try {
    const response = await api("/auth/token", { method: "POST", form: { username, password } });
    saveToken((await response.json()).access_token);
    $("login-form").reset();
    await start();
  } catch (error) {
    showLogin(error.message);
  }
}

function login(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  return loginWith(form.get("username"), form.get("password"));
}

// --- Conversations -------------------------------------------------------------------------

async function loadConversationList() {
  const response = await api("/chat/conversations?limit=50");
  const conversations = await response.json();
  $("conversation-list").replaceChildren(
    ...conversations.map((c) =>
      el(
        "li",
        {},
        el(
          "button",
          {
            type: "button",
            class: c.id === state.conversationId ? "conversation-link active" : "conversation-link",
            onclick: () => openConversation(c.id),
          },
          el("span", { class: "title", text: c.title ?? "(üres beszélgetés)" }),
          el("span", { class: "muted", text: formatDate(c.updated_at) }),
        ),
      ),
    ),
  );
}

function resetMessages() {
  $("messages").replaceChildren($("empty-state"));
  show("empty-state", true);
}

function newConversation() {
  if (state.abort) return;
  state.conversationId = null;
  resetMessages();
  loadConversationList().catch(() => {});
  $("question").focus();
}

async function openConversation(id) {
  if (state.abort) return;
  const response = await api(`/chat/conversations/${id}`);
  const conversation = await response.json();
  state.conversationId = id;
  show("empty-state", false);
  $("messages").replaceChildren($("empty-state"), ...renderHistory(conversation.messages));
  scrollToEnd();
  loadConversationList().catch(() => {});
}

// --- Asking --------------------------------------------------------------------------------

function setBusy(busy) {
  $("send").disabled = busy;
  $("question").disabled = busy;
  show("stop", busy);
}

async function ask(question) {
  if (state.abort || !question.trim()) return;
  const controller = new AbortController();
  state.abort = controller;
  setBusy(true);
  show("empty-state", false);
  const messages = $("messages");
  messages.append(userBubble(question));
  const turn = assistantTurn();
  messages.append(turn.node);
  scrollToEnd();

  const cards = new Map();
  let finished = false;
  try {
    if (!state.conversationId) {
      const created = await api("/chat/conversations", { method: "POST" });
      state.conversationId = (await created.json()).id;
    }
    const response = await api(`/chat/conversations/${state.conversationId}/messages`, {
      method: "POST",
      body: { content: question },
      signal: controller.signal,
    });
    for await (const { event, data } of serverSentEvents(response)) {
      if (event === "text") turn.text(data.delta);
      else if (event === "tool_start") cards.set(data.id, turn.tool(data.name, data.input));
      else if (event === "tool_result")
        cards.get(data.id)?.finish(data.is_error, data.details, data.duration_ms);
      else if (event === "done") {
        turn.answer(data.answer, data.citations, data.message_id);
        finished = true;
      } else if (event === "error") {
        turn.error(data.message);
        finished = true;
      }
      scrollToEnd();
    }
    if (!finished) turn.error("A válasz megszakadt.");
  } catch (error) {
    if (error.name === "AbortError") turn.error("Leállítva.");
    else if (error.status !== 401) turn.error(error.message);
  } finally {
    state.abort = null;
    setBusy(false);
    scrollToEnd();
    if (state.token) loadConversationList().catch(() => {});
    $("question").focus();
  }
}

function submitQuestion(event) {
  event.preventDefault();
  const input = $("question");
  const question = input.value;
  input.value = "";
  ask(question);
}

// --- Start ---------------------------------------------------------------------------------

function renderConfig(config) {
  show("demo-banner", config.demo_mode);
  $("examples").replaceChildren(
    ...config.examples.map((q) =>
      el("button", { type: "button", class: "example", text: q, onclick: () => ask(q) }),
    ),
  );
  show("demo-users", config.demo_users.length > 0);
  if (config.demo_password) {
    renderPublicDemoUsers(config.demo_users, config.demo_password);
    return;
  }
  $("demo-user-list").replaceChildren(
    ...config.demo_users.map((u) =>
      el(
        "li",
        {},
        el(
          "button",
          {
            type: "button",
            class: "link",
            onclick: () => {
              $("login-form").elements.username.value = u.email;
              $("login-form").elements.password.focus();
            },
          },
          u.email,
        ),
        el("span", {
          class: "muted",
          text: ` ${ROLE_LABELS[u.role] ?? u.role}${u.branch ? ` (${u.branch})` : ""}`,
        }),
      ),
    ),
  );
}

// Public demo (FINQL_PUBLIC_DEMO): the password is no secret, so one click logs in. The roles
// side by side show the row-level security: the same question, different rows.
function renderPublicDemoUsers(users, password) {
  $("demo-users-hint").replaceChildren(
    "Nyilvános demó: lépj be egy kattintással. A fiókvezető csak a saját fiókja adatait látja, " +
      "az elemző az egész bankét. Szerepkört a kijelentkezéssel válthatsz.",
  );
  const order = ["branch_manager", "analyst", "auditor", "admin"];
  const sorted = [...users].sort((a, b) => order.indexOf(a.role) - order.indexOf(b.role));
  $("demo-user-list").classList.add("demo-logins");
  $("demo-user-list").replaceChildren(
    ...sorted.map((u) =>
      el(
        "li",
        {},
        el(
          "button",
          { type: "button", class: "demo-login", onclick: () => loginWith(u.email, password) },
          el("span", { text: u.name }),
          el("span", {
            class: "muted",
            text: `${ROLE_LABELS[u.role] ?? u.role}${u.branch ? ` (${u.branch})` : ""}`,
          }),
        ),
      ),
    ),
  );
  $("demo-password").replaceChildren(
    "Az API-hoz (/docs) ugyanezek a felhasználók, e-mail-címmel, a közös jelszó: ",
    el("code", { text: password }),
  );
  show("demo-password", true);
}

async function start() {
  if (!state.token) {
    showLogin();
    return;
  }
  try {
    state.user = await (await api("/auth/me")).json();
  } catch (error) {
    if (error.status !== 401) showLogin(error.message);
    return;
  }
  $("user-name").textContent = state.user.full_name;
  $("user-role").textContent = ROLE_LABELS[state.user.role] ?? state.user.role;
  show("login-view", false);
  show("whoami", true);
  show("chat-view", true);
  newConversation();
}

async function init() {
  $("login-form").addEventListener("submit", login);
  $("logout").addEventListener("click", () => logout());
  $("new-conversation").addEventListener("click", newConversation);
  $("composer").addEventListener("submit", submitQuestion);
  $("stop").addEventListener("click", () => state.abort?.abort());
  $("question").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("composer").requestSubmit();
    }
  });
  try {
    state.config = await (await fetch("/web/config")).json();
    renderConfig(state.config);
  } catch {
    // the page works without the hints
  }
  await start();
}

init();
