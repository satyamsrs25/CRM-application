// Leads Kanban: the same list view, filters and search as the Leads table (LeadsTable.jsx loads one page per column).
// Each column shows its exact total and one page of cards, with Previous / Next and the range ("16–30 of 549"), so
// every lead can be reached however many there are. Cards per page is chosen above the board (as on the List page).
// Dragging a card to a column opens the popup the lead page uses (Change Stage with its required note, Convert, Mark as
// Lost, Mark as Unqualified). Nothing moves until that popup is saved; the board is then loaded again. Converted, Lost
// and Unqualified are closed: their cards don't move. A column that isn't part of the list view takes no drops.
// The Unassigned column (first, before Unqualified) holds the leads in the Unassigned Pool, which are in no stage
// column too. Its cards never move and nothing can be dropped on it: dragging is not a way to claim or assign a lead.
// The Admin or a Manager assigns it, and a Salesperson requests it, from the lead's page.
// Each card shows its time at its status (coloured by its rating; a pooled lead's waiting time is neutral), a red border
// when an open lead is stalled, and its details (LeadCardDetails) on a resting mouse, keyboard focus or a tap. A stage
// column's header counts its stalled leads (all of them, every page: from the server).
import React, { useState } from "react";
import { dateTime } from "./format";
import { initials, isPooledLead, leadStageAction, POOL_LABEL } from "./domain";
import { columnRange, inStageBadge } from "./listHelpers";
import { LeadCardDetails, useCardDetails } from "./OpportunityTools";
import { can, canCreateSales, seesPoolContacts } from "./permissions";
import { Icon } from "./ui";

// a rated open lead past its status's Stalled limit (pooled waiting time, closed and untimed leads never are)
const isStalled = (lead) => lead.in_stage?.state === "timed" && lead.in_stage.category === "stalled";

function CardAge({ lead }) {
  const badge = inStageBadge(lead.in_stage, lead.stage, isPooledLead(lead));
  if (!badge || badge.tone === "closed") return null;
  const label = lead.in_stage?.since ? `${badge.label} (since ${dateTime(lead.in_stage.since)})` : badge.label;
  return (
    <div className="kanban-age">
      <span className={`stage-badge in-stage ${badge.tone}`} title={label}>
        <span aria-hidden="true">{badge.text}</span>
        <span className="sr-only">{label}</span>
      </span>
    </div>
  );
}

// why a column has no cards on this board, and what brings it back
const EXCLUDED_HELP = {
  "Not in this list view": "Choose All Leads (or the matching list view) to see these leads.",
  "Hidden by the Lead Status filter": "Clear the Lead Status filter to see this column.",
  "Hidden by the Owner filter": "Clear the Owner filter to see this column.",
};

