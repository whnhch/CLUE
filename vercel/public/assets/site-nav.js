// Site tabs: Dashboard | Metric Explanation | Metric Simulator, shared by both pages
// so the navigation looks and reads the same wherever the participant is.
//
// Shown on CLUE, and on the dashboard in the CLUE condition only: in the baseline
// condition there is no CLUE to navigate to, and the tabs would be a way in.
//
// Each page supplies the hrefs, because they differ: the dashboard links into
// CLUE with its current period and token; CLUE switches its own views by hash
// ("#", "#simulator") so moving between them never reloads the page and loses
// pinned scenarios.

import { html, raw } from "./common.js";

// Loads its own stylesheet if the page did not link it (for example, an older
// cached copy of the page), so the tabs never render as bare links.
const STYLESHEET = "/assets/site-nav.css";
if (!document.querySelector(`link[href="${STYLESHEET}"]`)) {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = STYLESHEET;
  document.head.appendChild(link);
}

export const SITE_TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "main", label: "Metric Explanation" },
  { id: "simulator", label: "Metric Simulator" },
];

// active: one of the SITE_TABS ids. hrefs: { dashboard, main, simulator }.
export function siteTabsHtml(active, hrefs) {
  return html`
    <nav class="site-tabs" aria-label="Pages">
      ${SITE_TABS.map(
        (tab) => html`<a class="site-tab" href="${hrefs[tab.id]}"
            ${tab.id === active ? raw('aria-current="page"') : ""}>${tab.label}</a>`
      )}
    </nav>`;
}
