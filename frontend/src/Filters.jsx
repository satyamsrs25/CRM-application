// Column filters for the lists (Leads, Opportunities, Accounts, Contacts, Tasks): a dropdown arrow in the
// column header, like Salesforce/Excel. The chosen values are kept per list in this browser.
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Icon } from "./ui";
import { dateRangeBounds, filterText, FUTURE_RANGES, PAST_RANGES } from "./listHelpers";

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
export function useFilters(name) {
  const storeKey = `salestrack.filters.${name}`;
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
export const ownerOptions = (users, me) => [
  [String(me.id), "Me"],
  ...users
    .filter((u) => u.is_active !== false && u.id !== me.id && u.role !== "Admin")
    .sort((a, b) => a.full_name.localeCompare(b.full_name))
    .map((u) => [String(u.id), u.full_name]),
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
// views without column headers (the Leads Kanban); the menu is the same.
function HeaderFilter({ def, values, onChange, pill = false }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const [custom, setCustom] = useState({ from: "", to: "" });
  const button = useRef(null);
  const menu = useRef(null);
  const value = values[def.key] || "";

  useLayoutEffect(() => {
    if (!open) return;
    const r = button.current.getBoundingClientRect();
    const left = Math.min(r.right - 220, window.innerWidth - 240);
    setPos({ top: r.bottom + 4, left: Math.max(8, left), maxHeight: Math.max(220, window.innerHeight - r.bottom - 16) });
    setCustom({ from: values[`${def.key}_from`] || "", to: values[`${def.key}_to`] || "" });
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  // once drawn, use the menu's real width: its right edge lines up with the arrow, and it stays 8px inside the window
  // (on a phone the menu is wider than the space to the left of a narrow column)
  useLayoutEffect(() => {
    if (!open || !pos || !menu.current) return;
    const width = menu.current.getBoundingClientRect().width;
    const r = button.current.getBoundingClientRect();
    // a pill opens to the right of its left edge; a header arrow lines its menu up with its right edge
    const want = Math.max(8, Math.min(pill ? r.left : r.right - width, window.innerWidth - width - 8));
    if (Math.abs(want - pos.left) > 0.5) setPos({ ...pos, left: want });
  }, [open, pos]);
  useEffect(() => {
    if (!open) return;
    const away = (e) => !menu.current?.contains(e.target) && !button.current?.contains(e.target) && setOpen(false);
    // Esc closes the menu and puts the keyboard back on its arrow button
    const key = (e) => e.key === "Escape" && (setOpen(false), button.current?.focus({ preventScroll: true }));
    const close = (e) => !menu.current?.contains(e.target) && setOpen(false); // page scroll, not the menu's own
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

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
  const [typed, setTyped] = useState("");
  useEffect(() => {
    if (open) setTyped(values[def.key] || "");
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <button
        ref={button}
        type="button"
        className={`${pill ? "filter-pill" : "th-filter"} ${value ? "on" : ""} ${open ? "open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-label={pill ? (value ? `${filterSummary([def], values)}. Change the ${def.label} filter` : `Filter by ${def.label}`) : `Filter ${def.label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        title={value ? `Filtered: ${filterSummary([def], values)}` : `Filter by ${def.label}`}
      >
        {pill && <span>{value ? filterSummary([def], values) : def.label}</span>}
        <Icon name="down" size={pill ? 12 : 14} />
      </button>
      {open && pos && (
        <div ref={menu} className="th-menu" role="menu" style={pos}>
          <p className="th-menu-label">Filter by {def.label}</p>
          <button role="menuitemradio" aria-checked={!value} className={!value ? "on" : ""} onClick={() => choose("")}>
            <Icon name="check" size={13} /> {def.type === "date" ? "Any time" : "All"}
          </button>
          {choices.map(([v, text]) => (
            <button key={v} role="menuitemradio" aria-checked={value === v} className={value === v ? "on" : ""} onClick={() => choose(v)}>
              <Icon name="check" size={13} /> {text}
            </button>
          ))}
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
