// The live panel. One SSE stream from /events; every render is derived from server state.
const $ = (id) => document.getElementById(id);
const SECTIONS = ["needs", "mapping", "ask", "ops", "risks"];
const SHOWN = 4; // newest items per section; the rest fold behind "+N more"
const expanded = new Set();

let state = { state: "connecting", report: null };
const elements = new Map(); // item id -> <li>

// ---- top bar --------------------------------------------------------------------------

function renderState() {
  const shown = state.state;
  $("state").dataset.state = shown;
  $("state-text").textContent = shown;
  $("latency").textContent = state.latency_s != null ? `${state.latency_s.toFixed(1)} s` : "";
  $("model").textContent = state.model || "";
  $("end").disabled = ["connecting", "writing report", "ended"].includes(state.state);
}

function showError(message) {
  state.error = message;
  $("error").hidden = !message;
  $("error").textContent = message || "";
  $("error").title = message || "";
}

// ---- transcript -----------------------------------------------------------------------

function addTurn(turn) {
  const list = $("turns");
  const li = document.createElement("li");
  li.className = `turn ${turn.speaker}`;
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = turn.speaker === "me" ? "ME" : "CLIENT";
  li.append(who, document.createTextNode(turn.text));
  list.append(li);
  $("turns-empty").hidden = true;
  const pane = list.closest(".transcript");
  const nearBottom = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 120;
  if (nearBottom) pane.scrollTop = pane.scrollHeight;
}

// ---- board ----------------------------------------------------------------------------

function itemContent(item) {
  const box = document.createElement("div");
  box.className = "item-text";
  box.append(document.createTextNode(item.text));
  if (item.section === "mapping") {
    // One line: need → endpoint #section. The approach goes underneath, quieter.
    const code = document.createElement("span");
    code.className = item.endpoint ? "endpoint" : "endpoint none";
    code.textContent = item.endpoint || "not in docs";
    box.append(document.createTextNode(" → "), code);
    if (item.doc_ref) {
      const ref = document.createElement("a");
      ref.className = "ref";
      ref.target = "_blank";
      ref.rel = "noreferrer";
      ref.href = /^https?:/.test(item.doc_ref) ? item.doc_ref : "#";
      ref.textContent = item.doc_ref.includes("#") ? `#${item.doc_ref.split("#").pop()}` : "docs";
      ref.title = item.doc_ref;
      box.append(ref);
    }
    const approach = document.createElement("span");
    approach.className = "sub";
    approach.textContent = item.approach || "";
    box.append(approach);
  }
  return box;
}

function buildItem(item) {
  const li = $("item").content.firstElementChild.cloneNode(true);
  li.dataset.id = item.id;
  li.querySelector(".pin").addEventListener("click", () => {
    const pinned = !li.classList.contains("pinned");
    post(`/api/items/${item.id}/pin?pinned=${pinned}`);
  });
  li.querySelector(".dismiss").addEventListener("click", () => {
    li.remove();
    elements.delete(item.id);
    post(`/api/items/${item.id}/dismiss`);
  });
  return li;
}

let lastBoard = { sections: {} };

function renderBoard(board, changed = []) {
  lastBoard = board;
  const fresh = new Set(changed);
  for (const name of SECTIONS) {
    const section = document.querySelector(`.section[data-section="${name}"]`);
    const list = section.querySelector("ul");
    const items = board.sections[name] || [];
    const keep = new Set(items.map((i) => i.id));
    for (const li of [...list.children]) {
      if (li.dataset.id && !keep.has(Number(li.dataset.id))) {
        li.remove();
        elements.delete(Number(li.dataset.id));
      }
    }
    list.querySelector(".none")?.remove();
    list.querySelector(".more")?.remove();
    items.forEach((item, index) => {
      let li = elements.get(item.id);
      const isNew = !li;
      if (!li) {
        li = buildItem(item);
        elements.set(item.id, li);
      }
      li.querySelector(".item-text").replaceWith(itemContent(item));
      li.classList.toggle("pinned", item.pinned);
      li.querySelector(".pin").title = item.pinned ? "Unpin" : "Pin";
      if (list.children[index] !== li) list.insertBefore(li, list.children[index] || null);
      li.hidden = index >= SHOWN && !expanded.has(name);
      if ((isNew && fresh.size) || fresh.has(item.id)) {
        li.classList.remove("fresh");
        void li.offsetWidth; // restart the highlight
        li.classList.add("fresh");
      }
    });
    if (!items.length) {
      const none = document.createElement("li");
      none.className = "none";
      none.textContent = "—";
      list.append(none);
    } else if (items.length > SHOWN) {
      const more = document.createElement("li");
      more.className = "more";
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.textContent = expanded.has(name) ? "Show less" : `+${items.length - SHOWN} more`;
      toggle.addEventListener("click", () => {
        expanded.has(name) ? expanded.delete(name) : expanded.add(name);
        renderBoard(lastBoard);
      });
      more.append(toggle);
      list.append(more);
    }
    let count = section.querySelector("h2 .count");
    if (!count) {
      count = document.createElement("span");
      count.className = "count";
      section.querySelector("h2").append(count);
    }
    count.textContent = items.length ? String(items.length) : "";
  }
}

