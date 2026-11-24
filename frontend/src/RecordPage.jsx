import React, { useEffect, useState } from "react";
import { AddToCalendar } from "./calendar";
import { demoEvent } from "./calendarLinks";
import { formatBusiness } from "./businessTime";
import OpportunityAttachments, { PICK_ATTACHMENTS } from "./Attachments";
import { EmailList, useEmails } from "./Email";
import { canAssignPool, canCreateSales, canEditRecord, canRequestPool, canTransferLead } from "./permissions";
import { amount, dateTime, shortDate } from "./format";
import { regionName } from "./phone";
import { ActionMenu, Card, Icon, ObjectIcon, PathBar, PhoneReveal, StageBadge } from "./ui";
import { AssignLeadDialog, RequestTransferDialog, TransferRequestList } from "./TransferRequests";
import { api } from "./api";
import { stageClockSummary } from "./listHelpers";

import { ATTACHMENT_UPLOAD_STAGES, isPooledLead, LEAD_FLOW, LEAD_OPTIONAL_STAGES, OPPORTUNITY_FLOW } from "./domain";

// Unqualified comes first, as in the requirement: new leads start at New, and Unqualified is chosen (with a reason)
// for a lead that isn't eligible
const LEAD_PATH = ["Unqualified", ...LEAD_FLOW, "Converted"];
const OPP_PATH = [...OPPORTUNITY_FLOW, "Won"];

// A research link (LinkedIn, website) that opens in a new tab
export function ExternalLink({ href, children }) {
  if (!href) return null;
  const url = /^https?:\/\//i.test(href) ? href : `https://${href}`;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="external-link">
      {children || url.replace(/^https?:\/\/(www\.)?/i, "").replace(/\/$/, "")}
      <span aria-hidden="true"> ↗</span>
    </a>
  );
}

const headcount = (n) => (n == null ? "" : Number(n).toLocaleString());

// A lead or opportunity opened from a link (an assignment email's "Open in SalesTrack", a bookmark) that the server
// answered but didn't return. "denied": this account can't open it. The server answers the same whether the record
// doesn't exist or belongs to someone else (now: it may have been reassigned after the email was sent), so the page
// doesn't tell those apart. It names the signed-in account and offers to sign in with another one: after signing in,
// SalesTrack comes back to this same link (nothing in the link signs anyone in). Any other error says what the server
// said, with Try again. A server that didn't answer is not this page: that is "Can't reach the server" (App.jsx).
export function RecordUnavailable({ collection, problem, user, onSwitchAccount, onRetry }) {
  const noun = collection === "opportunities" ? "opportunity" : "lead";
  const list = collection === "opportunities" ? "Opportunities" : "Leads";
  const denied = problem.kind === "denied";
  return (
    <div className="page">
      <Card title={denied ? `You can't open this ${noun} with this account` : `This ${noun} couldn't be loaded`}>
        <div className="pad record-unavailable" role="alert">
          {denied ? (
            <>
              <p>
                You&apos;re signed in as <b>{user.full_name}</b> ({user.email}). This {noun} doesn&apos;t exist, or this
                account doesn&apos;t have access to it.
              </p>
              <p className="muted">
                If the link was sent to a different account, sign in with that account. If the {noun} was reassigned
                after the email was sent, ask its new owner or your Manager.
              </p>
            </>
          ) : (
            <p>
              The server answered: {problem.message} {problem.status ? `(${problem.status})` : ""}
            </p>
          )}
          <div className="record-unavailable-actions">
            {denied ? (
              <button type="button" className="sf-button brand" onClick={onSwitchAccount}>
                Sign in with a different account
              </button>
            ) : (
              <button type="button" className="sf-button brand" onClick={onRetry}>
                Try again
              </button>
            )}
            <a className="sf-button" href={`#/${collection}`}>
              Go to {list}
            </a>
          </div>
        </div>
      </Card>
    </div>
  );
}

function Field({ label, children, onEdit }) {
  return (
    <div className="field-row">
      <span className="field-label">{label}</span>
      <span className="field-value">
        {children === "" || children == null ? <>&nbsp;</> : children}
        {onEdit && (
          <button className="inline-edit" onClick={onEdit} aria-label={`Edit ${label}`}>
            <Icon name="edit" size={12} />
          </button>
        )}
      </span>
    </div>
  );
}

