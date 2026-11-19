// Lead transfer requests: a user asks for someone else's lead; the lead's owner, the owner's Manager or the Admin
// approves (the lead moves to the requester) or rejects it (with a reason). Nothing moves without an approval.
// - RequestTransferDialog: "Request Transfer" on a lead page, or from the "email already in the CRM" message; for a
//   lead in the Unassigned Pool it is "Request Assignment" (a Salesperson; the Admin or their Manager approves)
// - AssignLeadDialog: "Assign" on a pooled lead's page (the Admin, or a Manager to their own Salespeople)
// - TransferRequestsPage (#/transfer-requests): To Approve, My Requests and All
import React, { useEffect, useState } from "react";
import { api } from "./api";
import { dateTime } from "./format";
import { Dialog } from "./LeadFiles";
import { poolAssignees } from "./permissions";

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

// The requests as a table, with Approve / Reject / Cancel on the ones you can act on
export function TransferRequestTable({ rows, onChange, showLead = true, focus = null }) {
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
              <tr key={r.id} id={`transfer-request-${r.id}`} className={String(r.id) === String(focus) ? "row-focus" : undefined}>
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
export function BulkRequestDialog({ leadIds, onClose }) {
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

const TABS = [
  ["to_approve", "To Approve"],
  ["mine", "My Requests"],
  ["all", "All"],
];

// From a notification: ?request=<id> opens All (it shows the request whether it is still pending or someone has
// decided it already) with that request highlighted; ?box=to_approve opens To Approve.
const queryValue = (query, key) => new URLSearchParams(query || "").get(key);

export default function TransferRequestsPage({ user, reload, query = "" }) {
  const focus = queryValue(query, "request");
  const askedBox = queryValue(query, "box");
  const [box, setBox] = useState(
    focus ? "all" : TABS.some(([key]) => key === askedBox) ? askedBox : user.role === "Admin" ? "to_approve" : "mine",
  );
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const load = () =>
    api
      .transferRequests(box)
      .then(setRows)
      .catch((err) => setError(err.message));
  useEffect(() => {
    setRows(null);
    setError("");
    load();
  }, [box]); // eslint-disable-line react-hooks/exhaustive-deps
  const empty = { to_approve: "Nothing is waiting for your approval.", mine: "You haven't asked for any leads.", all: "No transfer requests yet." }[box];
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
            <button key={key} role="tab" aria-selected={box === key} className={box === key ? "on" : ""} onClick={() => setBox(key)}>
              {label}
            </button>
          ))}
        </div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        {rows === null && !error && <p className="table-empty">Loading…</p>}
        {rows && rows.length > 0 && (
          <TransferRequestTable
            rows={rows}
            focus={focus}
            onChange={() => {
              load();
              reload?.();
            }}
          />
        )}
        {rows && !rows.length && <p className="table-empty">{empty}</p>}
      </section>
    </div>
  );
}
