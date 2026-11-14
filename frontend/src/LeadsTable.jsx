// The Leads list: every list view (All Open Leads, My Open Leads, Uploaded Leads...) is loaded from the server
// page by page with search and sorting, so it stays fast with 100,000s of leads. Uploaded leads have Lead Source "Upload".
// The Kanban view uses the same query: one request per status column, each with its own total and its own page of
// cards (Previous / Next per column, cards per page as on the List page). The filters, search and sort are shared.
// Tick the checkboxes to transfer or delete several leads at once (the server checks each lead and skips the ones you can't change):
// a selection bar takes the toolbar's place while leads are ticked.
import React, { useEffect, useRef, useState } from "react";
import { api, apiRequest } from "./api";
import { leadBoardColumns, leadConvertChoice } from "./domain";
import LeadsKanban from "./LeadsKanban";
import { NewCampaign, queuedMessage, watchCampaign } from "./CampaignsPage";
import { can, canCreateSales } from "./permissions";
import { DateCell, Icon, PAGE_SIZES, Pagination, PhoneReveal, StageBadge } from "./ui";
import { dateTime } from "./format";
import { FilterButton, rangeBounds, Th } from "./Filters";
import {
  boardPages,
  boardQueryKey,
  clampPage,
  defaultSortDirection,
  filterChips,
  latestRequests,
  leadSelectionActions,
  leadsEmptyMessage,
  pageSummary,
  selectionSummary,
  sortText,
  withColumnPage,
} from "./listHelpers";

const PAGE = 15; // leads per page to start with (Rows per page offers more; the server allows up to 500)
// [heading, sort key, column width]. The checkbox, row number and Name stay in view when the table scrolls sideways.
const COLUMNS = [
  ["Name", "name", 180],
  ["Company", "company", 168],
  ["Title", "title", 136],
  ["Email", "email", 196],
  ["Phone", "phone", 150],
  ["Status", "stage", 124],
  ["Source", "source", 104],
  ["Owner", "owner", 144],
  // who the lead was last transferred to, and when (empty when it never changed owner)
  ["Transferred To", "transferred", 200],
  ["Created", "created", 108],
  ["Last Modified", "modified", 124],
];

// a cell that keeps to one line (or wraps with "Wrap text") and shows the full text on hover
const Cell = ({ children, title, className = "" }) => (
  <td className={`cell ${className}`} title={title ?? (typeof children === "string" ? children : undefined)}>
    {children}
  </td>
);

const plural = (n, word = "lead") => `${Number(n).toLocaleString()} ${word}${n === 1 ? "" : "s"}`;

// One line about the leads that were left out, e.g. "2 skipped: Ana Ruiz (converted), Lead 41 (not found)"
const skippedText = (skipped) =>
  skipped.length
    ? ` ${plural(skipped.length)} skipped: ${skipped
        .slice(0, 3)
        .map((s) => `${s.name} (${s.reason})`)
        .join("; ")}${skipped.length > 3 ? ` and ${skipped.length - 3} more` : ""}.`
    : "";

// A select-all checkbox that also shows the "some selected" dash
function Check({ checked, some = false, onChange, label, inputRef, disabled = false }) {
  const own = useRef(null);
  const ref = inputRef || own;
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = some && !checked;
  }, [some, checked, ref]);
  return (
    <input ref={ref} type="checkbox" className="row-check" checked={checked} onChange={onChange} aria-label={label} title={label} disabled={disabled} />
  );
}