function Section({ title, children }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="detail-section">
      <button className="section-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon name="down" size={12} className={open ? "" : "rot"} /> {title}
      </button>
      {open && <div className="field-grid">{children}</div>}
    </div>
  );
}

export function TaskLine({ task, toggleTask, setModal }) {
  return (
    <li className={`task-line ${task.completed ? "done" : ""}`}>
      <ObjectIcon type="task" size={24} />
      <input
        type="checkbox"
        checked={task.completed}
        disabled={task.completed}
        onChange={() => toggleTask(task.id)}
        aria-label={`Complete ${task.title}`}
      />
      <div>
        <button className="link" onClick={() => setModal({ type: "task", record: task })}>
          {task.title}
        </button>
        <small>
          {task.owner}
          {task.is_auto ? " • Automatic" : ""}
          {task.completed ? ` • ${task.status}` : ""}
          {task.priority === "High" ? " • High priority" : ""}
        </small>
      </div>
      <span
        className={`due ${!task.completed && task.isOverdue ? "overdue" : ""}`}
        title={task.completed ? `Completed ${shortDate(task.completed_at)} • Due ${shortDate(task.due_date)}` : "Due date"}
      >
        {task.completed ? shortDate(task.completed_at || task.due_date) : shortDate(task.due_date)}
      </span>
    </li>
  );
}

function ActivityTab({ item, tasks, toggleTask, setModal, openTask, collection, emails, sendEmail, addFiles, canAddTask = true, canEmail = true }) {
  const open = tasks.filter((t) => !t.completed).sort((a, b) => a.due_date.localeCompare(b.due_date));
  const done = tasks.filter((t) => t.completed);
  const past = [
    ...done.map((t) => ({ key: `t${t.id}`, date: t.completed_at || t.due_date, task: t })),
    ...item.activity.map((a, i) => ({ key: `h${i}`, date: a.date, history: a })),
  ].sort((a, b) => String(b.date).localeCompare(String(a.date)));
  return (
    <div className="activity-tab">
      <div className="activity-actions">
        {/* a lead in the Unassigned Pool gets its follow-ups once it is assigned (there is nobody to do them yet) */}
        {canAddTask && (
          <button className="sf-button" onClick={() => openTask(item.id, collection)}>
            <ObjectIcon type="task" size={18} /> New Task
          </button>
        )}
        {canEmail && (
          <button className="sf-button" onClick={sendEmail}>
            <ObjectIcon type="event" size={18} /> Email
          </button>
        )}
        {canEmail && (
          <button className="sf-button" onClick={() => setModal({ type: "note", collection, record: item })}>
            <ObjectIcon type="note" size={18} /> New Note
          </button>
        )}
        {/* opportunities: the proposal, pricing or signed order go to the Attachments card (open or Won deals) */}
        {addFiles && (
          <button className="sf-button" onClick={addFiles} title="Add files to this opportunity's Attachments">
            <ObjectIcon type="note" size={18} /> Add Files
          </button>
        )}
      </div>
      <h3 className="activity-heading">Upcoming &amp; Overdue</h3>
      {open.length ? (
        <ul className="task-lines">
          {open.map((t) => (
            <TaskLine key={t.id} task={t} toggleTask={toggleTask} setModal={setModal} />
          ))}
        </ul>
      ) : (
        <p className="muted pad">No next steps. To get things moving, add a task.</p>
      )}
      <h3 className="activity-heading">Emails ({emails.length})</h3>
      <EmailList emails={emails} empty="No emails yet. Use Email to send one with attachments." />
      <h3 className="activity-heading">Past Activity</h3>
      {past.length ? (
        <ul className="task-lines">
          {past.map((p) =>
            p.task ? (
              <TaskLine key={p.key} task={p.task} toggleTask={toggleTask} setModal={setModal} />
            ) : (
              <li key={p.key} className="task-line history">
                <ObjectIcon type="event" size={24} />
                <div>
                  <span>{p.history.text}</span>
                  <small>{p.history.by}</small>
                </div>
                <span className="due">{shortDate(p.history.date)}</span>
              </li>
            ),
          )}
        </ul>
      ) : (
        <p className="muted pad">No past activity.</p>
      )}
    </div>
  );
}

