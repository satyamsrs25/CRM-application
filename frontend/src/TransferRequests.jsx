// Lead transfer requests: a user asks for someone else's lead; the lead's owner, the owner's Manager or the Admin
// approves (the lead moves to the requester) or rejects it (with a reason). Nothing moves without an approval.
// - RequestTransferDialog: "Request Transfer" on a lead page, or from the "email already in the CRM" message; for a
//   lead in the Unassigned Pool it is "Request Assignment" (a Salesperson; the Admin or their Manager approves)
// - AssignLeadDialog: "Assign" on a pooled lead's page (the Admin, or a Manager to their own Salespeople)
// - TransferRequestsPage (#/transfer-requests): To Approve, My Requests and All
import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { dateTime } from "./format";
import { Dialog } from "./LeadFiles";
import { poolAssignees } from "./permissions";
import {
  REQUEST_PAGE_SIZE,
  canBulkDecide,
  decisionSummary,
  keepSelection,
  requestCount,
  requestRange,
  tickableIds,
  toggleAllOnPage,
  toggleOne,
} from "./transferRequestRules";
import { Pagination } from "./ui";

const POOL_NAME = "Unassigned Pool";
// the Owner column: a request made from the pool shows the pool until the lead is assigned
const ownerText = (r) => r.owner_name || (r.pool ? POOL_NAME : "");

const STATUS_PILL = { Pending: "pill-warn", Approved: "pill-ok", Rejected: "pill-lost", Cancelled: "pill-past" };

export function RequestTransferDialog({ lead, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(null); // a pool request: who decides it, shown before the dialog closes
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const saved = await api.requestLeadTransfer(lead.id, reason.trim());
      if (saved.routing) {
        setSent(saved);
        setBusy(false);
      } else onDone(saved);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  const pool = !!lead.pool;
  if (sent)
    return (
      <Dialog
        title={`Request Assignment: ${lead.name}`}
        onClose={() => onDone(sent)}
        footer={
          <button className="sf-button brand" onClick={() => onDone(sent)} autoFocus>
            OK
          </button>
        }
      >
        <p role="status">Your request was sent. {sent.routing}</p>
      </Dialog>
    );
  return (
    <Dialog
      title={`${pool ? "Request Assignment" : "Request Transfer"}: ${lead.name}`}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button className="sf-button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="sf-button brand" form="transfer-request" disabled={busy || reason.trim().length < 3} aria-busy={busy}>
            {busy ? "Sending…" : "Send Request"}
          </button>
        </>
      }
    >
      <form id="transfer-request" className="transfer-form" onSubmit={submit}>
        <p className="muted">
          {pool
            ? "This lead is in the Unassigned Pool. Your Manager or the Admin must approve before it is assigned to you; " +
              "asking doesn't make it yours or let you change it."
            : `${lead.owner_name ? `${lead.owner_name} owns this lead. ` : ""}The owner, their Manager or the Admin must approve before the lead is transferred to you.`}
        </p>
        <label className="field">
          <span>
            <abbr title="required">*</abbr> Reason
          </span>
          <textarea value={reason} maxLength={300} rows={3} required autoFocus onChange={(e) => setReason(e.target.value)}
            placeholder="Why should this lead be yours? e.g. I met this customer at the expo" />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}

// Approve or reject one request (a reason is required to reject)
function DecideDialog({ request, decision, onClose, onDone }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const approve = decision === "approve";
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onDone(await api.decideTransferRequest(request.id, decision, note.trim()));
    } catch (err) {
      // decided meanwhile (by another approver, or the lead was assigned): nothing changed; the list is loaded again
      if (err.status === 409) return onDone(null, err.message);
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={`${approve ? "Approve" : "Reject"} ${request.pool ? "Request" : "Transfer"}: ${request.lead_name}`}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button className="sf-button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className={`sf-button ${approve ? "brand" : "danger"}`} form="transfer-decision" disabled={busy || (!approve && !note.trim())}>
            {busy ? "Saving…" : approve ? (request.pool ? "Approve & Assign" : "Approve & Transfer") : "Reject"}
          </button>
        </>
      }
    >
      <form id="transfer-decision" className="transfer-form" onSubmit={submit}>
        <p className="muted">
          {request.requested_by_name} asked for this lead: “{request.reason}”.{" "}
          {approve
            ? request.pool
              ? `The lead is assigned from the Unassigned Pool to ${request.requested_by_name} now. Its stage stays as it is.`
              : `The lead moves from ${request.owner_name} to ${request.requested_by_name} now, with its open follow-ups.`
            : "The lead stays where it is."}
        </p>
        <label className="field">
          <span>
            {!approve && <abbr title="required">*</abbr>} {approve ? "Note (optional)" : "Reason"}
          </span>
          <textarea value={note} maxLength={300} rows={3} required={!approve} autoFocus onChange={(e) => setNote(e.target.value)} />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}

