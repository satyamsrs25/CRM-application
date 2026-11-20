// Column filters for the lists (Leads, Opportunities, Accounts, Contacts, Tasks): a dropdown arrow in the
// column header, like Salesforce/Excel. The chosen values are kept per list in this browser.
import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { Icon } from "./ui";
import { dateRangeBounds, filterText, FUTURE_RANGES, matchChoices, PAST_RANGES } from "./listHelpers";

// Date ranges. "past" fits created dates, "future" fits close and due dates (listHelpers.js, shared with the chips).
const PAST = PAST_RANGES;
const FUTURE = FUTURE_RANGES;

// Task due dates: only the choices people use (plus a custom range)
export const TASK_DUE_RANGES = [
  ["overdue", "Overdue"],
  ["today", "Today"],
  ["tomorrow", "Tomorrow"],
  ["week", "This week"],
  ["next7", "Next 7 days"],
];

// [start, end) in local time for a range key; custom uses the two date inputs (yyyy-mm-dd). See listHelpers.js.
export const rangeBounds = (range, from, to, now) => dateRangeBounds(range, from, to, now);

const toDate = (value) => (!value ? null : String(value).length === 10 ? new Date(`${value}T12:00:00`) : new Date(value));

// Client-side filtering for lists that are fully loaded (Opportunities, Accounts, Contacts, Tasks)
export function applyFilters(rows, defs, values) {
  const active = defs.filter((f) => values[f.key] && f.get); // filters without get() run on the server (Leads)
  if (!active.length) return rows;
  const tests = active.map((f) => {
    if (f.type === "text") {
      const needle = String(values[f.key]).trim().toLowerCase();
      return (r) => String(f.get(r) ?? "").toLowerCase().includes(needle);
    }
    if (f.type === "date") {
      const [start, end] = rangeBounds(values[f.key], values[`${f.key}_from`], values[`${f.key}_to`]);
      return (r) => {
        const d = toDate(f.get(r));
        return !!d && (!start || d >= start) && (!end || d < end);
      };
    }
    return (r) => String(f.get(r) ?? "") === values[f.key];
  });
  return rows.filter((r) => tests.every((t) => t(r)));
}

// Values kept per list ("leads", "tasks"...) so a filter stays when you come back
// Remembered per user (userId): filters chosen by someone who used this browser before (an Owner, a status) never hide
// another user's records.
export function useFilters(name, userId = null) {
  const storeKey = `salestrack.filters.${userId ? `${userId}.` : ""}${name}`;
  const read = () => {
    try {
      return JSON.parse(localStorage.getItem(storeKey)) || {};
    } catch {
      return {};
    }
  };
  const [values, setValues] = useState(read);
  useEffect(() => setValues(read()), [name]); // eslint-disable-line react-hooks/exhaustive-deps
  const update = (next) => {
    setValues(next);
    try {
      localStorage.setItem(storeKey, JSON.stringify(next));
    } catch {
      /* private window: filters just aren't remembered */
    }
  };
  return [values, update];
}

export const activeCount = (defs, values) => defs.filter((f) => values[f.key]).length;

// Owner choices for Admins/Managers (people who can see the team's records)
// Deactivated people come last, marked: their leads can still be listed (Manage Access > People > Open Leads)
export const ownerOptions = (users, me) => [
  [String(me.id), "Me"],
  ...users
    .filter((u) => u.id !== me.id && u.role !== "Admin")
    .sort((a, b) => (a.is_active === false) - (b.is_active === false) || a.full_name.localeCompare(b.full_name))
    .map((u) => [String(u.id), u.is_active === false ? `${u.full_name} (inactive)` : u.full_name]),
];

export const opts = (list) => list.map((x) => [x, x]);

// short text for the active filter, shown under the list title ("Priority: High")
export function filterSummary(defs, values) {
  return defs
    .filter((f) => values[f.key])
    .map((f) => filterText(f, values))
    .join(" • ");
}

