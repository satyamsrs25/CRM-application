// Leads Kanban: the same list view, filters and search as the Leads table (LeadsTable.jsx loads one page per column).
// Each column shows its exact total and one page of cards, with Previous / Next and the range ("16–30 of 549"), so
// every lead can be reached however many there are. Cards per page is chosen above the board (as on the List page).
// Dropping a card on a column, or choosing it in the card's Change Status menu, opens the popup the lead page uses
// (Change Stage with its required note, Convert, Mark as Lost). Nothing moves until that popup is saved; the board
// is then loaded again. Converted and Lost are closed: their cards don't move.
import React, { useState } from "react";
import { leadStageAction } from "./domain";
import { columnRange } from "./listHelpers";
import { can, canCreateSales } from "./permissions";
import { ActionMenu, Icon } from "./ui";

const MENU_LABEL = { Converted: "Convert", Lost: "Mark as Lost" };
// why a column has no cards on this board, and what brings it back
const EXCLUDED_HELP = {
  "Not in this list view": "Choose All Leads (or the matching list view) to see these leads.",
  "Hidden by the Lead Status filter": "Clear the Lead Status filter to see this column.",
};

export default function LeadsKanban({ columns, board, user, setModal, size, pages = {}, busy = {}, onPage }) {
  const [over, setOver] = useState(null);
  // Salespeople change only their own leads, Managers and Admins any; converting follows the same rule (as on the lead page)
  const rights = (lead) => {
    const canEdit = lead.owner_id === user?.id || can(user, "edit_team_records");
    return { canEdit, canConvert: canEdit && canCreateSales(user) };
  };
  const moves = (lead) =>
    columns
      .map(({ stage }) => ({ stage, action: leadStageAction(lead, stage, rights(lead)) }))
      .filter(({ action }) => action);
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
      {columns.map(({ stage, closed, excluded }) => {
        const column = excluded ? null : board?.[stage];
        const items = column?.items || [];
        const page = column?.page ?? pages[stage] ?? 0;
        const loading = !!busy[stage];
        const range = column ? columnRange(page, size, column.total) : null;
        return (
          <section
            key={stage}
            className={`kanban-col ${closed ? "closed" : ""} ${excluded ? "excluded" : ""} ${over === stage ? "drag-over" : ""}`}
            aria-label={
              excluded
                ? `${stage}: ${excluded}`
                : `${stage}: ${column ? `${column.total.toLocaleString()} lead${column.total === 1 ? "" : "s"}` : "loading"}`
            }
            aria-busy={loading || undefined}
            onDragOver={(e) => {
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
              <h3 className={`kanban-stage k-${stage.toLowerCase()}`}>
                {/* an excluded column has no count: its leads aren't part of this board */}
                {excluded ? stage : `${stage} (${column ? column.total.toLocaleString() : "…"})`}
              </h3>
              <p>
                {excluded || (closed ? "Closed" : "Open")}
                {range && range.pages > 1 && ` • ${range.range.split(" of ")[0]}`}
              </p>
            </header>
            <div className={`kanban-cards ${loading && column ? "is-loading" : ""}`}>
              {items.map((lead) => {
                const options = moves(lead);
                return (
                  <article
                    key={lead.id}
                    className="kanban-card"
                    aria-labelledby={`lead-card-${lead.id}`}
                    draggable={options.length > 0}
                    onDragStart={(e) => {
                      e.dataTransfer.setData("text/plain", String(lead.id));
                      e.dataTransfer.effectAllowed = "move";
                    }}
                    onDragEnd={() => setOver(null)}
                  >
                    <a id={`lead-card-${lead.id}`} href={`#/leads/${lead.id}`}>
                      {lead.name}
                    </a>
                    <dl>
                      <dt>Company</dt>
                      <dd>{lead.company || "—"}</dd>
                      {lead.title && (
                        <>
                          <dt>Title</dt>
                          <dd>{lead.title}</dd>
                        </>
                      )}
                    </dl>
                    <div className="lead-card-foot">
                      <small>{lead.owner_name}</small>
                      {options.length > 0 && (
                        <ActionMenu
                          label="Change Status"
                          items={options.map(({ stage: to, action }) => ({
                            label: MENU_LABEL[to] || `Move to ${to}`,
                            onClick: () => setModal(action),
                          }))}
                        />
                      )}
                    </div>
                  </article>
                );
              })}
              {!items.length && (
                <p className="kanban-empty">
                  {excluded ? (
                    EXCLUDED_HELP[excluded] || excluded
                  ) : column ? (
                    "No leads"
                  ) : loading ? (
                    "Loading…"
                  ) : (
                    "Not loaded"
                  )}
                </p>
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