// ---- report ---------------------------------------------------------------------------

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function inline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|\W)_([^_]+)_(?=\W|$)/g, "$1<em>$2</em>");
}

// Enough markdown for the report: headings, lists, paragraphs, code and emphasis.
function markdown(md) {
  const out = [];
  let list = null;
  let para = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; } };
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of md.split("\n")) {
    const line = raw.trimEnd();
    let m;
    if (!line.trim()) { flushPara(); closeList(); continue; }
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      flushPara(); closeList();
      const level = m[1].length === 1 ? 1 : 3;
      out.push(`<h${level}>${inline(m[2])}</h${level}>`);
    } else if ((m = line.match(/^\s*(?:[-*]|(\d+)\.)\s+(.*)$/))) {
      flushPara();
      const kind = m[1] ? "ol" : "ul";
      if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline(m[2])}</li>`);
    } else {
      closeList();
      para.push(line.trim());
    }
  }
  flushPara(); closeList();
  return out.join("\n");
}

function renderReport() {
  const has = Boolean(state.report);
  $("report").hidden = !has;
  $("board").hidden = has;
  if (has) {
    $("report-body").innerHTML = markdown(state.report);
    $("report-path").textContent = state.report_path ? `saved to ${state.report_path}` : "";
  }
}

// ---- wiring ---------------------------------------------------------------------------

async function post(url) {
  try {
    const response = await fetch(url, { method: "POST" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  } catch (e) {
    showError(`Could not reach the server: ${e.message}`);
  }
}

async function copy(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    const label = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => (button.textContent = label), 1500);
  } catch {
    showError("Copy failed: select the text and copy it by hand.");
  }
}

function handle(event) {
  switch (event.type) {
    case "snapshot":
      state = { ...state, ...event };
      $("turns").replaceChildren();
      elements.clear();
      document.querySelectorAll(".section ul").forEach((ul) => ul.replaceChildren());
      event.transcript.forEach(addTurn);
      $("turns-empty").hidden = event.transcript.length > 0;
      requestAnimationFrame(() => {
        const pane = document.querySelector(".transcript");
        pane.scrollTop = pane.scrollHeight;
      });
      renderBoard(event.board);
      showError(event.error);
      renderReport();
      break;
    case "state":
      state.state = event.state;
      if (event.latency_s != null) state.latency_s = event.latency_s;
      break;
    case "turn":
      addTurn(event.turn);
      break;
    case "board":
      if (event.latency_s != null) state.latency_s = event.latency_s;
      renderBoard(event.board, event.changed);
      break;
    case "error":
      showError(event.error);
      break;
    case "report":
      state.report = event.report;
      state.report_path = event.report_path;
      renderReport();
      break;
  }
  renderState();
}

function connect() {
  const source = new EventSource("/events");
  source.onmessage = (message) => handle(JSON.parse(message.data));
  source.onopen = () => { if (state.error?.startsWith("Lost")) showError(null); };
  source.onerror = () => {
    showError("Lost the connection to Fieldnotes, retrying…");
    $("state").dataset.state = "error";
  };
}

$("copy-report").addEventListener("click", (e) => copy(state.report || "", e.currentTarget));
$("end").addEventListener("click", () => {
  $("end").disabled = true;
  post("/api/end");
});
renderState();
connect();
