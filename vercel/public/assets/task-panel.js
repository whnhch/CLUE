// Study task panel: a collapsible sidebar with the task instructions, on both pages.
//
// Installed identically on the dashboard (whatever the ?s= condition) and on CLUE,
// so rereading the task in-app is never something only one condition can do.
//
// Both pages are on one site, so the panel's state (open or closed, which task
// tab) is kept in localStorage and carries across the dashboard <-> CLUE handoff:
// a participant on Task 2 in the dashboard still sees Task 2 when CLUE opens.
// Storage is a convenience only; without it the panel opens on Task 1.

import { escapeHtml, html, raw } from "./common.js";
import { STUDY_TASKS } from "./study-tasks.js";

const STORAGE_KEY = "clue-study.task-panel";

// Loads its own stylesheet if the page did not link it (for example, an older
// cached copy of the page), so the panel never renders unstyled over the page.
const STYLESHEET = "/assets/task-panel.css";
if (!document.querySelector(`link[href="${STYLESHEET}"]`)) {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = STYLESHEET;
  document.head.appendChild(link);
}

// Below this width the panel would squeeze the page too far, so it floats over
// the content instead and starts closed.
const NARROW_QUERY = "(max-width: 900px)";

function readState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (saved && typeof saved === "object") return saved;
  } catch {
    // Private mode or blocked storage: fall through to the defaults.
  }
  return {};
}

function writeState(next) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Not fatal; the panel just won't remember across pages.
  }
}

// Escapes the text, then turns **x** into <b>x</b>.
function inline(text) {
  return raw(escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>"));
}

function taskHtml(task) {
  return html`
    <h3 class="tp-task-title">${task.label}: ${task.title}</h3>
    <p>${inline(task.intro)}</p>
    <ol>${task.steps.map((step) => html`<li>${inline(step)}</li>`)}</ol>
    ${task.note ? html`<p class="tp-note">${inline(task.note)}</p>` : ""}`;
}

function panelHtml(activeId) {
  return html`
    <div class="tp-head">
      <h2 class="tp-title" id="tp-title">Study tasks</h2>
      <button type="button" class="tp-icon-button" data-tp-close
              aria-label="Hide study tasks" title="Hide study tasks">»</button>
    </div>
    <div class="tp-tabs" role="tablist" aria-labelledby="tp-title">
      ${STUDY_TASKS.map(
        (task) => html`
          <button type="button" role="tab" class="tp-tab" id="tp-tab-${task.id}"
                  data-tp-task="${task.id}" aria-controls="tp-panel-${task.id}"
                  aria-selected="${task.id === activeId}"
                  tabindex="${task.id === activeId ? "0" : "-1"}">${task.label}</button>`
      )}
    </div>
    ${STUDY_TASKS.map(
      (task) => html`
        <section class="tp-body" role="tabpanel" id="tp-panel-${task.id}"
                 aria-labelledby="tp-tab-${task.id}" ${task.id === activeId ? "" : raw("hidden")}>
          ${taskHtml(task)}
        </section>`
    )}`;
}

export function installTaskPanel() {
  if (!STUDY_TASKS.length || document.getElementById("task-panel")) return;

  const saved = readState();
  const narrow = window.matchMedia(NARROW_QUERY);
  const state = {
    open: typeof saved.open === "boolean" ? saved.open : !narrow.matches,
    task: STUDY_TASKS.some((t) => t.id === saved.task) ? saved.task : STUDY_TASKS[0].id,
  };

  const panel = document.createElement("aside");
  panel.id = "task-panel";
  panel.className = "tp-panel";
  panel.setAttribute("aria-label", "Study tasks");

  const opener = document.createElement("button");
  opener.type = "button";
  opener.className = "tp-opener";
  opener.setAttribute("aria-controls", "task-panel");
  opener.textContent = "Study tasks";

  document.body.prepend(panel, opener);

  const apply = ({ focus = false } = {}) => {
    panel.innerHTML = panelHtml(state.task);
    panel.hidden = !state.open;
    opener.hidden = state.open;
    opener.setAttribute("aria-expanded", String(state.open));
    document.documentElement.classList.toggle("tp-is-open", state.open);
    writeState(state);
    if (focus) {
      (state.open ? panel.querySelector('[aria-selected="true"]') : opener)?.focus();
    }
  };

  // Charts sized to their container (vega-embed) only re-measure on a window
  // resize, and opening the panel changes the page width without one.
  const relayout = () => window.dispatchEvent(new Event("resize"));

  const setOpen = (open) => {
    state.open = open;
    apply({ focus: true });
    relayout();
  };

  const selectTask = (id) => {
    state.task = id;
    apply();
    panel.querySelector(`#tp-tab-${id}`)?.focus();
  };

  opener.addEventListener("click", () => setOpen(true));

  panel.addEventListener("click", (event) => {
    if (event.target.closest("[data-tp-close]")) {
      setOpen(false);
      return;
    }
    const tab = event.target.closest("[data-tp-task]");
    if (tab) selectTask(tab.dataset.tpTask);
  });

  // Arrow keys move between tabs (WAI-ARIA tabs pattern).
  panel.addEventListener("keydown", (event) => {
    if (!event.target.closest("[role=tab]")) return;
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const index = STUDY_TASKS.findIndex((t) => t.id === state.task);
    selectTask(STUDY_TASKS[(index + step + STUDY_TASKS.length) % STUDY_TASKS.length].id);
  });

  // "Open in CLUE" opens a new tab; switching task in one tab follows in the other.
  // Only the task follows, not open/closed: each tab keeps its own layout.
  window.addEventListener("storage", (event) => {
    if (event.key !== STORAGE_KEY) return;
    const task = readState().task;
    if (task !== state.task && STUDY_TASKS.some((t) => t.id === task)) {
      state.task = task;
      apply();
    }
  });

  // On a narrow screen the panel floats over the page; Escape closes it.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.open && narrow.matches) setOpen(false);
  });

  apply();
}