export default function LeadsKanban({ columns, board, user, setModal, size, pages = {}, busy = {}, onPage, tasks = [], limits, openTask, openEmail, onRequest }) {
  const [over, setOver] = useState(null);
  const { openId, close, cardProps, infoProps } = useCardDetails();
  // what a card's details offer: the app's own forms, nothing done until they are submitted. A pooled lead has no
  // follow-ups or calls yet; one whose contact details this user may not see shows none (the server never sent them).
  const actionsFor = (lead) => {
    const pooled = isPooledLead(lead);
    const hidden = !!lead.contact_hidden;
    return {
      addTask: !pooled && openTask ? () => (close(), openTask(lead.id, "leads")) : null,
      logCall: !hidden && (!pooled || seesPoolContacts(user)) ? () => (close(), setModal({ type: "call", collection: "leads", record: lead, contactName: lead.name })) : null,
      email:
        !hidden && openEmail
          ? () => (
              close(),
              openEmail({ type: "lead", field: "lead_id", id: lead.id, name: lead.name, email: lead.email, firstName: lead.first_name, stage: lead.stage,
                noEmail: "This lead has no email address." })
            )
          : null,
      request: pooled && onRequest ? () => (close(), onRequest(lead)) : null,
    };
  };
  // Salespeople change only their own leads, Managers and Admins any; converting follows the same rule (as on the lead page)
  const rights = (lead) => {
    const canEdit = lead.owner_id === user?.id || can(user, "edit_team_records");
    return { canEdit, canConvert: canEdit && canCreateSales(user) };
  };
  const movable = (lead) => columns.some(({ stage, excluded }) => !excluded && leadStageAction(lead, stage, rights(lead)));
  // Previous / Next: that column's page; if its top is above the screen (a long page of cards), it comes back into view
  const turn = (event, stage, page) => {
    onPage(stage, page);
    const column = event.currentTarget.closest(".kanban-col");
    if (column && column.getBoundingClientRect().top < 0) column.scrollIntoView({ block: "start" });
  };
  const drop = (stage, id) => {
    setOver(null);
    const lead = columns.flatMap((c) => board?.[c.stage]?.items || []).find((l) => String(l.id) === id);
    const action = lead && leadStageAction(lead, stage, rights(lead));
    if (action) setModal(action);
  };
  return (
    <div className="kanban lead-board">
      {columns.map(({ stage, closed, excluded, pool }) => {
        const column = excluded ? null : board?.[stage];
        const items = column?.items || [];
        const page = column?.page ?? pages[stage] ?? 0;
        const loading = !!busy[stage];
        const range = column ? columnRange(page, size, column.total) : null;
        return (
          <section
            key={stage}
            className={`kanban-col stage-${stage.toLowerCase()} ${closed ? "closed" : ""} ${pool ? "pool" : ""} ${excluded ? "excluded" : ""} ${over === stage ? "drag-over" : ""}`}
            aria-label={
              excluded
                ? `${stage}: ${excluded}`
                : `${stage}: ${column ? `${column.total.toLocaleString()} lead${column.total === 1 ? "" : "s"}` : "loading"}`
            }
            aria-busy={loading || undefined}
            onDragOver={(e) => {
              if (pool || excluded) return; // nothing is dropped on the Unassigned column or a column outside the view
              e.preventDefault();
              setOver(stage);
            }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              e.preventDefault();
              drop(stage, e.dataTransfer.getData("text/plain"));
            }}
          >
            <header>
              <div>
                <h3 className={`kanban-stage k-${stage.toLowerCase()}`}>{stage}</h3>
                <p>
                  {excluded || (pool ? "No owner yet" : closed ? "Closed" : "Open")}
                  {range && range.pages > 1 && ` • ${range.range.split(" of ")[0]}`}
                </p>
                {/* every stalled lead in the column, not only this page's */}
                {!pool && !closed && column && column.stalled != null && (
                  <p className={`kanban-stalled${column.stalled ? " on" : ""}`}>{column.stalled.toLocaleString()} stalled</p>
                )}
              </div>
              {/* an excluded column has no count: its leads aren't part of this board */}
              {!excluded && (
                <span className="kanban-count" aria-label={`${column ? column.total : 0} leads`}>
                  {column ? column.total.toLocaleString() : "…"}
                </span>
              )}
            </header>
            <div className={`kanban-cards ${loading && column ? "is-loading" : ""}`}>
              {items.map((lead) => {
                const canMove = movable(lead);
                return (
                  <article
                    key={lead.id}
                    {...cardProps(lead.id)}
                    className={`kanban-card${isStalled(lead) ? " stalled" : ""}`}
                    aria-labelledby={`lead-card-${lead.id}`}
                    draggable={canMove}
                    title={canMove ? "Drag to another column to change its stage" : undefined}
                    onDragStart={(e) => {
                      if (e.target.closest?.(".card-details")) return e.preventDefault(); // selecting text in the details
                      close();
                      e.dataTransfer.setData("text/plain", String(lead.id));
                      e.dataTransfer.effectAllowed = "move";
                    }}
                    onDragEnd={() => setOver(null)}
                  >
                    <div className="kanban-card-head">
                      <span className="kanban-initials" aria-hidden="true">{initials(lead.name)}</span>
                      <a id={`lead-card-${lead.id}`} href={`#/leads/${lead.id}`}>
                        {lead.name}
                      </a>
                      <button {...infoProps(lead.id, lead.name)}>
                        <Icon name="info" size={15} />
                      </button>
                    </div>
                    <p className={`kanban-line${lead.company ? "" : " none"}`} title="Company">
                      <Icon name="building" size={13} /> <span>{lead.company || "No company"}</span>
                    </p>
                    <p className={`kanban-line${lead.title ? "" : " none"}`} title="Title">
                      <Icon name="briefcase" size={13} /> <span>{lead.title || "No title"}</span>
                    </p>
                    <div className="kanban-card-foot">
                      <span className={`kanban-owner${isPooledLead(lead) ? " pool" : ""}`}>
                        {lead.owner_name || (isPooledLead(lead) ? POOL_LABEL : "No owner")}
                      </span>
                      {lead.source && <small>{lead.source}{pool ? " (locked)" : ""}</small>}
                    </div>
                    <CardAge lead={lead} />
                    {openId === lead.id && (
                      <LeadCardDetails id={`card-details-${lead.id}`} lead={lead} tasks={tasks} limits={limits} actions={actionsFor(lead)} />
                    )}
                  </article>
                );
              })}
              {/* an empty column stays blank (its count shows 0); one outside the view says why */}
              {!items.length && (excluded || !column) && (
                <p className="kanban-empty">{excluded ? EXCLUDED_HELP[excluded] || excluded : loading ? "Loading…" : "Not loaded"}</p>
              )}
            </div>
            {range && column.total > 0 && (
              <nav className="kanban-pager" aria-label={`${stage} pages`}>
                <p className="kanban-range" aria-live="polite">
                  <b>{range.range}</b>
                  {range.pages > 1 && <span>{range.pageText}</span>}
                </p>
                {range.pages > 1 && (
                  <div className="kanban-pager-buttons">
                    <button
                      type="button"
                      className="sf-button small"
                      onClick={(e) => turn(e, stage, page - 1)}
                      disabled={page === 0 || loading}
                      aria-label={`Previous page of ${stage}`}
                    >
                      <Icon name="left" size={12} /> Previous
                    </button>
                    <button
                      type="button"
                      className="sf-button small"
                      onClick={(e) => turn(e, stage, page + 1)}
                      disabled={page >= range.pages - 1 || loading}
                      aria-label={`Next page of ${stage}`}
                    >
                      Next <Icon name="right" size={12} />
                    </button>
                  </div>
                )}
              </nav>
            )}
          </section>
        );
      })}
    </div>
  );
}
