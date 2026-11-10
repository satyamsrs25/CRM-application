// "Add to Calendar" next to a lead's demo date: Google Calendar, Outlook on the web (Microsoft 365) or an .ics file.
// The links and the file are built in calendarLinks.js; nothing is synchronised and no invitation is sent.
import React, { useEffect, useId, useRef, useState } from "react";
import { googleCalendarUrl, icsContent, outlookCalendarUrl } from "./calendarLinks";
import { Icon } from "./ui";

function downloadIcs(event) {
  const url = URL.createObjectURL(new Blob([icsContent(event)], { type: "text/calendar;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = event.fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// A menu button: opens on the first choice; arrow keys, Home and End move; Esc closes it and returns to the button;
// Tab or a click elsewhere closes it.
export function AddToCalendar({ event, buttonText = "Add to Calendar" }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef(null);
  const button = useRef(null);
  const menu = useRef(null);
  const id = useId();

  useEffect(() => {
    if (!open) return undefined;
    const items = () => [...(menu.current?.querySelectorAll('[role="menuitem"]') || [])];
    items()[0]?.focus();
    const away = (e) => !wrap.current?.contains(e.target) && setOpen(false);
    const key = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
        button.current?.focus();
        return;
      }
      if (e.key === "Tab") return setOpen(false);
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      const list = items();
      const at = list.indexOf(document.activeElement);
      const next =
        e.key === "Home" ? 0 : e.key === "End" ? list.length - 1 : (at + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length;
      list[next]?.focus();
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  if (!event) return null;
  const close = () => setOpen(false);

  return (
    <div className="add-to-cal" ref={wrap}>
      <button
        ref={button}
        type="button"
        className="sf-button add-to-cal-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={`${id}-menu`}
        onClick={() => setOpen((o) => !o)}
        title="Add to Google Calendar or Outlook, or download an .ics file"
      >
        <Icon name="calendar" size={13} />
        {buttonText}
        <Icon name="down" size={11} />
      </button>
      {open && (
        <div id={`${id}-menu`} className="menu-pop add-to-cal-menu" role="menu" aria-label="Add the demo to a calendar" ref={menu}>
          <a role="menuitem" href={googleCalendarUrl(event)} target="_blank" rel="noopener noreferrer" onClick={close}>
            Google Calendar
          </a>
          <a role="menuitem" href={outlookCalendarUrl(event)} target="_blank" rel="noopener noreferrer" onClick={close}>
            Outlook (Microsoft 365)
          </a>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              downloadIcs(event);
              close();
              button.current?.focus();
            }}
          >
            Download .ics file
          </button>
        </div>
      )}
    </div>
  );
}
