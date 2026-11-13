// Lead transfer requests: a user asks for someone else's lead; the lead's owner, the owner's Manager or the Admin
// approves (the lead moves to the requester) or rejects it (with a reason). Nothing moves without an approval.
// - RequestTransferDialog: "Request Transfer" on a lead page, or from the "email already in the CRM" message
// - TransferRequestsPage (#/transfer-requests): To Approve, My Requests and All
import React, { useEffect, useState } from "react";
import { api } from "./api";
import { dateTime } from "./format";
import { Dialog } from "./LeadFiles";

const STATUS_PILL = { Pending: "pill-warn", Approved: "pill-ok", Rejected: "pill-lost", Cancelled: "pill-past" };

export function RequestTransferDialog({ lead, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onDone(await api.requestLeadTransfer(lead.id, reason.trim()));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={`Request Transfer: ${lead.name}`}
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
          {lead.owner_name ? `${lead.owner_name} owns this lead. ` : ""}The owner, their Manager or the Admin must approve before
          the lead is transferred to you.
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
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={`${approve ? "Approve" : "Reject"} Transfer: ${request.lead_name}`}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button className="sf-button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className={`sf-button ${approve ? "brand" : "danger"}`} form="transfer-decision" disabled={busy || (!approve && !note.trim())}>
            {busy ? "Saving…" : approve ? "Approve & Transfer" : "Reject"}
          </button>
        </>
      }
    >
      <form id="transfer-decision" className="transfer-form" onSubmit={submit}>
        <p className="muted">
          {request.requested_by_name} asked for this lead: “{request.reason}”.{" "}
          {approve ? `The lead moves from ${request.owner_name} to ${request.requested_by_name} now, with its open follow-ups.` : "The lead stays where it is."}
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
export function TransferRequestTable({ rows, onChange, showLead = true }) {
  const [deciding, setDeciding] = useState(null); // { request, decision }
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
              <tr key={r.id}>
                {showLead && (
                  <td>
                    {r.can_open_lead ? <a href={`#/leads/${r.lead_id}`}>{r.lead_name}</a> : r.lead_name}
                    {r.company && <small className="muted block">{r.company}</small>}
                  </td>
                )}
                <td>{r.owner_name}</td>
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
          onDone={(saved) => {
            setDeciding(null);
            onChange(saved);
          }}
        />
      )}
    </>
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
          onDone={(saved) => {
            setDeciding(null);
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

export default function TransferRequestsPage({ user, reload }) {
  const [box, setBox] = useState(user.role === "Admin" ? "to_approve" : "mine");
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