// In stage under the status path: "In New for 13 days" with its rating, or a plain badge and a line saying why a
// lead isn't timed (Not started, Not recorded) or that closed leads aren't
function StageClockLine({ clock, since }) {
  if (clock.state === "closed") return <p className="stage-clock muted">{clock.text}</p>;
  return (
    <p className="stage-clock" title={since ? `Since ${dateTime(since)}` : undefined}>
      {clock.state === "timed" && <span className="stage-clock-text">{clock.text}</span>}
      {clock.badge && <span className={`stage-badge in-stage ${clock.tone}`}>{clock.badge}</span>}
      {clock.state !== "timed" && <span className="stage-clock-text muted">{clock.text}</span>}
    </p>
  );
}

export default function RecordPage({ collection, item, data, user, openLead, openTask, toggleTask, convert, setModal, openEmail, emailVersion, reload }) {
  const lead = collection === "leads";
  const [tab, setTab] = useState("activity");
  // (a pooled lead shown without its contact details has no emails to show this user: none are asked for)
  const { emails } = useEmails(lead ? "lead_id" : "opportunity_id", lead && item?.contact_hidden ? null : item?.id, emailVersion);
  // lead transfer requests: asking for someone else's lead, and approving requests for this one
  const [requests, setRequests] = useState([]);
  const [asking, setAsking] = useState(false);
  const [assigning, setAssigning] = useState(false); // the Unassigned Pool: Assign (Admin / authorised Manager)
  const loadRequests = () => {
    if (lead && item?.id) api.leadTransferRequests(item.id).then(setRequests).catch(() => setRequests([]));
  };
  useEffect(loadRequests, [lead, item?.id, item?.owner_id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!item)
    return (
      <div className="page">
        <Card title="Record not found">
          <p className="pad">
            This record doesn't exist, or you don't have access to it. <a href={`#/${collection}`}>Back to list</a>
          </p>
        </Card>
      </div>
    );

  const closed = ["Won", "Lost", "Converted", "Unqualified"].includes(item.stage);
  // the Unassigned Pool: no owner yet. It keeps its stage until it is assigned (no stage change, conversion, closing,
  // follow-ups or transfer); a user who can only request it sees it without the person's contact details
  const pooled = lead && isPooledLead(item);
  const summaryOnly = pooled && !!item.contact_hidden;
  // Salespeople change only their own records; Managers and Admins can change any (the backend checks it too)
  const canEdit = canEditRecord(user, item);
  const canWork = canEdit && !pooled; // stage, conversion, closing, demo: only once the lead has an owner
  const canConvert = canEdit && canCreateSales(user) && !pooled; // the Admin, Managers and Salespeople convert leads they may edit
  const canTransfer = lead && canTransferLead(user, item); // Admin: any lead; owner with "Transfer leads": their own
  const transfers = (lead && item.transfers) || [];
  const askedAlready = requests.some((r) => r.status === "Pending" && r.requested_by_id === user.id);
  // anyone but the Admin (who transfers directly) can ask for an open lead they don't own; approval is required
  const canRequest =
    lead && !pooled && !closed && user.role !== "Admin" && item.owner_id !== user.id &&
    !askedAlready;
  // a pooled lead: the Admin or a Manager with "Reassign owner" assigns it; a Salesperson requests it (approval needed)
  const canAssign = pooled && !closed && canAssignPool(user);
  const canAskForPool = pooled && !closed && canRequestPool(user) && !askedAlready;
  const tasks = data.tasks.filter((t) => t.relatedId === item.id && t.relatedType === collection);
  // New Task: anyone who can open the record, except on a pooled lead (nobody to do it yet; the backend says the same)
  const canAddTask = !pooled;
  // In stage (leads): the Leads list's clock from the server (item.in_stage), the same start, time and rating
  const stageClock = lead ? stageClockSummary(item.in_stage, item.stage, pooled) : null;
  const edit = () => (lead ? openLead(item) : setModal({ type: "opportunity", record: item }));
  // the pencils on the Details tab follow the same rule as Actions > Edit (none for a view-only user)
  const editField = canEdit ? edit : undefined;
  const convertedTo = lead && data.opportunities.find((o) => o.leadId === item.id);
  const sourceLead = !lead && item.leadId && data.leads.find((l) => l.id === item.leadId);
  const contact = !lead && data.contacts.find((c) => c.id === item.primary_contact_id);
  // Any stage, Lost included: the composer only drafts and opens Outlook (no stage, owner or task changes). To is the
  // lead's email or the opportunity's primary contact's; noEmail says why it is empty.
  const sendEmail = () =>
    openEmail(
      lead
        ? { type: "lead", field: "lead_id", id: item.id, name: item.name, email: item.email, firstName: item.first_name, stage: item.stage,
            noEmail: "This lead has no email address." }
        : { type: "opportunity", field: "opportunity_id", id: item.id, name: item.name, email: contact?.email, firstName: contact?.first_name, stage: item.stage,
            noEmail: contact
              ? `The primary contact, ${contact.full_name || contact.last_name}, has no email address.`
              : item.primary_contact_id
                ? "The primary contact's email isn't available to you."
                : "This opportunity has no primary contact." },
    );

  const path = lead ? LEAD_PATH : OPP_PATH;
  // a closed lead shows how it ended in the last step (Lost / Unqualified) instead of Converted
  const pathStages = item.stage === "Lost" ? [...path.slice(0, -1), "Lost"] : path;
  // an optional stage (Revisit) the lead went past without entering is shown as skipped, not as done
  const reached = (stage) => item.activity.some((a) => a.text?.includes(`→ ${stage}`) || a.text?.startsWith(`Created at ${stage}`));
  const skippedStages = lead ? LEAD_OPTIONAL_STAGES.filter((stage) => !reached(stage)) : [];
  // a lead closed as Lost / Unqualified: only the stages it really reached are ticked
  const notReached = lead && ["Lost", "Unqualified"].includes(item.stage)
    ? LEAD_PATH.filter((stage) => stage !== "Converted" && stage !== item.stage && !reached(stage))
    : [];
  // the Unqualified step: red when the lead is Unqualified, otherwise never ticked (it's an outcome, not a step done)
  const stepState = (stage) => {
    if (!lead) return undefined;
    if (stage === "Unqualified") return item.stage === "Unqualified" ? "lost" : "incomplete";
    if (item.stage === "Unqualified") return reached(stage) && stage !== "Converted" ? "complete" : "incomplete";
    return undefined;
  };
  // "Mark as Complete" goes to the next required stage: an optional one (Revisit) is chosen on the path itself
  const nextStage = path.slice(path.indexOf(item.stage) + 1).find((stage) => !LEAD_OPTIONAL_STAGES.includes(stage));
  const selectStage = (stage) => {
    if (stage === "Unqualified") return setModal({ type: "unqualified", record: item });
    if (stage === "Converted") return canConvert ? convert(item.id) : undefined;
    if (stage === "Won") return setModal({ type: "won", record: item });
    if (stage !== item.stage) setModal({ type: "stage", collection, record: item, stage });
  };

  const highlights = lead
    ? [
        ["Title", item.title],
        ["Company", item.company],
        item.stage === "Revisit" && item.revisit_date && [
          "Revisit On",
          <span key="rv" className="revisit-on">
            {new Date(item.revisit_date).toLocaleDateString()} <small>{item.revisit_reason}</small>
          </span>,
        ],
        ["Phone", item.phone && <PhoneReveal key="ph" value={item.phone} />],
        ["Email", item.email && (
          <span key="em" className="email-with-status">
            <a href={`mailto:${item.email}`}>{item.email}</a>
            {item.email_invalid_at && (
              <span className="email-flag bad" title={item.email_invalid_reason || "Marked invalid"}>
                Invalid email
              </span>
            )}
            {item.unsubscribed_at && (
              <span className="email-flag off" title={`Unsubscribed on ${new Date(item.unsubscribed_at).toLocaleDateString()}`}>
                Unsubscribed
              </span>
            )}
          </span>
        )],
        ["LinkedIn", <ExternalLink key="li" href={item.linkedin_url}>Profile</ExternalLink>],
        ["Company Links", (item.company_website || item.company_linkedin_url) && (
          <span key="co" className="link-pair">
            <ExternalLink href={item.company_website}>Website</ExternalLink>
            <ExternalLink href={item.company_linkedin_url}>LinkedIn</ExternalLink>
          </span>
        )],
      ]
    : [
        ["Account Name", item.account_id && <a href={`#/accounts/${item.account_id}`}>{item.account_name}</a>],
        ["Close Date", shortDate(item.expected_close_date)],
        ["Amount", amount(item.value, item.currency)],
        ["Opportunity Owner", item.owner],
      ];

  return (
    <div className="page record-page">
      <section className="card highlights">
        <div className="highlights-top">
          <ObjectIcon type={collection} size={36} />
          <div className="highlights-name">
            <small>{lead ? "Lead" : "Opportunity"}</small>
            <h1>
              {lead && item.salutation ? `${item.salutation} ` : ""}
              {item.name}
            </h1>
          </div>
          <div className="button-group">
            {canAssign && (
              <button className="sf-button brand" onClick={() => setAssigning(true)}>
                Assign
              </button>
            )}
            {canAskForPool && (
              <button className="sf-button brand" onClick={() => setAsking(true)}>
                Request Assignment
              </button>
            )}
            {!summaryOnly && (
              <button className="sf-button" onClick={sendEmail}>
                Send Email
              </button>
            )}
            {/* New Task is in the Activity tab (the same form, already linked to this record) */}
            {canConvert && lead && !closed && (
              <button className="sf-button" onClick={() => convert(item.id)}>
                Convert
              </button>
            )}
            {canWork && !closed && (
              <button className="sf-button" onClick={() => setModal({ type: "lost", collection, record: item })}>
                Mark as Lost
              </button>
            )}
            {/* Edit, Transfer, Reschedule demo and Delete sit under one "Actions ▾" menu */}
            <ActionMenu
              items={[
                canEdit && { label: "Edit", onClick: edit },
                canTransfer && !closed && {
                  label: "Transfer",
                  onClick: () => setModal({ type: "transfer", record: item }),
                },
                canRequest && { label: "Request Transfer", onClick: () => setAsking(true) },
                canWork && lead && item.stage === "Demo" && {
                  label: "Reschedule / Cancel Demo",
                  onClick: () => setModal({ type: "cancelDemo", record: item }),
                },
                // not eligible: closes the lead with a reason (it can be reopened later)
                canWork && lead && !closed && {
                  label: "Mark as Unqualified",
                  onClick: () => setModal({ type: "unqualified", record: item }),
                },
                canEdit && lead && item.stage === "Unqualified" && {
                  label: "Reopen Lead",
                  onClick: () => setModal({ type: "reopen", record: item }),
                },
                "-",
                // email campaigns: an address that bounced, or fixed again; a lead who asked to get emails again
                canEdit && lead && item.email && !item.email_invalid_at && {
                  label: "Mark Email as Invalid",
                  onClick: () => setModal({ type: "emailStatus", status: "invalid", record: item }),
                },
                canEdit && lead && item.email_invalid_at && {
                  label: "Mark Email as Valid",
                  onClick: () => setModal({ type: "emailStatus", status: "valid", record: item }),
                },
                canEdit && lead && item.unsubscribed_at && {
                  label: "Subscribe Again",
                  onClick: () => setModal({ type: "emailStatus", status: "subscribed", record: item }),
                },
                "-",
                canEdit && lead && item.stage !== "Converted" && {
                  label: "Delete",
                  danger: true,
                  onClick: () => setModal({ type: "delete", collection, record: item }),
                },
              ]}
            />
          </div>
        </div>
        <dl className="highlights-fields">
          {highlights.filter(Boolean).map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value || " "}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="card path-card">
        <div className="path-main">
          <PathBar
            stages={pathStages}
            skipped={skippedStages}
            notReached={notReached}
            stepState={stepState}
            current={item.stage}
            closed={closed}
            onSelect={canWork ? selectStage : () => {}}
            lostLabel={item.stage === "Lost" ? (lead ? "Lost" : "Closed Lost") : null}
            currentNote={stageClock?.duration}
          />
          {stageClock && <StageClockLine clock={stageClock} since={item.in_stage?.since} />}
          {stageClock?.notice && (
            <div className={`stage-clock-notice ${stageClock.tone}`}>
              <Icon name="warn" size={16} />
              <span>
                <b>{stageClock.badge}.</b> {stageClock.notice}
              </span>
              {canAddTask && (
                <button type="button" className="sf-button small" onClick={() => openTask(item.id, collection)}>
                  <ObjectIcon type="task" size={16} /> New Task
                </button>
              )}
            </div>
          )}
        </div>
        {pooled && !closed && (
          <span className="read-only-note pool-note">
            <Icon name="lock" size={14} /> In the Unassigned Pool: no owner yet.{" "}
            {canAssign
              ? "Assign it to a Salesperson before its status can change."
              : canRequestPool(user)
                ? askedAlready
                  ? "You have asked for it: your Manager or the Admin decides."
                  : "Request it if you should work on it: your Manager or the Admin decides."
                : "The Admin or a Manager assigns it."}
          </span>
        )}
        {!canEdit && !pooled && !closed && (
          <span className="read-only-note">
            <Icon name="lock" size={14} /> Owned by {item.owner}. Only the owner or a Manager can change it.
          </span>
        )}
        {canWork && !closed && nextStage && (nextStage !== "Converted" || canConvert) && (
          <button className="sf-button brand" onClick={() => selectStage(nextStage)}>
            <Icon name="check" size={14} />
            {nextStage === "Converted" ? "Convert" : nextStage === "Won" ? "Mark as Won" : `Mark ${lead ? "Status" : "Stage"} as Complete`}
          </button>
        )}
        {closed && (
          <span className={`path-result ${["Lost", "Unqualified"].includes(item.stage) ? "lost" : "won"}`}>
            {item.stage === "Lost"
              ? `Lost: ${item.lost_reason || ""}`
              : item.stage === "Unqualified"
                ? `Unqualified: ${item.unqualified_reason || ""}`
              : item.stage === "Won"
                ? `Closed Won • ${amount(item.final_value, item.currency)}`
                : "Converted"}
          </span>
        )}
      </section>

      <div className="record-columns">
        <section className="card record-main">
          <div className="tabs" role="tablist">
            {["activity", "details"].map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
                {t === "details" ? "Details" : "Activity"}
              </button>
            ))}
          </div>
          {tab === "activity" ? (
            <ActivityTab
              item={item}
              tasks={tasks}
              toggleTask={toggleTask}
              setModal={setModal}
              openTask={openTask}
              collection={collection}
              emails={emails}
              sendEmail={sendEmail}
              canAddTask={canAddTask}
              canEmail={!summaryOnly}
              addFiles={
                !lead && canEdit && ATTACHMENT_UPLOAD_STAGES.includes(item.stage)
                  ? () => window.dispatchEvent(new Event(PICK_ATTACHMENTS))
                  : undefined
              }
            />
          ) : lead ? (
            <>
              <Section title="Lead Information">
                <Field label="Lead Owner">{item.owner}</Field>
                {summaryOnly && (
                  <Field label="Contact Details">
                    <span className="muted">Shown to the lead&apos;s owner once it is assigned</span>
                  </Field>
                )}
                <Field label="Lead Status"><StageBadge stage={item.stage} /></Field>
                <Field label="Name" onEdit={editField}>
                  {[item.salutation, item.first_name, item.last_name].filter(Boolean).join(" ")}
                </Field>
                <Field label="Company" onEdit={editField}>{item.company}</Field>
                <Field label="Title" onEdit={editField}>{item.title}</Field>
                <Field label="Industry" onEdit={editField}>{item.industry}</Field>
                <Field label="Email" onEdit={editField}>{item.email && <a href={`mailto:${item.email}`}>{item.email}</a>}</Field>
                <Field label="Phone" onEdit={editField}><PhoneReveal value={item.phone} /></Field>
                {/* the country chosen beside the phone, named as in the Leads Region filter (empty when none was chosen) */}
                <Field label="Region" onEdit={editField}>{regionName(item.phone_country) || item.region}</Field>
                <Field label="Lead LinkedIn URL" onEdit={editField}><ExternalLink href={item.linkedin_url} /></Field>
                <Field label="Location" onEdit={editField}>{item.location}</Field>
                <Field label="Lead Source" onEdit={editField}>
                  {item.source}
                  {item.source === "Other" && item.source_detail ? ` (${item.source_detail})` : ""}
                </Field>
                <Field label="Demo Date">
                  <span className="demo-date-value">
                    <span>{formatBusiness(item.demo_at)}</span>
                    {/* only for a demo that is booked now: a lead at Demo with a date (not Converted, Lost or cancelled) */}
                    <AddToCalendar event={demoEvent(item)} />
                  </span>
                </Field>
              </Section>
              <Section title="Company Details">
                <Field label="Company Website" onEdit={editField}><ExternalLink href={item.company_website} /></Field>
                <Field label="Company LinkedIn URL" onEdit={editField}><ExternalLink href={item.company_linkedin_url} /></Field>
                <Field label="Turnover" onEdit={editField}>{amount(item.annual_revenue, item.currency)}</Field>
                <Field label="Headcount" onEdit={editField}>{headcount(item.employees)}</Field>
              </Section>
              {item.stage === "Lost" && (
                <Section title="Lost Details">
                  <Field label="Lost Reason">{item.lost_reason}</Field>
                  <Field label="Lost Notes">{item.lost_notes}</Field>
                </Section>
              )}
              {item.stage === "Unqualified" && (
                <Section title="Unqualified Details">
                  <Field label="Reason">{item.unqualified_reason}</Field>
                  <Field label="Notes">{item.unqualified_notes}</Field>
                </Section>
              )}
              {item.stage === "Revisit" && (
                <Section title="Revisit">
                  <Field label="Revisit On">{dateTime(item.revisit_date)}</Field>
                  <Field label="Reason">{item.revisit_reason}</Field>
                </Section>
              )}
              <Section title="System Information">
                <Field label="Created By">{item.created_by_name}</Field>
                <Field label="Created">{dateTime(item.created_at)}</Field>
                {/* when the current owner got the lead (an older lead's assignment date wasn't recorded) */}
                <Field label="Assigned Date">
                  {pooled ? "Not assigned yet" : item.owner_since ? dateTime(item.owner_since) : <span className="muted">Not recorded</span>}
                </Field>
                <Field label="Last Modified">{dateTime(item.updated_at)}</Field>
                <Field label="Last Transferred">
                  {transfers[0] && `${dateTime(transfers[0].transferred_at)} (to ${transfers[0].to_user_name})`}
                </Field>
                <Field label="Converted Date">{dateTime(item.converted_at)}</Field>
                <Field label="Closed Date">{dateTime(item.closed_at)}</Field>
              </Section>
            </>
          ) : (
            <>
              <Section title="Opportunity Information">
                <Field label="Opportunity Owner" onEdit={editField}>{item.owner}</Field>
                <Field label="Opportunity Name" onEdit={editField}>{item.name}</Field>
                <Field label="Account Name">
                  {item.account_id && <a href={`#/accounts/${item.account_id}`}>{item.account_name}</a>}
                </Field>
                <Field label="Primary Contact" onEdit={editField}>
                  {contact && <a href={`#/contacts/${contact.id}`}>{contact.full_name}</a>}
                </Field>
                <Field label="Close Date" onEdit={editField}>{shortDate(item.expected_close_date)}</Field>
                <Field label="Amount" onEdit={editField}>{amount(item.expected_value, item.currency)}</Field>
                <Field label="Stage"><StageBadge stage={item.stage} /></Field>
                {item.stage === "Won" && <Field label="Final Amount">{amount(item.final_value, item.currency)}</Field>}
                <Field label="Converted From">
                  {sourceLead && <a href={`#/leads/${sourceLead.id}`}>{sourceLead.name}</a>}
                </Field>
              </Section>
              <Section title="Discovery">
                <Field label="Needs / Pain Points" onEdit={editField}>{item.discovery_needs}</Field>
                <Field label="Budget" onEdit={editField}>{item.discovery_budget}</Field>
                <Field label="Decision Maker" onEdit={editField}>{item.discovery_decision_maker}</Field>
                <Field label="Timeline" onEdit={editField}>{item.discovery_timeline}</Field>
              </Section>
              {item.stage === "Lost" && (
                <Section title="Lost Details">
                  <Field label="Lost Reason">{item.lost_reason}</Field>
                  <Field label="Lost Notes">{item.lost_notes}</Field>
                </Section>
              )}
              <Section title="System Information">
                <Field label="Created">{dateTime(item.created_at)}</Field>
                <Field label="Last Modified">{dateTime(item.updated_at)}</Field>
                <Field label="Closed Date">{dateTime(item.closed_at)}</Field>
              </Section>
            </>
          )}
        </section>

        <aside className="record-side">
          {convertedTo && (
            <Card title="Converted To" icon="opportunity">
              <ul className="related-links">
                <li>
                  <ObjectIcon type="opportunity" size={22} /> <a href={`#/opportunities/${convertedTo.id}`}>{convertedTo.name}</a>
                </li>
                <li>
                  <ObjectIcon type="account" size={22} /> <a href={`#/accounts/${convertedTo.account_id}`}>{convertedTo.account_name}</a>
                </li>
                {convertedTo.primary_contact_id && (
                  <li>
                    <ObjectIcon type="contact" size={22} />{" "}
                    <a href={`#/contacts/${convertedTo.primary_contact_id}`}>{convertedTo.primary_contact_name}</a>
                  </li>
                )}
              </ul>
            </Card>
          )}
          <Card
            title={`Notes (${item.notes.length})`}
            icon="note"
            actions={
              !summaryOnly && (
                <button className="sf-button small" onClick={() => setModal({ type: "note", collection, record: item })}>
                  New
                </button>
              )
            }
          >
            {item.notes.length ? (
              <ul className="note-list">
                {item.notes.map((n) => (
                  <li key={n.id}>
                    <p>{n.body}</p>
                    <small>
                      {n.created_by_name} • {dateTime(n.created_at)}
                    </small>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted pad">No notes yet.</p>
            )}
          </Card>
          {lead && requests.length > 0 && (
            <Card title={`${pooled || requests.some((r) => r.pool) ? "Requests" : "Transfer Requests"} (${requests.length})`} icon="contact">
              <TransferRequestList
                rows={requests}
                onChange={(saved) => {
                  loadRequests();
                  // the lead has a new owner (or someone else decided first: the page is loaded again)
                  if (!saved || saved.status === "Approved") reload?.();
                }}
              />
            </Card>
          )}
          {lead && (
            <Card title={`Transfer History (${transfers.length})`} icon="contact">
              {transfers.length ? (
                <ul className="history-list">
                  {transfers.map((t) => (
                    <li key={t.id}>
                      <b>
                        {t.from_user_name || (t.from_user_id == null ? "Unassigned Pool" : "Unassigned")} → {t.to_user_name}
                      </b>
                      {t.note && <p className="history-note">{t.note}</p>}
                      <small>
                        {t.from_user_id == null ? "Assigned by " : ""}
                        {t.transferred_by_name} • {dateTime(t.transferred_at)}
                        {t.request_id ? ` • Request #${t.request_id}` : ""}
                      </small>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted pad">
                  {pooled
                    ? `In the Unassigned Pool since ${dateTime(item.created_at)}: not assigned yet.`
                    : `Not transferred yet. Owned by ${item.owner} since ${dateTime(item.created_at)}.`}
                </p>
              )}
            </Card>
          )}
          <Card title={`Stage History (${item.activity.length})`} icon="event">
            <ul className="history-list">
              {item.activity.map((a, i) => (
                <li key={i}>
                  <b>{a.text}</b>
                  <small>
                    {a.by} • {dateTime(a.date)}
                  </small>
                </li>
              ))}
            </ul>
          </Card>
          {!lead && <OpportunityAttachments key={item.id} opportunity={item} user={user} canEdit={canEdit} />}
        </aside>
      </div>
      {asking && (
        <RequestTransferDialog
          lead={{ id: item.id, name: item.name, owner_name: pooled ? null : item.owner, pool: pooled }}
          onClose={() => setAsking(false)}
          onDone={() => {
            setAsking(false);
            loadRequests();
          }}
        />
      )}
      {assigning && (
        <AssignLeadDialog
          lead={{ id: item.id, name: item.name }}
          user={user}
          users={data.users || []}
          onClose={() => setAssigning(false)}
          onDone={() => {
            setAssigning(false);
            loadRequests();
            reload?.(); // the lead has an owner now
          }}
        />
      )}
    </div>
  );
}
