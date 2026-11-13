"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// ------------------------------------------------------------------ helpers
async function api(url, options = {}) {
  const opts = { ...options };
  if (opts.json !== undefined) {
    opts.body = JSON.stringify(opts.json);
    opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    delete opts.json;
  }
  const res = await fetch(url, opts);
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    let msg = data && data.detail ? data.detail : `Server error (${res.status})`;
    if (Array.isArray(msg)) msg = msg.map(d => d.msg).join(", ");
    throw new Error(msg);
  }
  return data;
}

let toastTimer;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
}

const CHECK_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5 10 17 19 7"/></svg>';
const TRASH_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>';

// --------------------------------------------------------------------- tabs
const TABS = ["text", "doc", "words"];
function showTab(name) {
  if (!TABS.includes(name)) name = "text";
  $$(".tabs [role=tab]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  $$(".panel").forEach(p => { p.hidden = p.id !== `tab-${name}`; });
  store.set("tab", name);
  history.replaceState(null, "", `#${name}`);
  if (name === "words") loadWords();
}
$$(".tabs [role=tab]").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
$(".tabs").addEventListener("keydown", e => {
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  const tabs = $$(".tabs [role=tab]");
  const i = tabs.findIndex(t => t.getAttribute("aria-selected") === "true");
  const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
  showTab(next.dataset.tab);
  next.focus();
});

// ----------------------------------------------------- "words to check" box
/**
 * Render the list of words that were not in the dictionary, with editable
 * Urdu spellings. Saving stores the changed ones in custom_words.txt.
 */
function renderCheck(container, unknown, { saveLabel, onSaved }) {
  container.replaceChildren();
  container.className = "check";
  if (!unknown) return;
  const card = el("div", { class: "card" });
  if (!unknown.length) {
    card.innerHTML = `<div class="all-good">${CHECK_ICON}Every word was found in the dictionary</div>`;
    container.append(card);
    return;
  }
  const head = el("div", { class: "card-head" },
    el("span", {}, "Words to check", el("span", { class: "count", text: String(unknown.length) })));
  const hint = el("p", { class: "hint",
    text: "These weren't in the dictionary, so they were spelled by rules. Fix any that are wrong. Your corrections are remembered." });
  const list = el("ul", { class: "check-list" });
  for (const w of unknown) {
    const input = el("input", { class: "urdu", dir: "rtl", lang: "ur", value: w.guess, "aria-label": `Urdu for ${w.roman}` });
    const li = el("li", {},
      el("span", { class: "roman", title: w.roman }, w.roman,
         w.count > 1 ? el("span", { class: "times", text: `×${w.count}` }) : null),
      el("span", { class: "arrow", "aria-hidden": "true", text: "→" }),
      input);
    input.addEventListener("input", () => li.classList.toggle("changed", input.value.trim() !== w.guess));
    li.dataset.roman = w.roman;
    li.dataset.guess = w.guess;
    list.append(li);
  }
  const btn = el("button", { class: "btn primary", type: "button", text: saveLabel });
  btn.addEventListener("click", async () => {
    const entries = $$("li", list)
      .map(li => ({ roman: li.dataset.roman, urdu: $("input", li).value.trim(), guess: li.dataset.guess }))
      .filter(e => e.urdu && e.urdu !== e.guess)
      .map(({ roman, urdu }) => ({ roman, urdu }));
    if (!entries.length) { toast("Edit a word first. Only changed words are saved."); return; }
    btn.disabled = true;
    try {
      const r = await api("/api/custom-words", { method: "POST", json: { entries } });
      toast(`Saved ${r.saved} word${r.saved === 1 ? "" : "s"}`);
      refreshWordCount();
      await onSaved();
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false;
    }
  });
  card.append(head, hint, list, btn);
  container.append(card);
}

// ---------------------------------------------------------------- text tab
const roman = $("#roman");
const out = $("#urduOut");
const outHint = $("#outHint");
const digitsText = $("#digitsText");
let textSeq = 0;
let textTimer;

async function convertText() {
  const text = roman.value;
  store.set("text", text);
  const mine = ++textSeq;
  if (!text.trim()) {
    out.textContent = "";
    outHint.hidden = false;
    renderCheck($("#textCheck"), null, {});
    return;
  }
  try {
    const r = await api("/api/convert", { method: "POST", json: { text, urdu_digits: digitsText.checked } });
    if (mine !== textSeq) return;               // a newer request is on its way
    out.textContent = r.urdu;
    outHint.hidden = true;
    renderCheck($("#textCheck"), r.unknown, { saveLabel: "Save corrections", onSaved: convertText });
  } catch (err) {
    if (mine === textSeq) toast(err.message);
  }
}
roman.addEventListener("input", () => { clearTimeout(textTimer); textTimer = setTimeout(convertText, 180); });
digitsText.addEventListener("change", convertText);
$("#clearBtn").addEventListener("click", () => { roman.value = ""; convertText(); roman.focus(); });
$$(".chip[data-example]").forEach(c => c.addEventListener("click", () => {
  roman.value = c.dataset.example;
  convertText();
}));
$("#copyBtn").addEventListener("click", async () => {
  const text = out.textContent;
  if (!text) { toast("Nothing to copy yet"); return; }
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const range = document.createRange();
    range.selectNodeContents(out);
    const sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    document.execCommand("copy");
    sel.removeAllRanges();
  }
  toast("Urdu text copied");
});