// The header's "select all on this page" box: checked, unchecked, or partly (some of this page's requests ticked)
function TickAll({ rows, selected, onToggleAll }) {
  const box = useRef(null);
  const ids = tickableIds(rows);
  const ticked = ids.filter((id) => selected.has(id)).length;
  useEffect(() => {
    if (box.current) box.current.indeterminate = ticked > 0 && ticked < ids.length;
  }, [ticked, ids.length]);
  return (
    <input
      ref={box}
      type="checkbox"
      checked={ids.length > 0 && ticked === ids.length}
      disabled={!ids.length}
      onChange={onToggleAll}
      aria-label="Select all requests on this page that you can decide (this page only)"
      title="Selects the requests on this page only"
    />
  );
}

// The requests as a table, with Approve / Reject / Cancel on the ones you can act on. selectable (To Approve, the Admin
// or a Manager): a tick box on each request you may decide, and one in the header for this page's requests.
export function TransferRequestTable({ rows, onChange, showLead = true, focus = null, selectable = false, selected = new Set(), onToggle, onToggleAll }) {
  const [deciding, setDeciding] = useState(null); // { request, decision }
  const [error, setError] = useState("");
  // a request opened from a notification: highlighted and brought into view
  useEffect(() => {
    if (focus) document.getElementById(`transfer-request-${focus}`)?.scrollIntoView({ block: "center" });
  }, [focus, rows.length]);
  const cancel = async (r) => {
    setError("");
    try {
      onChange(await api.cancelTransferRequest(r.id));
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <div className="table-scroll">
        <table className="sf-table transfer-requests">
          <thead>
            <tr>
              {selectable && (
                <th className="select-col">
                  <TickAll rows={rows} selected={selected} onToggleAll={onToggleAll} />
                </th>
              )}
              {showLead && <th>Lead</th>}
              <th>Owner</th>
              <th>Requested By</th>
              <th>Reason</th>
              <th>Requested At</th>
              <th>Status</th>
              <th>Decision</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.id}
                id={`transfer-request-${r.id}`}
                className={[String(r.id) === String(focus) ? "row-focus" : "", selected.has(r.id) ? "row-selected" : ""].join(" ").trim() || undefined}
              >
                {selectable && (
                  <td className="select-col">
                    {r.can_decide && r.status === "Pending" && (
                      <input
                        type="checkbox"
                        checked={selected.has(r.id)}
                        onChange={() => onToggle(r.id)}
                        aria-label={`Select the request for ${r.lead_name} from ${r.requested_by_name}`}
                      />
                    )}
                  </td>
                )}
                {showLead && (
                  <td>
                    {r.can_open_lead ? <a href={`#/leads/${r.lead_id}`}>{r.lead_name}</a> : r.lead_name}
                    {r.company && <small className="muted block">{r.company}</small>}
                  </td>
                )}
                <td>{ownerText(r)}</td>
                <td>{r.requested_by_name}</td>
                <td className="wrap">{r.reason}</td>
                <td className="nowrap">{dateTime(r.created_at)}</td>
                <td>
                  <span className={`pill ${STATUS_PILL[r.status] || ""}`}>{r.status}</span>
                </td>
                <td className="wrap">
                  {r.decided_at && (
                    <>
                      {r.decided_by_name} • {dateTime(r.decided_at)}
                      {r.decision_note && <small className="muted block">{r.decision_note}</small>}
                    </>
                  )}
                </td>
                <td className="nowrap">
                  {r.can_decide && (
                    <>
                      <button className="sf-button brand small" onClick={() => setDeciding({ request: r, decision: "approve" })}>
                        Approve
                      </button>{" "}
                      <button className="sf-button small" onClick={() => setDeciding({ request: r, decision: "reject" })}>
                        Reject
                      </button>
                    </>
                  )}
                  {r.can_cancel && (
                    <button className="sf-button small" onClick={() => cancel(r)}>
                      Cancel Request
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {deciding && (
        <DecideDialog
          {...deciding}
          onClose={() => setDeciding(null)}
          onDone={(saved, stale) => {
            setDeciding(null);
            setError(stale || "");
            onChange(saved);
          }}
        />
      )}
    </>
  );
}

// Request Assignment for the leads ticked in the Leads list (a Salesperson, Unassigned Pool): one reason, one request
// per lead (each approved or rejected on its own). Nothing is assigned. Afterwards it says what was requested, what
// was not (already asked for, or assigned since it was ticked) and who decides.
export function BulkRequestDialog({ leadIds, others = 0, onClose }) {
  const count = leadIds.length;
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const leads = (n) => `${n.toLocaleString()} lead${n === 1 ? "" : "s"}`;
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setResult(await api.requestPoolLeads(leadIds, reason.trim()));
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };
  if (result) {
    const notDone = [...result.conflicts, ...result.skipped];
    return (
      <Dialog
        title="Request Assignment"
        onClose={() => onClose(true)}
        footer={
          <button className="sf-button brand" onClick={() => onClose(true)} autoFocus>
            Done
          </button>
        }
      >
        <div className="transfer-form" role="status">
          <p>
            <b>{result.requested ? `${leads(result.requested)} requested.` : "No leads were requested."}</b>{" "}
            {result.requested > 0 && result.routing}
          </p>
          {notDone.length > 0 && (
            <>
              <p className="muted">{leads(notDone.length)} not requested:</p>
              <ul className="request-results">
                {notDone.slice(0, 20).map((r) => (
                  <li key={r.lead_id}>
                    <b>{r.name}</b>: {r.reason}
                  </li>
                ))}
                {notDone.length > 20 && <li>and {(notDone.length - 20).toLocaleString()} more</li>}
              </ul>
            </>
          )}
        </div>
      </Dialog>
    );
  }
  return (
    <Dialog
      title={`Request Assignment: ${leads(count)} selected`}
      onClose={() => onClose(false)}
      busy={busy}
      footer={
        <>
          <button className="sf-button" onClick={() => onClose(false)} disabled={busy}>
            Cancel
          </button>
          <button className="sf-button brand" form="bulk-request" disabled={busy || reason.trim().length < 3} aria-busy={busy}>
            {busy ? "Sending…" : `Request ${leads(count)}`}
          </button>
        </>
      }
    >
      <form id="bulk-request" className="transfer-form" onSubmit={submit}>
        <p className="muted">
          You are asking for the {leads(count)} you selected from the Unassigned Pool. Each lead gets its own request, which your
          Manager or the Admin approves or rejects. Asking doesn&apos;t make them yours or let you change them.
          {others > 0 && ` The other ${leads(others)} you selected ${others === 1 ? "isn't" : "aren't"} in the pool and ${others === 1 ? "is" : "are"} left out.`}
        </p>
        <label className="field">
          <span>
            <abbr title="required">*</abbr> Reason (for all {leads(count)})
          </span>
          <textarea value={reason} maxLength={300} rows={3} required autoFocus onChange={(e) => setReason(e.target.value)}
            placeholder="Why should these leads be yours? e.g. They are in my territory" />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}

// Assign one pooled lead to a Salesperson (the Admin: any active Salesperson; a Manager: those who report to them).
// One lead at a time; if someone assigned it first, the server says so and nothing changes.
export function AssignLeadDialog({ lead, user, users, onClose, onDone }) {
  const people = poolAssignees(user, users);
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onDone(await api.assignLead(lead.id, { to_user_id: Number(to), note: note.trim() || null }));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={`Assign Lead: ${lead.name}`}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button className="sf-button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="sf-button brand" form="assign-lead" disabled={busy || !to} aria-busy={busy}>
            {busy ? "Assigning…" : "Assign"}
          </button>
        </>
      }
    >
      <form id="assign-lead" className="transfer-form" onSubmit={submit}>
        <p className="muted">
          This lead is in the Unassigned Pool. Only its owner changes: its stage, Created By and Created Date stay as they are.
          {user?.role === "Admin" ? "" : " You can assign it to the Salespeople who report to you."}
        </p>
        <label className="field">
          <span>
            <abbr title="required">*</abbr> Assign to
          </span>
          <select value={to} required onChange={(e) => setTo(e.target.value)} autoFocus>
            <option value="" disabled>
              {people.length ? "Select a Salesperson…" : "No active Salespeople to assign to"}
            </option>
            {people.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Note</span>
          <textarea value={note} maxLength={300} rows={3} onChange={(e) => setNote(e.target.value)} />
        </label>
        {!people.length && (
          <p className="field-hint" role="note">
            {user?.role === "Admin"
              ? "There are no active Salespeople."
              : "No active Salespeople report to you. Set Reports To in Manage Access > People, or ask the Admin to assign this lead."}
          </p>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}

// Assign for the leads ticked in the Leads list (the Admin, or a Manager with Reassign owner): the ticked pooled leads
// go to one Salesperson, each through the single Assign's rules on the server (still in the pool when its turn comes,
// locked, Transfer History, pending requests closed). Owned leads ticked beside them are listed as left out, never
// reassigned. Afterwards it says what happened to each lead: assigned, assigned meanwhile by someone else (kept),
// skipped (why) or failed. Salespeople don't get this: they request pooled leads.
const leadsText = (n) => `${n.toLocaleString("en-US")} lead${n === 1 ? "" : "s"}`;
function LeadNames({ rows, more = 8 }) {
  return (
    <ul className="request-results">
      {rows.slice(0, more).map((r) => (
        <li key={r.id}>
          <b>{r.name}</b>
          {r.note && <span className="muted"> ({r.note})</span>}
          {r.reason && `: ${r.reason}`}
        </li>
      ))}
      {rows.length > more && <li>and {(rows.length - more).toLocaleString("en-US")} more</li>}
    </ul>
  );
}
export function BulkAssignDialog({ pooled, owned = [], user, users, onClose }) {
  const people = poolAssignees(user, users);
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const sending = useRef(false);
  const submit = async (e) => {
    e.preventDefault();
    if (sending.current) return; // a second click or Enter while it runs sends nothing
    sending.current = true;
    setBusy(true);
    setError("");
    try {
      setResult(await api.bulkAssignLeads(pooled.map((l) => l.id), Number(to), note.trim()));
    } catch (err) {
      setError(err.message);
    }
    sending.current = false;
    setBusy(false);
  };
  if (result) {
    const { assigned, to: name, conflicts, skipped, failed } = result;
    return (
      <Dialog
        title="Assign Leads"
        onClose={() => onClose(true)}
        footer={
          <button className="sf-button brand" onClick={() => onClose(true)} autoFocus>
            Done
          </button>
        }
      >
        <div className="transfer-form" role="status">
          <p>
            <b>{assigned ? `${leadsText(assigned)} assigned to ${name}.` : "No leads were assigned."}</b>
          </p>
          {conflicts.length > 0 && (
            <>
              <p className="muted">{leadsText(conflicts.length)} not assigned: someone else assigned {conflicts.length === 1 ? "it" : "them"} meanwhile (the new owner was kept):</p>
              <LeadNames rows={conflicts} />
            </>
          )}
          {skipped.length > 0 && (
            <>
              <p className="muted">{leadsText(skipped.length)} skipped:</p>
              <LeadNames rows={skipped} />
            </>
          )}
          {failed.length > 0 && (
            <>
              <p className="muted">{leadsText(failed.length)} failed (nothing was saved for {failed.length === 1 ? "it" : "them"}):</p>
              <LeadNames rows={failed} />
            </>
          )}
        </div>
      </Dialog>
    );
  }
  return (
    <Dialog
      title={`Assign ${leadsText(pooled.length)}`}
      onClose={() => onClose(false)}
      busy={busy}
      footer={
        <>
          <button className="sf-button" onClick={() => onClose(false)} disabled={busy}>
            Cancel
          </button>
          <button className="sf-button brand" form="bulk-assign" disabled={busy || !to} aria-busy={busy}>
            {busy ? "Assigning…" : `Assign ${leadsText(pooled.length)}`}
          </button>
        </>
      }
    >
      <form id="bulk-assign" className="transfer-form" onSubmit={submit}>
        <p className="muted">
          The {leadsText(pooled.length)} from the Unassigned Pool you selected {pooled.length === 1 ? "goes" : "go"} to one Salesperson. Only
          {pooled.length === 1 ? " its" : " their"} owner changes: stage, Created By and Created Date stay; pending requests for
          {pooled.length === 1 ? " it" : " them"} are closed.
          {user?.role === "Admin" ? "" : " You can assign them to the Salespeople who report to you."}
        </p>
        <p className="field-hint">Will be assigned ({pooled.length}):</p>
        <LeadNames rows={pooled} />
        {owned.length > 0 && (
          <>
            <p className="field-hint" role="note">
              Left out ({owned.length}): {owned.length === 1 ? "it already has" : "they already have"} an owner, so {owned.length === 1 ? "it isn't" : "they aren't"} reassigned (use Transfer Leads for that):
            </p>
            <LeadNames rows={owned} />
          </>
        )}
        <label className="field">
          <span>
            <abbr title="required">*</abbr> Assign to
          </span>
          <select value={to} required onChange={(e) => setTo(e.target.value)} autoFocus>
            <option value="" disabled>
              {people.length ? "Select a Salesperson…" : "No active Salespeople to assign to"}
            </option>
            {people.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Note</span>
          <textarea value={note} maxLength={300} rows={3} onChange={(e) => setNote(e.target.value)} />
        </label>
        {!people.length && (
          <p className="field-hint" role="note">
            {user?.role === "Admin"
              ? "There are no active Salespeople."
              : "No active Salespeople report to you. Set Reports To in Manage Access > People, or ask the Admin to assign these leads."}
          </p>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}

// The lead page: its requests in a short list (the lead's owner, their Manager and the Admin see all of them)
export function TransferRequestList({ rows, onChange }) {
  const [deciding, setDeciding] = useState(null);
  const [error, setError] = useState("");
  const cancel = async (r) => {
    setError("");
    try {
      onChange(await api.cancelTransferRequest(r.id));
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <>
      {error && (
        <p className="form-error pad" role="alert">
          {error}
        </p>
      )}
      <ul className="history-list">
        {rows.map((r) => (
          <li key={r.id}>
            <b>
              {r.requested_by_name} asked for this lead <span className={`pill ${STATUS_PILL[r.status] || ""}`}>{r.status}</span>
            </b>
            <p className="history-note">{r.reason}</p>
            <small>
              {dateTime(r.created_at)}
              {r.decided_at && ` • ${r.status} by ${r.decided_by_name}, ${dateTime(r.decided_at)}`}
              {r.decision_note && ` • ${r.decision_note}`}
            </small>
            {(r.can_decide || r.can_cancel) && (
              <div className="transfer-request-actions">
                {r.can_decide && (
                  <>
                    <button className="sf-button brand small" onClick={() => setDeciding({ request: r, decision: "approve" })}>
                      Approve
                    </button>
                    <button className="sf-button small" onClick={() => setDeciding({ request: r, decision: "reject" })}>
                      Reject
                    </button>
                  </>
                )}
                {r.can_cancel && (
                  <button className="sf-button small" onClick={() => cancel(r)}>
                    Cancel Request
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
      {deciding && (
        <DecideDialog
          {...deciding}
          onClose={() => setDeciding(null)}
          onDone={(saved, stale) => {
            setDeciding(null);
            setError(stale || "");
            onChange(saved);
          }}
        />
      )}
    </>
  );
}

// Approve Selected / Reject Selected: says how many and which, takes one note (required to reject, as for one
// request), then shows what happened to each: decided, changed by someone else meanwhile, or not possible. The server
// checks every request again on its own; nothing is sent twice (the button is off while it runs).
function BulkDecisionDialog({ decision, rows, onClose }) {
  const approve = decision === "approve";
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const sending = useRef(false);
  const count = rows.length;
  const pool = rows.filter((r) => r.pool).length;
  const submit = async (e) => {
    e.preventDefault();
    if (sending.current) return; // a second click or Enter while it runs sends nothing
    sending.current = true;
    setBusy(true);
    setError("");
    try {
      setResult(await api.decideTransferRequests(decision, rows.map((r) => r.id), note.trim()));
    } catch (err) {
      setError(err.message);
    }
    sending.current = false;
    setBusy(false);
  };
  if (result) {
    const notDone = [...result.conflicts.map((r) => ({ ...r, conflict: true })), ...result.skipped];
    return (
      <Dialog
        title={approve ? "Approve Selected" : "Reject Selected"}
        onClose={() => onClose(true)}
        footer={
          <button className="sf-button brand" onClick={() => onClose(true)} autoFocus>
            Done
          </button>
        }
      >
        <div className="transfer-form" role="status">
          <p>
            <b>{decisionSummary(result)}</b>
          </p>
          {notDone.length > 0 && (
            <ul className="request-results">
              {notDone.slice(0, 20).map((r) => (
                <li key={r.id}>
                  <b>{r.lead_name}</b>
                  {r.requested_by_name && ` (asked by ${r.requested_by_name})`}: {r.reason}
                </li>
              ))}
              {notDone.length > 20 && <li>and {(notDone.length - 20).toLocaleString("en-US")} more</li>}
            </ul>
          )}
        </div>
      </Dialog>
    );
  }
  return (
    <Dialog
      title={`${approve ? "Approve" : "Reject"} ${requestCount(count)}`}
      onClose={() => onClose(false)}
      busy={busy}
      footer={
        <>
          <button className="sf-button" onClick={() => onClose(false)} disabled={busy}>
            Cancel
          </button>
          <button className={`sf-button ${approve ? "brand" : "danger"}`} form="bulk-decision" disabled={busy || (!approve && !note.trim())} aria-busy={busy}>
            {busy ? "Saving…" : `${approve ? "Approve" : "Reject"} ${requestCount(count)}`}
          </button>
        </>
      }
    >
      <form id="bulk-decision" className="transfer-form" onSubmit={submit}>
        <p className="muted">
          {approve
            ? `Each lead goes to the person who asked for it${pool ? " (leads from the Unassigned Pool are assigned to them)" : ", with its open follow-ups"}. `
            : "The leads stay where they are; each person who asked is told why. "}
          Only the {requestCount(count)} you selected on this page {count === 1 ? "is" : "are"} decided, each on its own: one that someone
          else has decided or changed meanwhile is left as it is and listed.
        </p>
        <ul className="request-results">
          {rows.slice(0, 10).map((r) => (
            <li key={r.id}>
              <b>{r.lead_name}</b> for {r.requested_by_name}
              {r.reason && <span className="muted"> “{r.reason}”</span>}
            </li>
          ))}
          {count > 10 && <li>and {(count - 10).toLocaleString("en-US")} more</li>}
        </ul>
        <label className="field">
          <span>
            {!approve && <abbr title="required">*</abbr>} {approve ? "Note for all (optional)" : `Reason for all ${requestCount(count)}`}
          </span>
          <textarea value={note} maxLength={300} rows={3} required={!approve} autoFocus onChange={(e) => setNote(e.target.value)} />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}

const TABS = [
  ["to_approve", "To Approve"],
  ["mine", "My Requests"],
  ["all", "All"],
];

// From a notification: ?request=<id> opens All (it shows the request whether it is still pending or someone has
// decided it already) with that request highlighted, on the page that holds it; ?box=to_approve opens To Approve.
const queryValue = (query, key) => new URLSearchParams(query || "").get(key);

export default function TransferRequestsPage({ user, reload, query = "" }) {
  const focus = queryValue(query, "request");
  const askedBox = queryValue(query, "box");
  // what is shown: the tab, the Requested By filter (To Approve), the page; focus only for the first load
  const [view, setView] = useState({
    box: focus ? "all" : TABS.some(([key]) => key === askedBox) ? askedBox : user.role === "Admin" ? "to_approve" : "mine",
    requestedBy: "",
    offset: 0,
    size: REQUEST_PAGE_SIZE,
    focus: focus || "",
  });
  const [page, setPage] = useState(null); // { items, total, box_total, offset, requesters }
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(() => new Set()); // ticked request ids, on the page shown only
  const [bulk, setBulk] = useState(null); // "approve" | "reject": the confirmation dialog
  const [version, setVersion] = useState(0); // a decision was made: load the page again
  useEffect(() => {
    let live = true;
    setError("");
    api
      .transferRequestsPage({ box: view.box, requestedBy: view.requestedBy, offset: view.offset, limit: view.size, focus: view.focus })
      .then((res) => {
        if (!live) return;
        setPage(res);
        setSelected((ticked) => keepSelection(ticked, res.items)); // decided or gone since: unticked
      })
      .catch((err) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, [view, version]);
  // a new tab, filter or page starts with nothing ticked: no request that isn't shown can be decided by accident
  const show = (change) => {
    setSelected(new Set());
    setView((v) => ({ ...v, focus: "", ...change }));
  };
  const changed = () => {
    setVersion((n) => n + 1);
    reload?.();
  };
  const bulkOn = canBulkDecide(user, view.box);
  const items = page?.box === view.box ? page.items : null; // a tab's rows only once they are loaded
  const requesters = page?.requesters || [];
  const filterName = requesters.find((p) => String(p.id) === String(view.requestedBy))?.name || "";
  const empty = view.requestedBy
    ? "No requests from this person here."
    : { to_approve: "Nothing is waiting for your approval.", mine: "You haven't asked for any leads.", all: "No transfer requests yet." }[view.box];
  const offset = page?.offset ?? view.offset;
  return (
    <div className="page">
      <section className="card transfer-requests-page">
        <header className="card-header">
          <h2>Lead Transfer Requests</h2>
          <div className="card-actions">
            <a className="sf-button" href="#/leads">
              Back to Leads
            </a>
          </div>
        </header>
        <div className="tabs" role="tablist">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={view.box === key}
              className={view.box === key ? "on" : ""}
              onClick={() => view.box !== key && show({ box: key, requestedBy: "", offset: 0 })}
            >
              {label}
            </button>
          ))}
        </div>
        {view.box === "to_approve" && (
          <div className="request-filters">
            <label className="field request-filter">
              <span>Requested By</span>
              <select value={view.requestedBy} onChange={(e) => show({ requestedBy: e.target.value, offset: 0 })}>
                <option value="">Everyone{page?.box === "to_approve" ? ` (${page.box_total.toLocaleString("en-US")})` : ""}</option>
                {requesters.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.count.toLocaleString("en-US")})
                  </option>
                ))}
                {view.requestedBy && !filterName && <option value={view.requestedBy}>(no requests now)</option>}
              </select>
            </label>
            {view.requestedBy && (
              <button type="button" className="link" onClick={() => show({ requestedBy: "", offset: 0 })}>
                Clear filter
              </button>
            )}
            {/* the filtered count beside the filter (the page bar below always says the range) */}
            {items && view.requestedBy && (
              <span className="request-range" aria-live="polite">
                {requestRange({ offset, count: items.length, total: page.total, requester: filterName })}
              </span>
            )}
          </div>
        )}
        {bulkOn && selected.size > 0 ? (
          <div className="selection-bar" role="region" aria-label="Selected requests">
            <p className="selection-summary">
              <b aria-live="polite">{requestCount(selected.size)} selected</b>
              <span>on this page</span>
            </p>
            <button type="button" className="link selection-clear" onClick={() => setSelected(new Set())}>
              Clear selection
            </button>
            <div className="selection-actions">
              <button type="button" className="sf-button brand" onClick={() => setBulk("approve")}>
                Approve Selected
              </button>
              <button type="button" className="sf-button" onClick={() => setBulk("reject")}>
                Reject Selected
              </button>
            </div>
          </div>
        ) : (
          bulkOn &&
          items?.length > 0 && (
            <p className="field-hint request-select-hint">
              Tick requests to approve or reject them together. The box in the header ticks the requests on this page only,
              never the whole list; changing the filter or the page clears the ticks.
            </p>
          )
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        {!items && !error && <p className="table-empty">Loading…</p>}
        {items && items.length > 0 && (
          <TransferRequestTable
            rows={items}
            focus={focus}
            onChange={changed}
            selectable={bulkOn}
            selected={selected}
            onToggle={(id) => setSelected((ticked) => toggleOne(ticked, id))}
            onToggleAll={() => setSelected((ticked) => toggleAllOnPage(ticked, items))}
          />
        )}
        {items && !items.length && <p className="table-empty">{empty}</p>}
        {items && page.total > 0 && (
          <Pagination
            page={Math.floor(offset / view.size) + 1}
            pages={Math.max(1, Math.ceil(page.total / view.size))}
            size={view.size}
            total={page.total}
            start={offset}
            noun="request"
            label="Request pages"
            setPage={(p) => show({ offset: (p - 1) * view.size })}
            setSize={(size) => show({ size, offset: 0 })}
          />
        )}
      </section>
      {bulk && (
        <BulkDecisionDialog
          decision={bulk}
          rows={items.filter((r) => selected.has(r.id))}
          onClose={(decided) => {
            setBulk(null);
            if (decided) {
              setSelected(new Set());
              changed();
            }
          }}
        />
      )}
    </div>
  );
}
