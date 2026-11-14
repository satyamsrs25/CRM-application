// Leads table: long values (name, company, title, email, owner) stay on one line and end in "…", so rows
// stay compact. The full value opens in one floating preview for the whole table:
// - hover the cell (the preview stays while the pointer is on it, so its text can be selected and copied);
// - keyboard: focus the name or email link, or the ⋯ button of a cut-off company, title or owner;
// - touch: tap ⋯ (shown on every cut-off value); tap it again, or anywhere else, to close.
// Escape, scrolling and resizing close it, and it is placed inside the viewport. Phone numbers are never shown here
// (the Phone column keeps its own eye button).
import React, { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { previewPlacement } from "./listHelpers";

export const PREVIEW_ID = "leads-cell-preview";
const SHOW_DELAY = 250; // hover: a pointer passing over the table doesn't open previews
const HIDE_DELAY = 150; // time to move the pointer from the cell onto the preview

// What a cell's preview shows, or null when the value fits and has no note (nothing to show)
function contentOf(line, pinned) {
  if (!line?.isConnected || !(line.hasAttribute("data-cut") || line.dataset.note)) return null;
  return { line, text: line.dataset.full || "", note: line.dataset.note || "", pinned };
}

// Marks the cells whose value doesn't fit (data-cut): their ⋯ button shows, and hovering them opens the preview.
// All marks are removed first and then measured in one pass (one layout, not one per cell).
export function markCutCells(root) {
  if (!root) return;
  const lines = [...root.querySelectorAll(".cell-line")];
  for (const line of lines) line.removeAttribute("data-cut");
  const cut = lines.filter((line) => {
    const value = line.firstElementChild;
    return value && value.scrollWidth > value.clientWidth + 1;
  });
  for (const line of cut) line.setAttribute("data-cut", "");
}

// The table's one preview. Cells call hover / focus / leave / toggle with their .cell-line element; opening one
// doesn't re-render the table.
export const CellPreview = forwardRef(function CellPreview(_, ref) {
  const [open, setOpen] = useState(null); // { line, text, note, pinned }
  const box = useRef(null);
  const timer = useRef(0);
  const later = (next, delay) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(next, delay);
  };
  const close = () => {
    clearTimeout(timer.current);
    setOpen(null);
  };
  useImperativeHandle(ref, () => ({
    hover: (line) => later(() => setOpen((now) => (now?.pinned ? now : contentOf(line, false))), SHOW_DELAY),
    focus: (line) => {
      clearTimeout(timer.current);
      setOpen((now) => (now?.pinned && now.line === line ? now : contentOf(line, false)));
    },
    leave: (line) => later(() => setOpen((now) => (now && !now.pinned && now.line === line ? null : now)), HIDE_DELAY),
    toggle: (line) => {
      clearTimeout(timer.current);
      setOpen((now) => (now?.pinned && now.line === line ? null : contentOf(line, true)));
    },
    close,
  }));
  useEffect(() => () => clearTimeout(timer.current), []);

  // placed under the cell (above it when there's no room), inside the viewport, before it is painted
  useLayoutEffect(() => {
    if (!open || !box.current) return;
    const anchor = open.line.getBoundingClientRect();
    const size = box.current.getBoundingClientRect();
    const { top, left } = previewPlacement(anchor, size, { width: window.innerWidth, height: window.innerHeight });
    box.current.style.top = `${top}px`;
    box.current.style.left = `${left}px`;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    // the cell's link and ⋯ button are described by the preview while it is open
    const triggers = [...open.line.querySelectorAll("a, button")];
    for (const el of triggers) el.setAttribute("aria-describedby", PREVIEW_ID);
    const more = open.line.querySelector(".cell-more");
    more?.setAttribute("aria-expanded", "true");
    // an event's target may be the window (not an element): then it is outside the preview and the cell
    const within = (root, target) => target instanceof Node && !!root?.contains(target);
    const onKey = (event) => event.key === "Escape" && close();
    const onScroll = (event) => !within(box.current, event.target) && close();
    const onDown = (event) => !within(box.current, event.target) && !within(open.line, event.target) && close();
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", close);
    return () => {
      for (const el of triggers) el.removeAttribute("aria-describedby");
      more?.setAttribute("aria-expanded", "false");
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  if (!open) return null;
  return createPortal(
    <div
      ref={box}
      id={PREVIEW_ID}
      role="tooltip"
      className="cell-preview"
      style={{ top: 0, left: 0 }}
      onMouseEnter={() => clearTimeout(timer.current)}
      onMouseLeave={() => !open.pinned && later(close, HIDE_DELAY)}
    >
      {open.text}
      {open.note && <small>{open.note}</small>}
    </div>,
    document.body,
  );
});

// A Leads table cell with a value that may not fit: the value (a link when href is given) and the ⋯ button.
// preview: a ref to the table's CellPreview; label: what the value is, for the button ("name", "company"...);
// note: extra text for the preview (an email's status), which also makes the ⋯ button show.
export function PreviewCell({ preview, value, label, href, linkClass = "", note = "", className = "" }) {
  if (!value) return <td className={`cell ${className}`} />;
  const lineOf = (event) => event.currentTarget.closest(".cell-line");
  const focusProps = {
    onFocus: (event) => preview.current?.focus(lineOf(event)),
    onBlur: (event) => preview.current?.leave(lineOf(event)),
  };
  return (
    <td className={`cell ${className}`}>
      <div
        className="cell-line"
        data-full={value}
        data-note={note || undefined}
        onMouseEnter={(event) => preview.current?.hover(event.currentTarget)}
        onMouseLeave={(event) => preview.current?.leave(event.currentTarget)}
      >
        {href ? (
          <a className={`cell-value ${linkClass}`.trim()} href={href} {...focusProps}>
            {value}
          </a>
        ) : (
          <span className="cell-value">{value}</span>
        )}
        {/* the link itself opens the preview from the keyboard, so its ⋯ is for pointer and touch only */}
        <button
          type="button"
          className="cell-more"
          tabIndex={href ? -1 : undefined}
          aria-label={`Show full ${label}`}
          aria-expanded="false"
          {...focusProps}
          onClick={(event) => preview.current?.toggle(lineOf(event))}
        >
          <span aria-hidden="true">⋯</span>
        </button>
      </div>
    </td>
  );
}