// Transfer / delete dialog for the selected leads
// A short explanation with OK (nothing is saved or sent)
function NoticeDialog({ title, message, onClose }) {
  const ok = useRef(null);
  useEffect(() => {
    ok.current?.focus();
    const key = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <section className="modal small-modal" role="alertdialog" aria-modal="true" aria-labelledby="notice-title" aria-describedby="notice-text">
        <button className="modal-close" aria-label="Close dialog" onClick={onClose}>
          <Icon name="close" size={18} />
        </button>
        <header className="modal-header">
          <h2 id="notice-title">{title}</h2>
        </header>
        <div className="modal-body">
          <p id="notice-text">{message}</p>
        </div>
        <footer className="modal-footer">
          <button ref={ok} className="sf-button brand" onClick={onClose}>
            OK
          </button>
        </footer>
      </section>
    </div>
  );
}

function BulkDialog({ action, count, users, me, onClose, onDone }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const transfer = action.type === "transfer";
  useEffect(() => {
    const key = (e) => e.key === "Escape" && !busy && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [busy, onClose]);
  const submit = async (e) => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(e.currentTarget));
    setBusy(true);
    setError("");
    try {
      const res = transfer
        ? await api.bulkTransferLeads(action.ids, Number(v.to_user_id), v.note)
        : await api.bulkDeleteLeads(action.ids);
      onDone(res);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <section className="modal small-modal" role="dialog" aria-modal="true" aria-labelledby="bulk-title">
        <button className="modal-close" aria-label="Close dialog" onClick={onClose} disabled={busy}>
          <Icon name="close" size={18} />
        </button>
        <header className="modal-header">
          <h2 id="bulk-title">{transfer ? `Transfer ${plural(count)}` : `Delete ${plural(count)}`}</h2>
        </header>
        <form onSubmit={submit}>
          <div className="modal-body bulk-form">
            {transfer ? (
              <>
                <p className="field-hint">
                  Each lead continues at its stage with its history. Its open follow-ups, due dates and reminders go to the new owner, who
                  is told what's next. Converted or closed leads, and leads you can't transfer, are skipped.
                </p>
                <label className="field">
                  <span>
                    <abbr title="required">*</abbr> Transfer to
                  </span>
                  <select name="to_user_id" required defaultValue="">
                    <option value="" disabled>
                      Select a user…
                    </option>
                    {users
                      .filter((u) => u.is_active !== false)
                      .map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.full_name} ({u.role}){u.id === me?.id ? " - me" : ""}
                        </option>
                      ))}
                  </select>
                </label>
                <label className="field">
                  <span>Note</span>
                  <textarea name="note" rows={3} maxLength={300} />
                </label>
              </>
            ) : (
              <p className="modal-subtitle">
                Delete {plural(count)} with their tasks, notes and history? This can't be undone. Converted leads, and leads you can't
                change, are skipped.
              </p>
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
            <button type="submit" className={`sf-button ${transfer ? "brand" : "danger"}`} disabled={busy} aria-busy={busy}>
              {busy ? "Working…" : transfer ? "Transfer" : "Delete"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}


export default function LeadsTable({
  view,
  activity = null, // Home's pills: "upcoming" | "past" | "none"
  createdFrom = null, // Home's period: created_at in [createdFrom, createdTo)
  createdTo = null,
  viewName = "",
  stage,
  filters = {},
  defs = [],
  onFilter,
  onSummary,
  refresh = 0,
  mode = "table",
  onMode,
  user,
  setModal,
  users = [],
  notify = () => {},
  reload = () => Promise.resolve(),
}) {
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [sort, setSort] = useState({ col: "created", dir: "desc" });
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(PAGE); // rows per page (the server's limit)
  const [result, setResult] = useState(null);
  const [board, setBoard] = useState(null); // Kanban: { stage: { total, items } } for the columns this list can have
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  // Kanban: cards per column (the List page's choices), each column's page for the current board query, and the
  // columns being loaded
  const [cardSize, setCardSize] = useState(PAGE);
  const [colPages, setColPages] = useState({ key: "", pages: {} });
  const [busyCols, setBusyCols] = useState({});
  const requests = useRef(latestRequests());
  const loadedBoard = useRef({ key: null, reload: null, pages: {} });
  const [selected, setSelected] = useState(() => new Set());
  const [bulk, setBulk] = useState(null); // { type: "transfer" | "delete", ids }
  const [campaignFor, setCampaignFor] = useState(null); // lead ids for "Email" (a campaign to the selected leads)
  // a short explanation with OK: "one lead at a time" when Convert is chosen with several ticked, or why an action is off
  const [notice, setNotice] = useState(null); // { title, message }
  const [wrap, setWrap] = useState(false); // "Wrap text": long values on several lines instead of ending in "…"
  const [scrolled, setScrolled] = useState(false); // the table is scrolled sideways (shadow beside the Name column)
  const [again, setAgain] = useState(0); // reloads the list after a bulk action, or on Try again
  const selectAll = useRef(null);
  const kanban = mode === "kanban";
  const columns = leadBoardColumns(view, stage || filters.stage);

  useEffect(() => {
    const t = setTimeout(() => (setTerm(search.trim()), setPage(0)), 350); // search after typing stops
    return () => clearTimeout(t);
  }, [search]);
  const filterKey = JSON.stringify(filters);
  useEffect(() => setPage(0), [view, stage, filterKey]);
  useEffect(() => setSelected(new Set()), [view, stage, filterKey, term, kanban]); // a new list starts with nothing ticked

  // GET /leads/page with the list view, filters, search and sort (the List page and every Kanban column)
  const load = (extra) => {
    const params = new URLSearchParams({ view, sort: sort.col, direction: sort.dir });
    if (activity) params.set("activity", activity);
    if (createdFrom) params.set("created_from", createdFrom);
    if (createdTo) params.set("created_to", createdTo);
    if (filters.source) params.set("source", filters.source);
    if (filters.owner) params.set("owner", filters.owner);
    for (const key of ["created", "modified"]) {
      if (!filters[key]) continue;
      const [from, to] = rangeBounds(filters[key], filters[`${key}_from`], filters[`${key}_to`]);
      if (from) params.set(`${key}_from`, from.toISOString());
      if (to) params.set(`${key}_to`, to.toISOString());
    }
    if (term) params.set("search", term);
    return apiRequest(`/leads/page?${new URLSearchParams([...params, ...Object.entries(extra)])}`);
  };

  useEffect(() => {
    if (kanban) return undefined;
    let current = true;
    setLoading(true);
    // a failed load shows the error with Try again, not the previous list's rows or an empty-list message
    load({ ...(stage || filters.stage ? { stage: stage || filters.stage } : {}), offset: page * size, limit: size })
      .then((r) => current && (setResult(r), setError(""), setLoading(false)))
      .catch((err) => current && (setError(err.message), setLoading(false), setResult(null)));
    return () => {
      current = false;
    };
  }, [kanban, view, stage, filterKey, term, sort, page, size, refresh, again]); // eslint-disable-line react-hooks/exhaustive-deps

  // Kanban: one request per shown column, for that column's page. A new board query (list view, filters, search, sort,
  // cards per page) loads every column from its first page; Previous / Next loads only that column; a saved stage
  // change (refresh) or Try again reloads every column at its page. Only the latest request of a column is shown.
  const boardKey = boardQueryKey({ view, stage: stage || filters.stage, filters, search: term, sort, size: cardSize });
  const pagesNow = boardPages(colPages, boardKey);
  const shownColumns = columns.filter((c) => !c.excluded);
  useEffect(() => {
    if (!kanban) {
      loadedBoard.current = { key: null, reload: null, pages: {} };
      return;
    }
    const reload = `${refresh}|${again}`;
    const last = loadedBoard.current;
    const newQuery = last.key !== boardKey;
    const everything = newQuery || last.reload !== reload;
    const todo = shownColumns.filter((c) => everything || (last.pages[c.stage] || 0) !== (pagesNow[c.stage] || 0));
    loadedBoard.current = { key: boardKey, reload, pages: pagesNow };
    if (newQuery) {
      requests.current.forgetAll(); // answers to the previous query are dropped
      setBoard(null);
    }
    todo.forEach(({ stage: column }) => {
      const at = pagesNow[column] || 0;
      const id = requests.current.start(column);
      setBusyCols((b) => ({ ...b, [column]: true }));
      load({ stage: column, offset: at * cardSize, limit: cardSize })
        .then((r) => {
          if (!requests.current.isLatest(column, id)) return;
          const fixed = clampPage(at, r.total, cardSize);
          if (fixed !== at) {
            // fewer cards than before (a stage change moved some out): show the column's last page instead
            setColPages((state) => withColumnPage(state, boardKey, column, fixed));
            return;
          }
          setBoard((b) => ({ ...(b || {}), [column]: { ...r, page: at } }));
          setError("");
        })
        .catch((err) => requests.current.isLatest(column, id) && setError(err.message))
        .finally(() => requests.current.isLatest(column, id) && setBusyCols((b) => ({ ...b, [column]: false })));
    });
  }, [kanban, boardKey, JSON.stringify(pagesNow), refresh, again]); // eslint-disable-line react-hooks/exhaustive-deps
  const goToColumnPage = (column, at) => setColPages((state) => withColumnPage(state, boardKey, column, at));
  const boardBusy = shownColumns.some((c) => busyCols[c.stage]);
  const boardLoaded = !!board && shownColumns.every((c) => board[c.stage]);

  const loaded = kanban ? boardLoaded : result;
  const total = kanban
    ? shownColumns.reduce((sum, c) => sum + (board?.[c.stage]?.total || 0), 0)
    : result?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / size));
  // fewer leads than before (a delete, a transfer, another page size): a page past the end moves back to the last one
  useEffect(() => {
    if (!kanban && result) setPage((p) => clampPage(p, result.total, size));
  }, [result, size, kanban]);
  const sortBy = (col) => {
    setSort((s) => ({ col, dir: s.col === col && s.dir === "asc" ? "desc" : "asc" }));
    setPage(0);
  };
  const sortLabel = COLUMNS.find(([, c]) => c === sort.col)?.[0];
  // the count and sort order are shown under the list title (ListView)
  useEffect(() => {
    onSummary?.({ loaded: !!loaded, failed: !loaded && !!error, total, sort: sortText(sortLabel, sort.col, sort.dir) });
  }, [!!loaded, !!error, total, sortLabel, sort.col, sort.dir]); // eslint-disable-line react-hooks/exhaustive-deps

  // Selection: ticks stay when you change pages, so you can pick leads from several pages
  const items = result?.items || [];
  // the rows seen so far, so a lead ticked on another page can still be opened in the Convert popup
  const seen = useRef(new Map());
  items.forEach((lead) => seen.current.set(lead.id, lead));
  // Convert to Opportunity: one open lead you may convert (owner or "Edit team records"; the Admin included)
  const convertChoice = leadConvertChoice([...selected].map((id) => seen.current.get(id)), (lead) => ({
    canEdit: lead.owner_id === user?.id || can(user, "edit_team_records"),
    canCreateSales: canCreateSales(user),
  }));
  const canTransferAny = !!user && (user.role === "Admin" || can(user, "reassign_owner") || can(user, "transfer_leads"));
  const pageIds = items.map((l) => l.id);
  const ticked = selectionSummary(selected, pageIds);
  const allOnPage = pageIds.length > 0 && ticked.onPage === pageIds.length;
  const toggle = (id) =>
    setSelected((s) => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const togglePage = () =>
    setSelected((s) => {
      const next = new Set(s);
      pageIds.forEach((id) => (allOnPage ? next.delete(id) : next.add(id)));
      return next;
    });
  const clearSelection = () => {
    setSelected(new Set());
    requestAnimationFrame(() => selectAll.current?.focus()); // the bar goes away: keep the keyboard in the table
  };
  // the actions for the ticked leads (listHelpers.js): Convert, Email Campaign, Transfer, Delete
  const actions = leadSelectionActions({
    count: selected.size,
    convertChoice,
    canCampaign: can(user, "send_campaigns"),
    canTransfer: canTransferAny,
  });
  const run = {
    // opens the usual Convert popup for the one ticked lead (nothing is converted until it's saved);
    // with several ticked it only explains (no request is sent)
    convert: () =>
      convertChoice.explain ? setNotice({ title: "Convert to Opportunity", message: convertChoice.explain }) : setModal(convertChoice.action),
    // a campaign to the ticked leads (unsubscribed / invalid emails are left out)
    campaign: () => setCampaignFor([...selected]),
    transfer: () => setBulk({ type: "transfer", ids: [...selected] }),
    delete: () => setBulk({ type: "delete", ids: [...selected] }),
  };
  const finish = (res) => {
    const transfer = bulk.type === "transfer";
    const done = transfer ? res.transferred : res.deleted;
    notify(
      (done
        ? transfer
          ? `${plural(done)} transferred to ${res.to}.`
          : `${plural(done)} deleted.`
        : transfer
          ? "No leads were transferred."
          : "No leads were deleted.") + skippedText(res.skipped || []),
    );
    setBulk(null);
    setSelected(new Set());
    setAgain((n) => n + 1);
    reload().catch(() => {});
  };

  const clearSearch = () => {
    setSearch("");
    setTerm("");
    setPage(0);
  };
  const chips = filterChips(defs, filters);
  const empty = leadsEmptyMessage({ search: !!term, filtered: chips.length > 0, view, viewName });
  const selecting = !kanban && selected.size > 0;
  const summary = pageSummary({ start: page * size, size, total, noun: "lead" });

  return (
    <>
      <section className="card table-card leads-card" aria-label={`${viewName || "Leads"} list`}>
        {selecting ? (
          // while leads are ticked, the bar takes the toolbar's place (searching, filtering or switching to Kanban
          // would clear the ticks)
          <div className="selection-bar" role="region" aria-label="Selected leads">
            <p className="selection-summary">
              <b aria-live="polite">{plural(ticked.count)} selected</b>
              <span>{ticked.where}</span>
            </p>
            <button type="button" className="link selection-clear" onClick={clearSelection}>
              Clear selection
            </button>
            <div className="selection-actions">
              {actions.map((a) => (
                <button
                  key={a.key}
                  type="button"
                  className={`sf-button ${a.danger ? "danger-text" : ""}`}
                  aria-disabled={a.disabled || undefined}
                  aria-describedby={a.disabled && a.reason ? `lead-action-${a.key}-why` : undefined}
                  title={a.disabled ? a.reason : undefined}
                  // an action that is off sends nothing: it says why (as the Actions menu did under the item)
                  onClick={() => (a.disabled ? a.reason && setNotice({ title: a.label, message: a.reason }) : run[a.key]())}
                >
                  {a.label}
                </button>
              ))}
            </div>
            {actions
              .filter((a) => a.disabled && a.reason)
              .map((a) => (
                <span key={a.key} id={`lead-action-${a.key}-why`} className="sr-only">
                  {a.reason}
                </span>
              ))}
          </div>
        ) : (
          <div className="leads-toolbar">
            <div className="list-search leads-search">
              <Icon name="search" size={14} />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === "Escape" && search && (e.stopPropagation(), clearSearch())}
                placeholder="Search name, company, email, phone…"
                aria-label="Search this list"
              />
              {search && (
                <button type="button" className="search-clear" onClick={clearSearch} aria-label="Clear search" title="Clear search">
                  <Icon name="close" size={14} />
                </button>
              )}
            </div>
            {chips.length > 0 && (
              <div className="filter-chips" role="group" aria-label="Applied filters">
                {chips.map((c) => (
                  <span key={c.key} className="filter-chip">
                    <span>{c.text}</span>
                    <button type="button" onClick={() => onFilter(c.without)} aria-label={`Remove filter ${c.text}`} title="Remove this filter">
                      <Icon name="close" size={12} />
                    </button>
                  </span>
                ))}
                <button type="button" className="link clear-all" onClick={() => (onFilter({}), clearSearch())}>
                  Clear all
                </button>
              </div>
            )}
            <div className="toolbar-end">
              {!kanban && (
                <button
                  type="button"
                  className="sf-button tool-toggle"
                  aria-pressed={wrap}
                  onClick={() => setWrap((w) => !w)}
                  title="Show long names, companies and emails in full"
                >
                  {wrap && <Icon name="check" size={14} />}
                  Wrap text
                </button>
              )}
              {onMode && (
                <div className="toggle-group view-toggle" role="group" aria-label="Display as">
                  <button type="button" className={kanban ? "" : "on"} onClick={() => onMode("table")} aria-pressed={!kanban}>
                    <Icon name="list" size={15} />
                    <span>List</span>
                  </button>
                  <button type="button" className={kanban ? "on" : ""} onClick={() => onMode("kanban")} aria-pressed={kanban}>
                    <Icon name="kanban" size={15} />
                    <span>Kanban</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
        {error && (
          <div className="alert leads-alert" role="alert">
            <Icon name="warn" size={16} />
            <span>
              <b>The leads couldn&apos;t be loaded.</b> {error}
            </span>
            <button type="button" className="sf-button small" onClick={() => setAgain((n) => n + 1)} disabled={kanban ? boardBusy : loading}>
              {(kanban ? boardBusy : loading) ? "Trying…" : "Try again"}
            </button>
          </div>
        )}
        {kanban && (
          // the List page's filters, as buttons (the board has no column headers), with the sort and cards per column
          <div className="board-bar" role="group" aria-label="Kanban filters, sorting and cards per column">
            <div className="board-filters">
              <span className="board-bar-label">Filter</span>
              {defs.map((def) => (
                <FilterButton key={def.key} def={def} values={filters} onChange={onFilter} />
              ))}
              {chips.length > 0 && (
                <button type="button" className="link board-clear" onClick={() => onFilter({})}>
                  Clear filters
                </button>
              )}
            </div>
            <div className="board-options">
              {/* the field only: each starts in its default order (dates newest first, text A–Z); the summary under
                  the page title says the order in use */}
              <label className="board-select">
                <span>Sort by</span>
                <select value={sort.col} onChange={(e) => setSort({ col: e.target.value, dir: defaultSortDirection(e.target.value) })}>
                  {COLUMNS.map(([label, col]) => (
                    <option key={col} value={col}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="board-select">
                <span>Cards per column</span>
                <select value={cardSize} onChange={(e) => setCardSize(Number(e.target.value))}>
                  {PAGE_SIZES.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        )}
        {kanban ? (
          <LeadsKanban
            columns={columns}
            board={board}
            user={user}
            setModal={setModal}
            size={cardSize}
            pages={pagesNow}
            busy={busyCols}
            onPage={goToColumnPage}
          />
        ) : (
          <>
            <div
              className={`table-scroll leads-scroll ${scrolled ? "scrolled" : ""} ${loading && result ? "is-loading" : ""}`}
              role="region"
              aria-label="Leads table"
              tabIndex={0}
              onScroll={(e) => {
                const sideways = e.currentTarget.scrollLeft > 0;
                if (sideways !== scrolled) setScrolled(sideways);
              }}
            >
              <table className={`sf-table leads-table ${wrap ? "wrap" : ""}`} aria-busy={loading || undefined}>
                <caption className="sr-only">
                  {viewName || "Leads"}. {result ? summary : "Loading"}. Select a column name to sort; the arrow beside it filters.
                </caption>
                <colgroup>
                  <col style={{ width: 40 }} />
                  <col style={{ width: 44 }} />
                  {COLUMNS.map(([, col, width]) => (
                    <col key={col} style={{ width }} />
                  ))}
                </colgroup>
                <thead>
                  <tr>
                    <th className="select-col sticky-col">
                      <Check
                        inputRef={selectAll}
                        checked={allOnPage}
                        some={ticked.onPage > 0}
                        onChange={togglePage}
                        disabled={!pageIds.length}
                        label={`Select all ${pageIds.length} leads on this page`}
                      />
                    </th>
                    <th className="rownum sticky-col" aria-label="Row number" />
                    {COLUMNS.map(([label, col]) => (
                      <Th
                        key={col}
                        label={label}
                        className={col === "name" ? "col-name sticky-col" : ""}
                        sorted={sort.col === col}
                        flip={sort.dir === "asc"}
                        onSort={() => sortBy(col)}
                        filter={defs.find((f) => f.key === col)}
                        values={filters}
                        onChange={onFilter}
                      />
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((l, i) => (
                    <tr key={l.id} className={selected.has(l.id) ? "row-selected" : undefined}>
                      <td className="select-col sticky-col">
                        <input
                          type="checkbox"
                          className="row-check"
                          checked={selected.has(l.id)}
                          onChange={() => toggle(l.id)}
                          aria-label={`Select ${l.name}`}
                        />
                      </td>
                      <td className="rownum sticky-col">{(page * size + i + 1).toLocaleString()}</td>
                      <Cell title={l.name} className="col-name sticky-col">
                        <a className="lead-link" href={`#/leads/${l.id}`}>
                          {l.name}
                        </a>
                      </Cell>
                      <Cell className="strong">{l.company || ""}</Cell>
                      <Cell>{l.title || ""}</Cell>
                      <Cell title={l.email_invalid_at ? `Invalid email: ${l.email_invalid_reason || ""}` : l.unsubscribed_at ? "Unsubscribed" : l.email || ""}>
                        {l.email && (
                          <a href={`mailto:${l.email}`} className={l.email_invalid_at ? "email-invalid" : l.unsubscribed_at ? "email-off" : ""}>
                            {l.email}
                          </a>
                        )}
                      </Cell>
                      <Cell className="phone">
                        <PhoneReveal value={l.phone} />
                      </Cell>
                      <td className="cell">
                        <StageBadge stage={l.stage} />
                      </td>
                      <Cell title={l.uploaded_from ? `Uploaded from ${l.uploaded_from}` : l.source}>{l.source}</Cell>
                      <Cell className="strong">{l.owner_name || ""}</Cell>
                      <Cell
                        className="transferred"
                        title={l.last_transferred_to ? `Transferred to ${l.last_transferred_to} on ${dateTime(l.last_transferred_at)}` : "Not transferred"}
                      >
                        {l.last_transferred_to && (
                          <>
                            {l.last_transferred_to} <small className="muted">{dateTime(l.last_transferred_at)}</small>
                          </>
                        )}
                      </Cell>
                      <Cell className="date" title={dateTime(l.created_at)}>
                        <DateCell value={l.created_at} />
                      </Cell>
                      <Cell className="date" title={dateTime(l.updated_at)}>
                        <DateCell value={l.updated_at} />
                      </Cell>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!result && !error && (
                <p className="list-state" role="status">
                  <span className="spinner small" aria-hidden="true" />
                  Loading leads…
                </p>
              )}
              {result && !result.items.length && !loading && (
                <div className="list-state list-empty" role="status">
                  <b>{empty.title}</b>
                  <span>{empty.text}</span>
                  {empty.clear && (
                    <div className="list-state-actions">
                      {term && (
                        <button type="button" className="sf-button" onClick={clearSearch}>
                          Clear search
                        </button>
                      )}
                      {chips.length > 0 && (
                        <button type="button" className="sf-button" onClick={() => onFilter({})}>
                          Clear filters
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
            {result && (
              <Pagination
                noun="lead"
                label="Leads pages"
                page={page + 1}
                pages={pages}
                size={size}
                total={total}
                start={page * size}
                busy={loading}
                // next to Previous / Next: ticked leads stay ticked on other pages
                note={selected.size > 0 && pages > 1 ? `${plural(selected.size)} selected; ticks stay when you change pages` : ""}
                setPage={(p) => setPage(p - 1)}
                setSize={(n) => (setSize(n), setPage(0))}
              />
            )}
          </>
        )}
      </section>
      {notice && <NoticeDialog title={notice.title} message={notice.message} onClose={() => setNotice(null)} />}
      {bulk && (
        <BulkDialog
          action={bulk}
          count={bulk.ids.length}
          users={users}
          me={user}
          onClose={() => setBulk(null)}
          onDone={finish}
        />
      )}
      {campaignFor && (
        <NewCampaign
          user={user}
          users={users}
          leadIds={campaignFor}
          onClose={() => setCampaignFor(null)}
          onCreated={(c) => {
            setCampaignFor(null);
            setSelected(new Set());
            notify(queuedMessage(c));
            watchCampaign(c); // the progress pop-up
            window.location.hash = `#/campaigns/${c.id}`;
          }}
        />
      )}
    </>
  );
}
