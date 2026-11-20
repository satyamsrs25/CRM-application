// Home's period selector (top right of the Dashboard and of Analytics): Past 1 week / Past 1 month apply at once; a
// custom range needs From, To and Apply (the box then closes; the dates under the picker open it again).
// period: { preset, from, to }; shown: { start, end } (what is counted).
import React, { useState } from "react";
import { PERIODS, localIso, periodLabel } from "./homePeriod";
import { Icon } from "./ui";

export default function PeriodPicker({ period, setPeriod, shown, id = "home-period" }) {
  const toInput = (value) => localIso(new Date(value)).slice(0, 16); // datetime-local: 2026-11-12T15:30
  const [custom, setCustom] = useState(null); // the From / To box, while it is open
  const choose = (preset) => {
    // a custom range opens with the dates in use (the applied range, or the current period up to now)
    if (preset === "custom")
      setCustom(
        period.preset === "custom" && period.from && period.to
          ? { from: period.from, to: period.to }
          : { from: toInput(shown.start), to: toInput(new Date()) },
      );
    else {
      setCustom(null);
      setPeriod({ preset });
    }
  };
  const valid = custom && custom.from && custom.to && custom.from < custom.to;
  const range = periodLabel(shown.start, shown.end, period.preset === "custom");
  return (
    <div className="home-period">
      <div className="home-period-row">
        <Icon name="calendar" size={16} />
        <label className="sr-only" htmlFor={id}>
          Period
        </label>
        {/* an applied custom range shows through a hidden "applied" option, so choosing Custom range again in the
            list is a change and reopens From / To */}
        <select
          id={id}
          value={custom ? "custom" : period.preset === "custom" ? "applied" : period.preset}
          onChange={(e) => choose(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && setCustom(null)}
        >
          {period.preset === "custom" && !custom && (
            <option value="applied" hidden>
              Custom range
            </option>
          )}
          {PERIODS.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {period.preset === "custom" && !custom ? (
        <button type="button" className="home-period-range" title="Change the range"
          onClick={() => setCustom({ from: period.from || toInput(shown.start), to: period.to || toInput(shown.end) })}>
          {range}
        </button>
      ) : (
        <small className="home-period-range">{range}</small>
      )}
      {custom && (
        <form
          className="home-period-custom"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) {
              setPeriod({ preset: "custom", ...custom });
              setCustom(null);
            }
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