// The dropdown arrow inside a column header and its menu. pill: a labelled button instead ("Lead Status: Demo ▾"), for
// views without column headers (the Leads Kanban); the menu is the same. A long list (def.search, e.g. Region's
// countries) gets a search box above its options, which scroll under it; def.allLabel names its first choice.
// Keyboard: Enter or Space on the arrow opens the menu (a search box takes the typing); ↓ and ↑ move between the
// options (from the search box too), Home and End to the first and last; Enter picks one (in the search box, the first
// one shown); Esc closes the menu and puts the keyboard back on the arrow.
function HeaderFilter({ def, values, onChange, pill = false }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const [custom, setCustom] = useState({ from: "", to: "" });
  const [find, setFind] = useState(""); // typed in the search box (def.search)
  const button = useRef(null);
  const menu = useRef(null);
  const search = useRef(null);
  const list = useRef(null);
  const listId = useId();
  const value = values[def.key] || "";
  // a touch screen: the search box isn't focused on opening (that would cover the list with the on-screen keyboard)
  const touch = typeof window !== "undefined" && !!window.matchMedia?.("(pointer: coarse)").matches;
  // the menu's leftmost position: inside the list's card (on a phone the fixed side bar beside it is drawn over
  // anything further left), and at least 8px inside the window
  const leftEdge = () => Math.max(8, button.current?.closest(".card")?.getBoundingClientRect().left ?? 8);

  useLayoutEffect(() => {
    if (!open) {
      setPos(null); // the next opening is drawn afresh (never with the last search or position)
      return;
    }
    const r = button.current.getBoundingClientRect();
    const edge = leftEdge();
    const left = Math.min(r.right - 220, window.innerWidth - 240);
    const room = Math.max(220, window.innerHeight - r.bottom - 16);
    // a long searchable list stays a compact panel: its options scroll
    setPos({ top: r.bottom + 4, left: Math.max(edge, left), maxHeight: def.search ? Math.min(room, 400) : room, maxWidth: window.innerWidth - edge - 8 });
    setCustom({ from: values[`${def.key}_from`] || "", to: values[`${def.key}_to`] || "" });
    setFind("");
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  // once drawn, use the menu's real width: its right edge lines up with the arrow, and it stays 8px inside the window
  // (on a phone the menu is wider than the space to the left of a narrow column)
  useLayoutEffect(() => {
    if (!open || !pos || !menu.current) return;
    const width = menu.current.getBoundingClientRect().width;
    const r = button.current.getBoundingClientRect();
    // a pill opens to the right of its left edge; a header arrow lines its menu up with its right edge
    const want = Math.max(leftEdge(), Math.min(pill ? r.left : r.right - width, window.innerWidth - width - 8));
    if (Math.abs(want - pos.left) > 0.5) setPos({ ...pos, left: want });
  }, [open, pos]);
  // a long list opens at the chosen option (India, far down the countries), not at the top
  useLayoutEffect(() => {
    const box = list.current;
    const on = box?.querySelector('[aria-checked="true"]');
    if (open && pos && on) box.scrollTop = Math.max(0, on.offsetTop - (box.clientHeight - on.offsetHeight) / 2);
  }, [open, !!pos]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return;
    const width = window.innerWidth;
    // typing in the menu on a phone: its on-screen keyboard resizes or scrolls the page, which keeps the menu open
    // (turning the phone, or any other scroll or resize, still closes it)
    const typing = () => touch && menu.current?.contains(document.activeElement) && document.activeElement.tagName === "INPUT";
    const away = (e) => !menu.current?.contains(e.target) && !button.current?.contains(e.target) && setOpen(false);
    // Esc closes the menu and puts the keyboard back on its arrow button
    const key = (e) => e.key === "Escape" && (setOpen(false), button.current?.focus({ preventScroll: true }));
    const close = (e) => !menu.current?.contains(e.target) && !typing() && setOpen(false); // page scroll, not the menu's own
    const resize = () => (window.innerWidth !== width || !typing()) && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", resize);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", resize);
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const choose = (v, extra = {}) => {
    const next = { ...values };
    delete next[def.key];
    delete next[`${def.key}_from`];
    delete next[`${def.key}_to`];
    if (v) Object.assign(next, { [def.key]: v }, extra);
    onChange(next);
    setOpen(false);
    button.current?.focus({ preventScroll: true }); // after a choice, the keyboard stays on the column's filter arrow
  };
  const choices = def.type === "text" ? [] : def.type === "date" ? def.ranges || (def.future ? FUTURE : PAST) : def.options;
  const shown = def.search ? matchChoices(choices, find) : choices;
  const searching = !!def.search && !!find.trim(); // while searching, only the matches (Enter picks the first)
  const [typed, setTyped] = useState("");
  useEffect(() => {
    if (open) setTyped(values[def.key] || "");
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // ↓ ↑ Home End between the options (and from the search box into them); the date and text boxes keep their keys.
  // The options scroll inside the menu, never the page behind it.
  const moveFocus = (e) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const inSearch = e.target === search.current;
    if (!inSearch && e.target.getAttribute?.("role") !== "menuitemradio") return;
    if (inSearch && (e.key === "Home" || e.key === "End")) return; // the caret's keys in the search box
    const items = [...menu.current.querySelectorAll('[role="menuitemradio"]')];
    if (!items.length) return;
    e.preventDefault();
    const at = items.indexOf(e.target);
    const to = e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : e.key === "ArrowDown" ? Math.min(at + 1, items.length - 1) : at - 1;
    const next = to < 0 ? search.current || items[0] : items[to];
    next.focus({ preventScroll: true });
    const box = list.current || menu.current;
    if (box.contains(next) && next !== search.current) {
      if (next.offsetTop < box.scrollTop) box.scrollTop = next.offsetTop;
      else if (next.offsetTop + next.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = next.offsetTop + next.offsetHeight - box.clientHeight;
    }
  };
  const options = [
    !searching && (
      <button key="" role="menuitemradio" aria-checked={!value} className={!value ? "on" : ""} onClick={() => choose("")}>
        <Icon name="check" size={13} /> {def.allLabel || (def.type === "date" ? "Any time" : "All")}
      </button>
    ),
    ...shown.map(([v, text]) => (
      <button key={v} role="menuitemradio" aria-checked={value === v} className={value === v ? "on" : ""} onClick={() => choose(v)}>
        <Icon name="check" size={13} /> {text}
      </button>
    )),
  ];

  return (
    <>
      <button
        ref={button}
        type="button"
        className={`${pill ? "filter-pill" : "th-filter"} ${value ? "on" : ""} ${open ? "open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-label={pill ? (value ? `${filterSummary([def], values)}. Change the ${def.label} filter` : `Filter by ${def.label}`) : `Filter ${def.label}`}
        aria-haspopup={def.search ? "dialog" : "menu"}
        aria-expanded={open}
        title={value ? `Filtered: ${filterSummary([def], values)}` : `Filter by ${def.label}`}
      >
        {pill && <span>{value ? filterSummary([def], values) : def.label}</span>}
        <Icon name="down" size={pill ? 12 : 14} />
      </button>
      {open && pos && (
        <div
          ref={menu}
          className={`th-menu ${def.search ? "searchable" : ""}`}
          role={def.search ? "dialog" : "menu"}
          aria-label={def.search ? `Filter by ${def.label}` : undefined}
          style={pos}
          onKeyDown={moveFocus}
        >
          <p className="th-menu-label">Filter by {def.label}</p>
          {def.search ? (
            <>
              <div className="th-search">
                <Icon name="search" size={13} />
                <input
                  ref={search}
                  type="search"
                  value={find}
                  autoFocus={!touch}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => {
                    setFind(e.target.value);
                    if (list.current) list.current.scrollTop = 0; // the best match first
                  }}
                  onKeyDown={(e) => {
                    if (e.key !== "Enter") return;
                    e.preventDefault();
                    if (searching && shown.length) choose(shown[0][0]);
                  }}
                  placeholder={def.search.placeholder}
                  aria-label={def.search.placeholder}
                  aria-controls={listId}
                />
              </div>
              {(!searching || shown.length > 0) && (
                <div ref={list} id={listId} className="th-menu-list" role="menu" aria-label={`${def.label} choices`}>
                  {options}
                </div>
              )}
              {searching && !shown.length && (
                <p className="th-menu-empty" role="status">
                  {def.search.none} “{find.trim()}”
                </p>
              )}
            </>
          ) : (
            options
          )}
          {def.type === "date" && (
            <div className="th-custom">
              <p className="th-menu-label">Custom range</p>
              <label>
                From
                <input type="date" value={custom.from} max={custom.to || undefined} onChange={(e) => setCustom({ ...custom, from: e.target.value })} />
              </label>
              <label>
                To
                <input type="date" value={custom.to} min={custom.from || undefined} onChange={(e) => setCustom({ ...custom, to: e.target.value })} />
              </label>
              <div className="th-custom-actions">
                <button type="button" className="link" disabled={!custom.from && !custom.to} onClick={() => setCustom({ from: "", to: "" })}>
                  Clear
                </button>
                <button
                  className="sf-button brand small"
                  disabled={!custom.from && !custom.to}
                  onClick={() => choose("custom", { [`${def.key}_from`]: custom.from, [`${def.key}_to`]: custom.to })}
                >
                  Apply
                </button>
              </div>
            </div>
          )}
          {def.type === "text" && (
            <form
              className="th-custom"
              onSubmit={(e) => {
                e.preventDefault();
                choose(typed.trim());
              }}
            >
              <input
                autoFocus
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder={def.placeholder || `Type part of the ${def.label.toLowerCase()}`}
                aria-label={`${def.label} contains`}
              />
              <div className="th-custom-actions">
                <button type="button" className="link" disabled={!typed && !value} onClick={() => (setTyped(""), value && choose(""))}>
                  Clear
                </button>
                <button className="sf-button brand small" type="submit" disabled={!typed.trim()}>
                  Apply
                </button>
              </div>
            </form>
          )}
          {!choices.length && def.type !== "text" && <p className="th-menu-empty">Nothing to filter yet</p>}
        </div>
      )}
    </>
  );
}

// The same filter menu behind a labelled button (Leads Kanban filter bar)
export const FilterButton = (props) => <HeaderFilter {...props} pill />;

// A column header: click the name to sort, the arrow to filter
export function Th({ label, sorted, flip, onSort, filter, values, onChange, className = "" }) {
  const active = filter && values[filter.key];
  return (
    <th className={`${className} ${active ? "filtered" : ""}`} aria-sort={sorted ? (flip ? "ascending" : "descending") : undefined}>
      <div className="th-cell">
        {onSort ? (
          <button type="button" className="th-sort" onClick={onSort}>
            {label}
            {sorted && <span className="th-dir" aria-label={flip ? "sorted ascending" : "sorted descending"}>{flip ? "↑" : "↓"}</span>}
          </button>
        ) : (
          <span className="th-sort">{label}</span>
        )}
        {filter && <HeaderFilter def={filter} values={values} onChange={onChange} />}
      </div>
    </th>
  );
}