// ----------------------------------------------------------- word file tab
const drop = $("#drop");
const fileInput = $("#fileInput");
const statusBox = $("#docStatus");
let currentDoc = null;

function docOptions() {
  return { scale: parseFloat($("#scale").value), urdu_digits: $("#digitsDoc").checked };
}
function setStatus(kind, msg) {
  statusBox.hidden = !msg;
  statusBox.className = `status ${kind || ""}`;
  statusBox.replaceChildren();
  if (!msg) return;
  if (kind === "busy") statusBox.append(el("span", { class: "spinner", "aria-hidden": "true" }));
  statusBox.append(el("span", { text: msg }));
}

function showResult(r) {
  currentDoc = r;
  $("#docResult").hidden = false;
  $("#resName").textContent = r.filename;
  const check = r.unknown.length ? ` · ${r.unknown.length} to check` : "";
  $("#resStats").textContent = `${r.paragraphs} paragraphs · ${r.words} words${check}`;
  const dl = $("#downloadBtn");
  dl.href = r.download;
  dl.setAttribute("download", r.filename);

  const preview = $("#preview");
  preview.replaceChildren();
  for (const p of r.preview) {
    const tag = p.kind === "title" ? "h2" : p.kind === "heading" ? "h3" : "p";
    preview.append(el(tag, { class: p.kind, text: p.text }));
  }
  if (!r.preview.length) preview.append(el("p", { class: "muted", text: "(no text found)" }));
  renderCheck($("#docCheck"), r.unknown, { saveLabel: "Save & convert again", onSaved: reconvert });
}

async function upload(file) {
  if (!file) return;
  if (!/\.docx$/i.test(file.name)) {
    setStatus("error", file.name.toLowerCase().endsWith(".doc")
      ? "Old .doc files aren't supported. Open it in Word and use Save As → .docx first."
      : "Please choose a .docx Word file.");
    return;
  }
  const form = new FormData();
  const opts = docOptions();
  form.append("file", file);
  form.append("scale", opts.scale);
  form.append("urdu_digits", opts.urdu_digits);
  setStatus("busy", `Converting ${file.name}…`);
  try {
    const r = await api("/api/documents", { method: "POST", body: form });
    setStatus(null, "");
    showResult(r);
    toast("Done. Your Urdu document is ready");
  } catch (err) {
    setStatus("error", err.message);
  } finally {
    fileInput.value = "";
  }
}

async function reconvert() {
  if (!currentDoc) return;
  setStatus("busy", "Converting again…");
  try {
    const r = await api(`/api/documents/${currentDoc.id}/convert`, { method: "POST", json: docOptions() });
    setStatus(null, "");
    showResult(r);
  } catch (err) {
    setStatus("error", err.message);
  }
}

fileInput.addEventListener("change", () => upload(fileInput.files[0]));
["dragenter", "dragover"].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", e => upload(e.dataTransfer.files[0]));
$("#scale").addEventListener("change", () => { store.set("scale", $("#scale").value); reconvert(); });
$("#digitsDoc").addEventListener("change", reconvert);

// ------------------------------------------------------------ my words tab
async function loadWords() {
  try {
    const r = await api("/api/custom-words");
    const body = $("#wordsTable tbody");
    body.replaceChildren();
    for (const w of [...r.entries].reverse()) {
      const del = el("button", { class: "icon-btn", type: "button", title: `Remove ${w.roman}`, "aria-label": `Remove ${w.roman}` });
      del.innerHTML = TRASH_ICON;
      del.addEventListener("click", async () => {
        try {
          await api("/api/custom-words", { method: "DELETE", json: { roman: w.roman } });
          toast(`Removed "${w.roman}"`);
          loadWords();
          convertText();
        } catch (err) { toast(err.message); }
      });
      body.append(el("tr", {},
        el("td", { text: w.roman }),
        el("td", { class: "urdu", lang: "ur", text: w.urdu }),
        el("td", {}, del)));
    }
    $("#wordsEmpty").hidden = r.entries.length > 0;
    $("#wordsTable").hidden = r.entries.length === 0;
    setWordCount(r.entries.length);
  } catch (err) {
    toast(err.message);
  }
}
function setWordCount(n) {
  const b = $("#wordsCount");
  b.hidden = !n;
  b.textContent = n;
}
async function refreshWordCount() {
  try { setWordCount((await api("/api/custom-words")).entries.length); } catch { /* ignore */ }
  if (!$("#tab-words").hidden) loadWords();
}

$("#addWord").addEventListener("submit", async e => {
  e.preventDefault();
  const romanVal = $("#newRoman").value.trim();
  const urduVal = $("#newUrdu").value.trim();
  if (!romanVal || !urduVal) return;
  try {
    await api("/api/custom-words", { method: "POST", json: { entries: [{ roman: romanVal, urdu: urduVal }] } });
    $("#newRoman").value = "";
    $("#newUrdu").value = "";
    $("#newRoman").focus();
    toast(`Added "${romanVal}"`);
    loadWords();
    convertText();
  } catch (err) {
    toast(err.message);
  }
});

// -------------------------------------------------------------------- init
roman.value = store.get("text", "mera khyal ha ke Pakistan aik khoobsurat mulk hai. kia ap mujhe bata sakte hain ke kal ka plan kya hai?");
$("#scale").value = store.get("scale", "1.3");
convertText();
refreshWordCount();
showTab(location.hash.slice(1) || store.get("tab", "text"));
