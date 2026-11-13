import React, { useEffect, useState } from "react";
import { api } from "./api";
import { homeDescription } from "./domain";
import { compactMoney, compactMoneyMix, dateTime, greeting, shortDate, time } from "./format";
import { Card, EmptyState, Icon, ObjectIcon, Ring, StageBadge } from "./ui";
import { formatBusiness, formatBusinessTime } from "./businessTime";
import { can } from "./permissions";
import { PERIODS, localIso, periodLabel, periodQuery } from "./homePeriod";

// Home: one dashboard per role (each card also needs its "Home dashboard" permission, which the Admin sets for
// Managers and Salespeople on the Permissions page; the Admin has them all):
// - Salesperson, and a Manager's Me view: Action Needed, Scheduled Demos, Overall Value, Follow-up Radar, My Scorecard,
//   Recent Activity (GET /api/home)
// - Manager's My Team view: Action Needed, Scheduled Demos, Overall Value, Win/Loss Analysis, Team Performance
//   (GET /api/home/team-charts)
// - Admin (every record): Overall Value, Win/Loss Analysis, Lead Sources, Closing Soon, Follow-up Radar,
//   Recent Activity
// The period (top right) applies to every card except Action Needed, Scheduled Demos, Closing Soon and Recent Activity,
// which are about now.

const COLORS = { open: "#06a59a", won: "#1b96ff", lost: "#ea001e" };
const list = (collection, view) => `#/${collection}?list=${encodeURIComponent(view)}`;
const money = (values) => compactMoneyMix(values);
const percent = (value) => (value === null || value === undefined ? "–" : `${value}%`);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const ROUTE = { Lead: "leads", Opportunity: "opportunities", Account: "accounts", Contact: "contacts" };

function ViewButton({ href, children }) {
  return (
    <a className="outline-button" href={href}>
      {children}
    </a>
  );
}

// Each pill opens the matching list (items: [colorKey, text, href])
function Legend({ items }) {
  return (
    <ul className="legend">
      {items.map(([key, text, href]) => (
        <li key={key}>
          <i style={{ background: COLORS[key] }} />
          <a className={`pill pill-${key}`} href={href}>
            {text}
          </a>
        </li>
      ))}
    </ul>
  );
}

// One series of horizontal bars (one hue; the label on each row names it, the value sits at the bar's end)
function BarList({ rows, format = (v) => v, label }) {
  const max = Math.max(...rows.map((r) => r.value), 0);
  return (
    <ul className="team-bars" aria-label={label}>
      {rows.map((r) => (
        <li key={r.label} title={`${r.label}: ${format(r.value, r)}${r.note ? ` (${r.note})` : ""}`}>
          <span className="team-bar-label">{r.href ? <a href={r.href}>{r.label}</a> : r.label}</span>
          <span className="team-bar-track">
            <span className="team-bar" style={{ width: max ? `${Math.max((r.value / max) * 100, r.value ? 2 : 0)}%` : 0 }} />
          </span>
          <span className="team-bar-value">
            {format(r.value, r)}
            {r.note && <small>{r.note}</small>}
          </span>
        </li>
      ))}
    </ul>
  );
}

// A "Today" or "Upcoming" part of Action Needed / Scheduled Demos
function Section({ title, count, children }) {
  return (
    <div className="home-section">
      <h3>
        {title} <span className="home-section-count">{count}</span>
      </h3>
      {children}
    </div>
  );
}

