// Leads > Deleted Leads (Admin and Managers): the leads that were deleted, newest first. Tick one, several or all of
// them and Restore: they come back, with their notes, in the Unassigned Pool (Unassigned Leads). A deleted lead can be
// restored for 90 days, then it is deleted for good. The list and the restore are on the server
// (backend/app/routers/deleted_leads.py).
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { DateCell, Icon, PAGE_SIZES, Pagination, StageBadge } from "./ui";

const plural = (n) => `${Number(n).toLocaleString()} lead${n === 1 ? "" : "s"}`;
export const KEEP_DAYS = 90; // the server's KEEP_DAYS

// "Days Left" to restore: 7 days or less is shown as urgent
function DaysLeft({ days, expiresAt }) {
  if (days == null) return null;
  const text = days === 0 ? "Last day" : `${days} day${days === 1 ? "" : "s"}`;
  return (
    <span className={`days-left ${days <= 7 ? "urgent" : ""}`} title={expiresAt ? `Deleted for good after ${new Date(expiresAt).toLocaleDateString()}` : undefined}>
      {text}
    </span>
  );
}

// "3 leads restored to Unassigned Leads. 1 skipped: Ana Ruiz (email used by Ana R.)."
export function restoreMessage(res) {
  const done = res.restored.length;
  const skipped = res.skipped || [];
  const text = done ? `${plural(done)} restored to Unassigned Leads.` : "No leads were restored.";
  return skipped.length
    ? `${text} ${plural(skipped.length)} skipped: ${skipped
        .slice(0, 3)
        .map((s) => `${s.name || `Deleted lead ${s.id}`} (${s.reason})`)
        .join("; ")}${skipped.length > 3 ? ` and ${skipped.length - 3} more` : ""}.`
    : text;
}

