// Opportunities (List and Kanban): the filter row above both (Owner, Currency, Overdue / Stuck, Closing This Month,
// Clear All, Save as View), the dialogs for saved views and the Admin's In stage limits, and a board card's details.
// The filter values are the list's own (useFilters in ListView.jsx), so the column arrows, the summary line, List and
// Kanban all show and clear the same choices.
import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { api } from "./api";
import { useDismiss } from "./Header";
import { maskPhone, shortDate } from "./format";
import {
  matchChoices,
  nextOpenTask,
  opportunityClockSummary,
  opportunityPoc,
  previewPlacement,
  stageLimitText,
  telHref,
  withoutFilter,
} from "./listHelpers";
import { ActionMenu, Icon } from "./ui";

// Owner: several people at once (any of them), grouped by role; only the people whose opportunities this user can see
// (def.groups, from listHelpers.ownerChoiceGroups). A search box when the list is long; Clear owners.
function OwnerPicker({ def, values, onChange }) {
  const [open, setOpen] = useState(false);
  const [find, setFind] = useState("");
  const ref = useDismiss(open, setOpen);
  const button = useRef(null);
  const popId = useId();
  const chosen = new Set(values[def.key] ? String(values[def.key]).split(",") : []);
  useEffect(() => {
    if (!open) setFind("");
  }, [open]);
  const choose = (next) => {
    const out = withoutFilter(values, def.key);
    if (next.size) out[def.key] = [...next].join(",");
    onChange(out);
  };
  const toggle = (v) => {
    const next = new Set(chosen);
    if (next.has(v)) next.delete(v);
    else next.add(v);
    choose(next);
  };
  const label = !chosen.size
    ? "All"
    : chosen.size === 1
      ? def.options.find(([o]) => chosen.has(o))?.[1] || "1 selected"
      : `${chosen.size} selected`;
  const typed = find.trim();
  const groups = def.groups
    .map((g) => ({ ...g, options: typed ? matchChoices(g.options, typed) : g.options }))
    .filter((g) => g.options.length);
  return (
    <div className="owner-picker" ref={ref} onKeyDown={(e) => e.key === "Escape" && button.current?.focus()}>
      <button
        ref={button}
        type="button"
        className={`filter-pill ${chosen.size ? "on" : ""}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? popId : undefined}
        onClick={() => setOpen((o) => !o)}
      >
        <span>Owner: {label}</span>
        <Icon name="down" size={12} />
      </button>
      {open && (
        <div id={popId} className="owner-pop" role="dialog" aria-label="Filter by owner">
          {def.options.length > 8 && (
            <div className="th-search">
              <Icon name="search" size={13} />
              <input type="search" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Search people" aria-label="Search people" autoComplete="off" />
            </div>
          )}
          <div className="owner-groups">
            {groups.map((g) => (
              <fieldset key={g.label} className="owner-group">
                <legend>{g.label}</legend>
                {g.options.map(([v, text]) => (
                  <label key={v} className="owner-choice">
                    <input type="checkbox" checked={chosen.has(v)} onChange={() => toggle(v)} /> <span>{text}</span>
                  </label>
                ))}
              </fieldset>
            ))}
            {!groups.length && (
              <p className="th-menu-empty" role="status">
                No one matches “{typed}”
              </p>
            )}
          </div>
          <div className="owner-pop-foot">
            <span aria-live="polite">{chosen.size ? `${chosen.size} selected` : "Everyone you can see"}</span>
            <button type="button" className="link" disabled={!chosen.size} onClick={() => choose(new Set())}>
              Clear owners
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// The row above the List and the Kanban. Every choice narrows the list further (AND); the count on Overdue / Stuck is
// what it would show with the other choices as they are. Clear All clears these and the search, never the list view
// itself (its scope, e.g. My Open Opportunities, stays).
export function OpportunityFilterRow({ defs, values, onChange, overdueStuck, canClear, onClearAll, onSave, savedView, onRename, onDelete }) {
  const owner = defs.find((f) => f.key === "owner" && f.multi);
  const currency = defs.find((f) => f.key === "currency");
  const flag = defs.find((f) => f.key === "overdue_stuck");
  const close = defs.find((f) => f.key === "close");
  const set = (key, value) => {
    const next = withoutFilter(values, key);
    if (value) next[key] = value;
    onChange(next);
  };
  const month = values.close === "month"; // Closing This Month is Close Date: This month (the same choice, worked out each day)
  return (
    <div className="opp-filter-row" role="group" aria-label="Opportunity filters">
      {owner && <OwnerPicker def={owner} values={values} onChange={onChange} />}
      {currency && (
        <label className="opp-currency">
          <span>Currency</span>
          <select value={values.currency || ""} onChange={(e) => set("currency", e.target.value)}>
            <option value="">All</option>
            {currency.options.map(([v, text]) => (
              <option key={v} value={v}>
                {text}
              </option>
            ))}
          </select>
        </label>
      )}
      {flag && (
        <button
          type="button"
          className={`opp-toggle ${values.overdue_stuck ? "on" : ""}`}
          aria-pressed={!!values.overdue_stuck}
          onClick={() => set("overdue_stuck", values.overdue_stuck ? "" : "1")}
          title="Open opportunities past their close date, or stalled in their stage"
        >
          Overdue / Stuck <span className="opp-count">{overdueStuck.toLocaleString()}</span>
          <span className="sr-only">{overdueStuck === 1 ? " opportunity" : " opportunities"}</span>
        </button>
      )}
      {close && (
        <button
          type="button"
          className={`opp-toggle ${month ? "on" : ""}`}
          aria-pressed={month}
          onClick={() => set("close", month ? "" : "month")}
          title="Close Date in this calendar month"
        >
          Closing This Month
        </button>
      )}
      <button type="button" className="link opp-clear" disabled={!canClear} onClick={onClearAll}>
        Clear All
      </button>
      <span className="opp-row-end">
        <button type="button" className="sf-button small" onClick={onSave} title="Keep these filters, the search and the sort as your own view">
          Save as View
        </button>
        {savedView && (
          <ActionMenu
            label="Manage View"
            items={[
              { label: "Rename View", onClick: onRename },
              { label: "Delete View", danger: true, onClick: onDelete },
            ]}
          />
        )}
      </span>
    </div>
  );
}

function useEscape(busy, onClose) {
  useEffect(() => {
    const key = (e) => e.key === "Escape" && !busy && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [busy, onClose]);
}

// Save as View (a new view from the list as it is), Rename View or Delete View. onSubmit(name) saves; its error stays here.
export function SavedViewDialog({ mode, view, onClose, onSubmit }) {
  const [name, setName] = useState(mode === "rename" ? view.name : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEscape(busy, onClose);
  const submit = async (e) => {
    e.preventDefault();
    if (mode !== "delete" && !name.trim()) return setError("Enter a name for the view.");
    setBusy(true);
    setError("");
    try {
      await onSubmit(name.trim());
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  const title = mode === "save" ? "Save as View" : mode === "rename" ? `Rename View: ${view.name}` : `Delete View: ${view.name}`;
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <section className="modal small-modal" role="dialog" aria-modal="true" aria-labelledby="saved-view-title">
        <button className="modal-close" aria-label="Close dialog" onClick={onClose} disabled={busy}>
          <Icon name="close" size={18} />
        </button>
        <header className="modal-header">
          <h2 id="saved-view-title">{title}</h2>
        </header>
        <form onSubmit={submit}>
          <div className="modal-body">
            {mode === "delete" ? (
              <p>Delete this view? Only the saved view is removed; no opportunity changes.</p>
            ) : (
              <>
                {mode === "save" && (
                  <p className="field-hint">
                    Keeps the current filters, search and sort as your own view, next to the standard ones. Only you see it. Date choices such as Closing
                    This Month stay up to date.
                  </p>
                )}
                <label className="field">
                  <span>
                    <abbr title="required">*</abbr> View name
                  </span>
                  <input autoFocus value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
                </label>
              </>
            )}
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="sf-button" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className={`sf-button ${mode === "delete" ? "danger" : "brand"}`} disabled={busy} aria-busy={busy}>
              {busy ? "Saving…" : mode === "delete" ? "Delete" : "Save"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

// The Admin's In stage limits for the open stages (whole days; Needs attention below Stalled). The list, an opportunity's
// page, the board and the filters all use what is saved; Won and Lost have none.
export function StageLimitsDialog({ limits, onClose, onSaved }) {
  const stages = Object.keys(limits.defaults);
  const [values, setValues] = useState(() => Object.fromEntries(stages.map((s) => [s, limits.limits[s].map(String)])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEscape(busy, onClose);
  const problem = (s) => {
    const [a, b] = values[s];
    if (!/^\d+$/.test(a) || !/^\d+$/.test(b)) return "Enter whole days (0 or more).";
    if (Number(a) >= Number(b)) return "Needs attention must be less than Stalled.";
    if (Number(b) > limits.max_days) return `Stalled can be at most ${limits.max_days} days.`;
    return "";
  };
  const change = (stage, i, v) => setValues((old) => ({ ...old, [stage]: old[stage].map((x, j) => (j === i ? v.trim() : x)) }));
  const submit = async (e) => {
    e.preventDefault();
    const bad = stages.find((s) => problem(s));
    if (bad) return setError(`${bad}: ${problem(bad)}`);
    setBusy(true);
    setError("");
    try {
      onSaved(await api.setOpportunityStageLimits(Object.fromEntries(stages.map((s) => [s, values[s].map(Number)]))));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <section className="modal small-modal" role="dialog" aria-modal="true" aria-labelledby="stage-limits-title">
        <button className="modal-close" aria-label="Close dialog" onClick={onClose} disabled={busy}>
          <Icon name="close" size={18} />
        </button>
        <header className="modal-header">
          <h2 id="stage-limits-title">In Stage Limits</h2>
        </header>
        <form onSubmit={submit} noValidate>
          <div className="modal-body">
            <p className="field-hint">
              Days in an open stage before an opportunity needs attention and when it is stalled. Every list, page, board and filter uses these; Won and
              Lost are never rated.
            </p>
            <table className="limits-table">
              <thead>
                <tr>
                  <th scope="col">Stage</th>
                  <th scope="col">Needs attention at</th>
                  <th scope="col">Stalled at</th>
                </tr>
              </thead>
              <tbody>
                {stages.map((s) => (
                  <tr key={s} className={problem(s) ? "has-problem" : ""}>
                    <th scope="row">
                      {s}
                      <small>Default {limits.defaults[s][0]} / {limits.defaults[s][1]}</small>
                    </th>
                    {[0, 1].map((i) => (
                      <td key={i}>
                        <input
                          type="number"
                          inputMode="numeric"
                          min={0}
                          max={limits.max_days}
                          step={1}
                          value={values[s][i]}
                          onChange={(e) => change(s, i, e.target.value)}
                          aria-label={`${s}: ${i ? "stalled" : "needs attention"} at, in days`}
                          aria-invalid={!!problem(s) || undefined}
                        />{" "}
                        days
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="link" disabled={busy} onClick={() => setValues(Object.fromEntries(stages.map((s) => [s, limits.defaults[s].map(String)])))}>
              Use the defaults
            </button>
            <button type="button" className="sf-button" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="sf-button brand" disabled={busy} aria-busy={busy}>
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

// A board card's details (hover, keyboard focus or a tap on its details button): the stage time with its rating and
// limits, the next open task this user can see, the Client POC (masked phone) and Call / Log a call / Email. Built from
// what the page already has (the opportunity, its contact and the tasks this user can see): nothing is asked for per
// card. Drawn beside the card (or under / above it on a narrow screen), always inside the window.
export function CardDetails({ id, record: r, contacts, tasks, limits, actions }) {
  const box = useRef(null);
  const [pos, setPos] = useState(null);
  useLayoutEffect(() => {
    const card = box.current?.closest(".kanban-card");
    if (!card) return;
    const a = card.getBoundingClientRect();
    const size = box.current.getBoundingClientRect();
    const view = { width: window.innerWidth, height: window.innerHeight };
    const m = 8;
    const fit = (top) => Math.round(Math.max(m, Math.min(top, view.height - size.height - m)));
    const next =
      a.right + m + size.width <= view.width - m
        ? { left: Math.round(a.right + m), top: fit(a.top) }
        : a.left - m - size.width >= m
          ? { left: Math.round(a.left - m - size.width), top: fit(a.top) }
          : previewPlacement(a, size, view, { gap: 6, margin: m });
    setPos((old) => (old && old.left === next.left && old.top === next.top ? old : next));
  }, [r.id]);
  const s = opportunityClockSummary(r.in_stage, r.stage);
  const limit = stageLimitText(limits?.limits, r.stage);
  const task = nextOpenTask(tasks, r.id);
  const poc = opportunityPoc(r, contacts);
  return (
    <div
      ref={box}
      id={id}
      className="card-details"
      role="dialog"
      aria-label={`Details: ${r.name}`}
      style={pos || { top: 0, left: 0, visibility: "hidden" }}
    >
      <header>
        <a href={`#/opportunities/${r.id}`}>{r.name}</a>
        <p>{r.account_name || "No account"}</p>
      </header>
      <section>
        <h4>In stage</h4>
        {s ? (
          <p className="card-details-stage">
            <span>{s.text}</span>
            {s.badge && <span className={`stage-badge in-stage ${s.tone}`}>{s.badge}</span>}
          </p>
        ) : (
          <p className="muted">Not recorded</p>
        )}
        {limit && <p className="muted">{limit}</p>}
      </section>
      <section>
        <h4>Next task</h4>
        {task ? (
          <p>
            <b>{task.title}</b>
            <br />
            <span className={task.isOverdue ? "overdue" : ""}>
              Due {shortDate(task.due_date)}
              {task.isOverdue ? " (overdue)" : ""}
            </span>{" "}
            · {task.owner || "No owner"}
          </p>
        ) : (
          <p>No open task. Add the next follow-up.</p>
        )}
        {!task && actions.addTask && (
          <button type="button" className="sf-button small" onClick={actions.addTask}>
            Add task
          </button>
        )}
      </section>
      <section>
        <h4>Client POC</h4>
        {poc.contact ? (
          <p>
            {poc.name}
            <br />
            <span className={poc.phone ? "" : "muted"}>{poc.phone ? maskPhone(poc.phone) : "No phone number"}</span>
            {!poc.email && (
              <>
                <br />
                <span className="muted">No email address</span>
              </>
            )}
          </p>
        ) : (
          <p>
            {poc.name && (
              <>
                {poc.name}
                <br />
              </>
            )}
            <span className="muted">{poc.missing}</span>
          </p>
        )}
      </section>
      <div className="card-details-actions">
        {/* Call only opens the phone app (nothing is recorded); the number is read when Call is pressed */}
        <button type="button" className="sf-button small" disabled={!poc.phone} onClick={() => (window.location.href = telHref(poc.phone))}>
          Call
        </button>
        {actions.logCall && (
          <button type="button" className="sf-button small" onClick={() => actions.logCall(poc.name)}>
            Log a call
          </button>
        )}
        {actions.email && (
          <button type="button" className="sf-button small" disabled={!poc.email} onClick={() => actions.email(poc)}>
            Email
          </button>
        )}
      </div>
    </div>
  );
}