function TaskRows({ tasks, toggleTask, showDay, empty }) {
  if (!tasks.length) return <p className="home-section-empty">{empty}</p>;
  return (
    <ul className="home-tasks work-list">
      {tasks.slice(0, 5).map((t) => (
        <li key={t.id}>
          <input type="checkbox" aria-label={`Complete ${t.title}`} checked={t.completed} disabled={t.completed} onChange={() => toggleTask(t.id)} />
          <div>
            <a href={t.relatedType !== "general" ? `#/${t.relatedType}/${t.relatedId}` : `#/tasks?task=${t.id}`}>{t.title}</a>
            {t.related_to && (
              <small>
                {t.related_type}: {t.related_to}
              </small>
            )}
          </div>
          <span className={t.isOverdue ? "due overdue" : "due"}>
            {t.isOverdue ? `Overdue · ${shortDate(t.due_date)}` : showDay ? dateTime(t.due_date) : time(t.due_date)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function EventRows({ events, showDay, empty }) {
  if (!events.length) return <p className="home-section-empty">{empty}</p>;
  return (
    <ul className="home-tasks work-list">
      {events.slice(0, 5).map((e) => (
        <li key={`${e.lead_id}${e.start}`}>
          <ObjectIcon type="event" size={24} />
          <div>
            <a href={`#/leads/${e.lead_id}`}>Demo with {e.name}</a>
            <small>{e.company}</small>
          </div>
          <span className="due">{showDay ? formatBusiness(e.start_at) : formatBusinessTime(e.start_at)}</span>
        </li>
      ))}
    </ul>
  );
}

// Overall Value: open, won and lost amounts of the opportunities created in the period (pills open the lists)
function PipelineCard({ pipeline, views, range }) {
  const show = (key) => money(pipeline.by_currency?.[key]);
  return (
    <Card title="Overall Value" className="home-card" footer={<ViewButton href={`${list("opportunities", views.all)}${range}`}>View Opportunities</ViewButton>}>
      <div className="ring-row">
        <Ring
          label={`Total pipeline ${show("total_pipeline")}`}
          segments={[
            { value: pipeline.open, color: COLORS.open },
            { value: pipeline.won, color: COLORS.won },
            { value: pipeline.lost, color: COLORS.lost },
          ]}
        >
          {/* two or more currencies ("$85M + ₹42M") get a smaller line so they stay inside the ring */}
          <strong className={show("total_pipeline").length > 8 ? "ring-long" : ""}>{show("total_pipeline")}</strong>
          <span>Total Pipeline</span>
        </Ring>
        <Legend
          items={[
            ["open", `${show("open")} Open`, `${list("opportunities", views.open)}${range}`],
            ["won", `${show("won")} Won`, `${list("opportunities", views.won)}${range}`],
            ["lost", `${show("lost")} Lost`, `${list("opportunities", views.lost)}${range}`],
          ]}
        />
      </div>
    </Card>
  );
}

// Won and Lost side by side (count and amount): My Scorecard and Win/Loss Analysis
function Outcomes({ won, wonValues, lost, lostValues }) {
  return (
    <div className="home-score-outcomes">
      <div className="home-score-won">
        <span>Won</span>
        <b>{won ?? 0}</b>
        <small>{money(wonValues)}</small>
      </div>
      <div className="home-score-lost">
        <span>Lost</span>
        <b>{lost ?? 0}</b>
        <small>{money(lostValues)}</small>
      </div>
    </div>
  );
}

// Win/Loss Analysis (Manager's team, Admin): won vs lost, the win rate and the top lost reasons
function WinLossCard({ results, range }) {
  return (
    <Card title="Win/Loss Analysis" className="home-card" footer={<ViewButton href={`${list("opportunities", "Lost Opportunities")}${range}`}>View Lost Opportunities</ViewButton>}>
      <Outcomes won={results.won.count} wonValues={results.won.values} lost={results.lost.count} lostValues={results.lost.values} />
      <p className="home-winrate">
        <b>{percent(results.win_rate)}</b> win rate
      </p>
      <h3 className="home-subhead">Top lost reasons</h3>
      {results.lost_reasons.length ? (
        <BarList label="Top lost reasons" rows={results.lost_reasons.map((r) => ({ label: r.reason, value: r.count }))} />
      ) : (
        <p className="home-section-empty home-note">No deals lost yet.</p>
      )}
    </Card>
  );
}

// Closing Soon (Admin): open opportunities closing in the next 30 days (or late), with their owner
function ClosingSoonCard({ deals }) {
  return (
    <Card title="Closing Soon" className="home-card" footer={<ViewButton href={list("opportunities", "Open Opportunities")}>View Opportunities</ViewButton>}>
      {deals.length ? (
        <ul className="deal-list">
          {deals.map((d) => (
            <li key={d.id}>
              <ObjectIcon type="opportunity" size={28} />
              <div>
                <a href={`#/opportunities/${d.id}`}>{d.name}</a>
                <small className={d.late ? "overdue" : ""}>
                  {d.account_name} • {d.late ? "Was due" : "Closes"} {shortDate(d.close_date)}
                </small>
                {d.owner_name && <small>{d.owner_name}</small>}
              </div>
              <div className="deal-amount">
                <b>{compactMoney(d.amount, d.currency)}</b>
                <StageBadge stage={d.stage} />
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState text="Nothing closing in the next 30 days." small />
      )}
    </Card>
  );
}

// Follow-up Radar: leads, accounts and contacts created in the period; each pill opens the records with that activity
function RadarCard({ home, mine, range }) {
  const rows = [
    ["Lead", "leads", mine ? "My Leads" : "All Leads", home.build_pipeline],
    ["Account", "accounts", mine ? "My Accounts" : "All Accounts", home.accounts],
    ["Contact", "contacts", mine ? "My Contacts" : "All Contacts", home.contacts],
  ];
  return (
    <Card title="Follow-up Radar" className="home-card">
      <ul className="home-radar">
        {rows.map(([noun, collection, view, stats]) => {
          const pick = (activity) => `${list(collection, view)}&activity=${activity}${range}`;
          return (
            <li key={collection}>
              <a className="home-radar-name" href={`${list(collection, view)}${range}`}>
                {plural(stats.total, noun)}
              </a>
              <span>
                <a className="pill pill-upcoming" href={pick("upcoming")}>
                  {stats.upcoming_activity} Upcoming
                </a>
                <a className="pill pill-past" href={pick("past")}>
                  {stats.past_activity} Past
                </a>
                <a className="pill pill-none" href={pick("none")}>
                  {stats.no_activity} No Activity
                </a>
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

// Recent Activity: the leads, opportunities, accounts and contacts changed last (the Admin's also names the owner)
function RecentCard({ records, showOwner }) {
  return (
    <Card title="Recent Activity" className="home-card">
      {records.length ? (
        <ul className="recent-list home-recent">
          {records.map((r) => (
            <li key={r.type + r.id}>
              <ObjectIcon type={r.type} size={28} />
              <div>
                <a href={`#/${ROUTE[r.type]}/${r.id}`}>{r.name}</a>
                <small>
                  {r.type}
                  {showOwner && r.owner_name ? ` • ${r.owner_name}` : ""} • {dateTime(r.updated_at)}
                </small>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState text="Records you work on will show up here." small />
      )}
    </Card>
  );
}

// Lead Sources: leads created in the period per source, and the share of them converted
function SourcesCard({ sources, range }) {
  return (
    <Card title="Lead Sources" className="home-card" footer={<ViewButton href={`${list("leads", "All Leads")}${range}`}>View Leads</ViewButton>}>
      {sources.length ? (
        <BarList
          label="Leads by source"
          format={(v, r) => `${v} · ${percent(r.rate)}`}
          rows={sources.map((s) => ({ label: s.source, value: s.leads, rate: s.conversion_rate, note: `${s.converted} converted` }))}
        />
      ) : (
        <EmptyState text="No new leads." small />
      )}
    </Card>
  );
}

// Team Performance: each salesperson ranked by deals won, then converted leads, then open pipeline
function LeaderboardCard({ people }) {
  const ranked = [...people].sort(
    (a, b) =>
      b.won_count - a.won_count ||
      b.converted_this_month - a.converted_this_month ||
      b.open_pipeline - a.open_pipeline ||
      a.name.localeCompare(b.name),
  );
  const top = Math.max(...ranked.map((p) => p.open_pipeline), 0);
  return (
    <Card title="Team Performance" className="home-card home-wide">
      <div className="table-scroll">
        <table className="sf-table">
          <thead>
            <tr>
              <th className="num">Rank</th>
              <th>Name</th>
              <th className="num">Open Leads</th>
              <th className="num">Converted</th>
              <th>Open Pipeline</th>
              <th className="num">Deals Won</th>
              <th className="num">Won</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((p, i) => (
              <tr key={p.id}>
                <td className="num">{i + 1}</td>
                <td>
                  {p.name} {p.role === "Manager" && <small className="muted">(Manager)</small>}
                </td>
                <td className="num">{p.open_leads}</td>
                <td className="num">{p.converted_this_month}</td>
                <td>
                  <span className="team-inline-bar">
                    <span style={{ width: `${top ? (p.open_pipeline / top) * 100 : 0}%` }} />
                    <b>{money(p.open_pipeline_values)}</b>
                  </span>
                </td>
                <td className="num">{p.won_count}</td>
                <td className="num">{money(p.won_this_month_values)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!ranked.length && <p className="table-empty">No salespeople yet.</p>}
      </div>
    </Card>
  );
}

// Period selector (top right). Past 1 week applies at once; a custom range needs From, To and Apply.
function PeriodPicker({ period, setPeriod, shown }) {
  const toInput = (value) => localIso(new Date(value)).slice(0, 16); // datetime-local: 2026-11-12T15:30
  const [custom, setCustom] = useState(period.preset === "custom" ? { from: period.from, to: period.to } : null);
  const choose = (preset) => {
    if (preset === "custom") setCustom({ from: toInput(shown.start), to: toInput(new Date()) });
    else {
      setCustom(null);
      setPeriod({ preset });
    }
  };
  const valid = custom && custom.from && custom.to && custom.from < custom.to;
  return (
    <div className="home-period">
      <div className="home-period-row">
        <Icon name="calendar" size={16} />
        <label className="sr-only" htmlFor="home-period">
          Period
        </label>
        <select id="home-period" value={custom ? "custom" : period.preset} onChange={(e) => choose(e.target.value)}>
          {PERIODS.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <small className="home-period-range">{periodLabel(shown.start, shown.end, period.preset === "custom")}</small>
      {custom && (
        <form
          className="home-period-custom"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) setPeriod({ preset: "custom", ...custom });
          }}
        >
          <label>
            <span>From</span>
            <input type="datetime-local" value={custom.from} max={custom.to} onChange={(e) => setCustom({ ...custom, from: e.target.value })} required />
          </label>
          <label>
            <span>To</span>
            <input type="datetime-local" value={custom.to} min={custom.from} onChange={(e) => setCustom({ ...custom, to: e.target.value })} required />
          </label>
          <button className="sf-button brand" disabled={!valid}>
            Apply
          </button>
        </form>
      )}
    </div>
  );
}

// The team cards' data (GET /api/home/team-charts) for this period
function useTeamCharts(enabled, period) {
  const [charts, setCharts] = useState(null);
  const [error, setError] = useState("");
  const key = JSON.stringify(period);
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    setError("");
    api
      .teamCharts(periodQuery(period))
      .then((value) => live && setCharts(value))
      .catch((err) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, [enabled, key]); // eslint-disable-line react-hooks/exhaustive-deps
  return { charts: enabled ? charts : null, error };
}

const MINE = { all: "My Opportunities", open: "My Open Opportunities", won: "My Won Opportunities", lost: "My Lost Opportunities" };
const EVERYONE = { all: "All Opportunities", open: "Open Opportunities", won: "Won Opportunities", lost: "Lost Opportunities" };

export default function SellerHome({
  data,
  user,
  toggleTask,
  openTask,
  scope = "team",
  setScope = () => {},
  teamDashboard = true,
  period = { preset: "7d" },
  setPeriod = () => {},
}) {
  const isAdmin = user.role === "Admin";
  const teamView = isAdmin || (teamDashboard && scope === "team");
  const { charts, error } = useTeamCharts(teamView, period);
  const home = data.home?.seller_home;
  if (!home) return null;
  const shows = (card) => can(user, `home_${card}`);

  // the period the API counted (no end = up to now): every pill and View button opens its records with it
  const counted = (teamView ? charts?.period : null) || home.period || { start: localIso(new Date(Date.now() - 7 * 864e5)), end: null };
  const shown = { start: counted.start, end: counted.end || new Date() };
  const range = `&from=${encodeURIComponent(counted.start)}${counted.end ? `&to=${encodeURIComponent(counted.end)}` : ""}`;
  const tasksFor = (rows) => (rows || []).map((t) => data.tasks.find((x) => x.id === String(t.id))).filter(Boolean);
  const todayTasks = tasksFor(home.my_tasks?.today);
  const upcomingTasks = tasksFor(home.my_tasks?.upcoming);

  // ----- the user's own work: on the Manager's and Salesperson's dashboards (not the Admin's) -----
  const work = isAdmin
    ? []
    : [
        shows("action_items") && (
          <Card
            key="actions"
            title="Action Needed"
            className="home-card"
            actions={
              <button className="icon-btn" aria-label="New task" title="New Task" onClick={() => openTask()}>
                <Icon name="plus" size={14} />
              </button>
            }
            footer={<ViewButton href="#/tasks">View Tasks</ViewButton>}
          >
            <Section title="Today" count={todayTasks.length}>
              <TaskRows tasks={todayTasks} toggleTask={toggleTask} empty="Nothing due today." />
            </Section>
            <Section title="Upcoming" count={upcomingTasks.length}>
              <TaskRows tasks={upcomingTasks} toggleTask={toggleTask} showDay empty="Nothing planned for the next 7 days." />
            </Section>
          </Card>
        ),
        shows("meetings") && (
          <Card key="meetings" title="Scheduled Demos" className="home-card" footer={<ViewButton href={list("leads", "My Open Leads")}>View Leads</ViewButton>}>
            <Section title="Today" count={home.todays_events.length}>
              <EventRows events={home.todays_events} empty="No demos today." />
            </Section>
            <Section title="Upcoming" count={(home.upcoming_events || []).length}>
              <EventRows events={home.upcoming_events || []} showDay empty="No demos booked for the next 7 days." />
            </Section>
          </Card>
        ),
      ];

  let cards = [];
  if (!teamView) {
    const score = home.scorecard || {};
    cards = [
      ...work,
      shows("pipeline") && <PipelineCard key="pipeline" pipeline={home.close_deals} views={MINE} range={range} />,
      shows("follow_up_radar") && <RadarCard key="radar" home={home} mine range={range} />,
      shows("scorecard") && (
        <Card key="score" title="My Scorecard" className="home-card">
          <Outcomes won={score.won} wonValues={score.won_values} lost={score.lost} lostValues={score.lost_values} />
          <dl className="home-score">
            <div>
              <dt>Win rate</dt>
              <dd>{percent(score.win_rate)}</dd>
            </div>
            <div>
              <dt>Leads converted</dt>
              <dd>{score.converted ?? 0}</dd>
            </div>
            <div>
              <dt>Average deal</dt>
              <dd>{money(score.average_deal)}</dd>
            </div>
          </dl>
        </Card>
      ),
      shows("recent_activity") && <RecentCard key="recent" records={home.recent_records} />,
    ];
  } else if (charts) {
    // ----- the Manager's My Team view / the Admin's dashboard -----
    cards = [
      ...work,
      shows("pipeline") && <PipelineCard key="pipeline" pipeline={charts.pipeline} views={EVERYONE} range={range} />,
      shows("win_loss") && <WinLossCard key="winloss" results={charts.win_loss} range={range} />,
      isAdmin && charts.lead_sources && <SourcesCard key="sources" sources={charts.lead_sources} range={range} />,
      isAdmin && charts.closing_soon && <ClosingSoonCard key="closing" deals={charts.closing_soon} />,
      isAdmin && <RadarCard key="radar" home={home} range={range} />,
      !isAdmin && shows("team_performance") && <LeaderboardCard key="leaders" people={charts.people} />,
      isAdmin && charts.recent_records && <RecentCard key="recent" records={charts.recent_records} showOwner />,
    ];
  }
  cards = cards.filter(Boolean);

  return (
    <div className="page seller-home">
      <div className="home-title">
        <div className="home-greeting">
          {/* Title Case on the page title: "Good Evening" */}
          <h1>{greeting().replace(/\b\w/g, (c) => c.toUpperCase())}!</h1>
          <p>{homeDescription(user.role, teamView)}</p>
        </div>
        <div className="home-controls">
          <PeriodPicker period={period} setPeriod={setPeriod} shown={shown} />
          {teamDashboard && !isAdmin && (
            <div className="home-scope" role="group" aria-label="Show records">
              <button className={scope === "team" ? "on" : ""} aria-pressed={scope === "team"} onClick={() => setScope("team")}>
                My Team
              </button>
              <button className={scope === "team" ? "" : "on"} aria-pressed={scope !== "team"} onClick={() => setScope("mine")}>
                Me
              </button>
            </div>
          )}
        </div>
      </div>

      {error && <p className="table-empty">{error}</p>}
      {teamView && !charts && !error ? (
        <p className="table-empty">Loading the dashboard…</p>
      ) : cards.length ? (
        <div className="home-grid">{cards}</div>
      ) : (
        !error && <EmptyState text="No Home cards are turned on for your role. Your Admin can choose them on the Permissions page." />
      )}
    </div>
  );
}