export default function DeletedLeads({ notify, reload, onSummary }) {
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(PAGE_SIZES[1]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [again, setAgain] = useState(0);
  const [selected, setSelected] = useState(new Set());
  const [confirm, setConfirm] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const selectAll = useRef(null);

  // search as you type, after a short pause
  useEffect(() => {
    const t = setTimeout(() => {
      setTerm(search.trim());
      setPage(0);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api
      .deletedLeads({ search: term, page: page + 1, page_size: size })
      .then((res) => {
        if (!live) return;
        setResult(res);
        setError("");
        onSummary?.({ loaded: true, total: res.total, sort: "Sorted by Deleted On (newest first)" });
      })
      .catch((e) => {
        if (!live) return;
        setError(e.message || "The deleted leads couldn't be loaded");
        onSummary?.({ failed: true });
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [term, page, size, again]); // eslint-disable-line react-hooks/exhaustive-deps

  const items = result?.items || [];
  const total = result?.total || 0;
  const pages = Math.max(1, Math.ceil(total / size));
  const pageIds = items.map((r) => r.id);
  const onPage = pageIds.filter((id) => selected.has(id)).length;
  const allOnPage = pageIds.length > 0 && onPage === pageIds.length;
  useEffect(() => {
    if (selectAll.current) selectAll.current.indeterminate = onPage > 0 && !allOnPage;
  }, [onPage, allOnPage]);

  const toggle = (id) =>
    setSelected((old) => {
      const next = new Set(old);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const togglePage = () =>
    setSelected((old) => {
      const next = new Set(old);
      pageIds.forEach((id) => (allOnPage ? next.delete(id) : next.add(id)));
      return next;
    });
  // every deleted lead in this list (all pages, with the search), up to 1,000 at a time
  const [pickingAll, setPickingAll] = useState(false);
  const selectEvery = async () => {
    setPickingAll(true);
    try {
      const ids = new Set();
      for (let p = 1; ids.size < Math.min(total, 1000); p += 1) {
        const res = await api.deletedLeads({ search: term, page: p, page_size: 200 });
        res.items.forEach((r) => ids.size < 1000 && ids.add(r.id));
        if (res.items.length < 200) break;
      }
      setSelected(ids);
    } catch (e) {
      notify(e.message || "The deleted leads couldn't be selected");
    } finally {
      setPickingAll(false);
    }
  };

  const restore = async () => {
    setRestoring(true);
    try {
      const res = await api.restoreLeads([...selected]);
      notify(restoreMessage(res));
      setSelected(new Set());
      setConfirm(false);
      setAgain((n) => n + 1);
      reload?.().catch(() => {});
    } catch (e) {
      notify(e.message || "The leads couldn't be restored");
    } finally {
      setRestoring(false);
    }
  };

  return (
    <>
      <section className="card table-card leads-card deleted-leads" aria-label="Deleted Leads list">
        {selected.size > 0 ? (
          <div className="selection-bar" role="region" aria-label="Selected deleted leads">
            <p className="selection-summary">
              <b aria-live="polite">{plural(selected.size)} selected</b>
              {total > selected.size && selected.size < 1000 && (
                <button type="button" className="link" onClick={selectEvery} disabled={pickingAll}>
                  {pickingAll ? "Selecting…" : `Select all ${plural(Math.min(total, 1000))}`}
                </button>
              )}
            </p>
            <button type="button" className="link selection-clear" onClick={() => setSelected(new Set())}>
              Clear selection
            </button>
            <div className="selection-actions">
              <button type="button" className="sf-button brand" onClick={() => setConfirm(true)}>
                <Icon name="refresh" size={14} />
                Restore
              </button>
            </div>
          </div>
        ) : (
          <div className="leads-toolbar">
            <div className="list-search leads-search">
              <Icon name="search" size={14} />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search name, company, email…"
                aria-label="Search deleted leads"
              />
              {search && (
                <button type="button" className="search-clear" onClick={() => setSearch("")} aria-label="Clear search" title="Clear search">
                  <Icon name="close" size={14} />
                </button>
              )}
            </div>
            <p className="deleted-leads-hint">
              Restore within {KEEP_DAYS} days. Restored leads go to Unassigned Leads.
            </p>
          </div>
        )}
        {error ? (
          <p className="list-state form-error" role="alert">
            {error}
          </p>
        ) : (
          <>
            <div className="table-scroll" role="region" aria-label="Deleted leads table" tabIndex={0}>
              <table className="sf-table" aria-busy={loading || undefined}>
                <thead>
                  <tr>
                    <th className="select-col">
                      <input
                        ref={selectAll}
                        type="checkbox"
                        className="row-check"
                        checked={allOnPage}
                        onChange={togglePage}
                        disabled={!pageIds.length}
                        aria-label={`Select all ${pageIds.length} deleted leads on this page`}
                      />
                    </th>
                    <th>Name</th>
                    <th>Company</th>
                    <th>Email</th>
                    <th>Status</th>
                    <th>Owner</th>
                    <th>Deleted By</th>
                    <th>Deleted On</th>
                    <th title={`A deleted lead can be restored for ${KEEP_DAYS} days`}>Days Left</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((r) => (
                    <tr key={r.id} className={selected.has(r.id) ? "row-selected" : undefined}>
                      <td className="select-col">
                        <input
                          type="checkbox"
                          className="row-check"
                          checked={selected.has(r.id)}
                          onChange={() => toggle(r.id)}
                          aria-label={`Select ${r.name}`}
                        />
                      </td>
                      <td>
                        <b>{r.name}</b>
                      </td>
                      <td>{r.company || ""}</td>
                      <td>{r.email || ""}</td>
                      <td>{r.stage && <StageBadge stage={r.stage} />}</td>
                      <td>{r.owner_name}</td>
                      <td>{r.deleted_by_name || ""}</td>
                      <td>
                        <DateCell value={r.deleted_at} />
                      </td>
                      <td>
                        <DaysLeft days={r.days_left} expiresAt={r.expires_at} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!result && (
                <p className="list-state" role="status">
                  <span className="spinner small" aria-hidden="true" />
                  Loading deleted leads…
                </p>
              )}
              {result && !items.length && !loading && (
                <div className="list-state list-empty" role="status">
                  <b>{term ? "No deleted leads match your search" : "No deleted leads"}</b>
                  <span>{term ? "Try another name, company or email." : `Leads that are deleted appear here for ${KEEP_DAYS} days, ready to restore.`}</span>
                </div>
              )}
            </div>
            {result && (
              <Pagination
                noun="deleted lead"
                label="Deleted leads pages"
                page={page + 1}
                pages={pages}
                size={size}
                total={total}
                start={page * size}
                busy={loading}
                note={selected.size > 0 && pages > 1 ? `${plural(selected.size)} selected; ticks stay when you change pages` : ""}
                setPage={(p) => setPage(p - 1)}
                setSize={(n) => (setSize(n), setPage(0))}
              />
            )}
          </>
        )}
      </section>
      {confirm && (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !restoring && setConfirm(false)}>
          <section className="modal small-modal" role="dialog" aria-modal="true" aria-labelledby="restore-title">
            <button className="modal-close" aria-label="Close dialog" onClick={() => setConfirm(false)} disabled={restoring}>
              <Icon name="close" size={18} />
            </button>
            <header className="modal-header">
              <h2 id="restore-title">Restore {plural(selected.size)}</h2>
            </header>
            <div className="modal-body bulk-form">
              <p className="modal-subtitle confirm-text">
                {selected.size === 1 ? "It'll" : "They'll"} move to <b>Unassigned Leads</b>, with {selected.size === 1 ? "its" : "their"} notes.
              </p>
            </div>
            <div className="modal-footer">
              <button type="button" className="sf-button" onClick={() => setConfirm(false)} disabled={restoring}>
                Cancel
              </button>
              <button type="button" className="sf-button brand" onClick={restore} disabled={restoring} aria-busy={restoring}>
                {restoring ? "Restoring…" : "Restore"}
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
