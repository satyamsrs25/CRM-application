// Calendar export utilities for SalesTrack CRM (Google Calendar, Outlook Web, and iCal .ics)
import React, { useEffect, useRef, useState } from "react";
import { Icon } from "./ui";

export function googleCalendarUrl({ title, start, description, location }) {
  const startDate = new Date(start);
  const endDate = new Date(startDate.getTime() + 60 * 60 * 1000); // 1-hour duration
  const fmt = (d) => d.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: title,
    dates: `${fmt(startDate)}/${fmt(endDate)}`,
    details: description || "",
    location: location || "",
  });
  return `https://calendar.google.com/calendar/render?${params.toString()}`;
}

export function outlookCalendarUrl({ title, start, description, location }) {
  const startDate = new Date(start);
  const endDate = new Date(startDate.getTime() + 60 * 60 * 1000);
  const params = new URLSearchParams({
    path: "/calendar/action/compose",
    rru: "addevent",
    subject: title,
    startdt: startDate.toISOString(),
    enddt: endDate.toISOString(),
    body: description || "",
    location: location || "",
  });
  return `https://outlook.live.com/calendar/0/deeplink/compose?${params.toString()}`;
}

export function downloadIcs({ title, start, description, location }) {
  const startDate = new Date(start);
  const endDate = new Date(startDate.getTime() + 60 * 60 * 1000);
  const fmt = (d) => d.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
  const ics = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//SalesTrack CRM//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `SUMMARY:${title.replace(/[\r\n]/g, " ")}`,
    `DTSTART:${fmt(startDate)}`,
    `DTEND:${fmt(endDate)}`,
    `DESCRIPTION:${(description || "").replace(/\n/g, "\\n")}`,
    `LOCATION:${(location || "").replace(/[\r\n]/g, " ")}`,
    `STATUS:CONFIRMED`,
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");

  const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${title.replace(/[^a-zA-Z0-9]/g, "_")}.ics`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Dropdown button component to add events to Google Calendar, Outlook, or Apple/Desktop iCal
export function AddToCalendar({ title, start, description = "", location = "", buttonText = "Add to Calendar" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const clickAway = (e) => {
      if (!ref.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", clickAway);
    return () => document.removeEventListener("mousedown", clickAway);
  }, [open]);

  if (!start) return null;

  const eventData = { title, start, description, location };

  return (
    <div className="add-to-cal-wrap" ref={ref} style={{ display: "inline-block", position: "relative" }}>
      <button
        type="button"
        className="sf-button add-to-cal-btn"
        style={{ height: 26, padding: "0 10px", fontSize: 12, gap: 4 }}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        title="Add to Google Calendar, Outlook, or download iCal"
      >
        <Icon name="event" size={13} />
        {buttonText}
        <Icon name="down" size={11} />
      </button>

      {open && (
        <ul
          className="menu-pop add-to-cal-menu"
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            zIndex: 100,
            marginTop: 4,
            minWidth: 160,
          }}
        >
          <li>
            <a
              href={googleCalendarUrl(eventData)}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setOpen(false)}
            >
              Google Calendar
            </a>
          </li>
          <li>
            <a
              href={outlookCalendarUrl(eventData)}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setOpen(false)}
            >
              Outlook (Web)
            </a>
          </li>
          <li>
            <button
              type="button"
              className="link"
              style={{ width: "100%", textAlign: "left" }}
              onClick={() => {
                downloadIcs(eventData);
                setOpen(false);
              }}
            >
              Download iCal (.ics)
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}
