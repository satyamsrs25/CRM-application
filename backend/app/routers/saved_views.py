"""Saved list views: a user's own named views of the Opportunities and Leads lists (Save as View), next to the built-in
ones.

A view keeps the built-in view it starts from (its scope: "My Open Opportunities" stays the user's own open deals), the
filter choices, the search and the sort. Dates are kept as choices ("This month", "Last week"), so they stay dynamic.
Only the user who saved a view can list, update, rename or delete it (anyone else gets 404). A view belongs to one list
(its collection) for good: it is listed, updated and checked only as that list's view, so a Leads view can never
replace an Opportunities view or the other way round. A view never widens what the list shows: the records always come
from the permission-checked lists, and the owners a view names are checked against the user's access again each time it
is read; any no longer allowed are left out (adjusted).
"""
import json
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import CURRENCIES, LEAD_SOURCES, LEAD_STAGES, OPPORTUNITY_STAGES
from app.database import get_db
from app.models import SavedView, User
from app.regions import supported
from app.routers.lead_files import CLOCK_SORT, SORTS as LEAD_SORTS
from app.security import acting_user

router = APIRouter(prefix="/api/saved-views", tags=["Saved views"])

# the built-in views (frontend ListView.jsx views() and LEAD_VIEWS): a saved view starts from one of them
OPPORTUNITY_VIEWS = ("All Opportunities", "My Opportunities", "My Open Opportunities", "My Won Opportunities",
                     "My Lost Opportunities", "Open Opportunities", "Won Opportunities", "Lost Opportunities")
LEAD_VIEWS = ("All Open Leads", "My Open Leads", "All Leads", "My Leads", "Unassigned Leads", "Converted Leads",
              "Lost Leads", "Unqualified Leads", "Revisit Due", "Uploaded Leads", "My Uploaded Leads", "Invalid Emails",
              "Unsubscribed Leads", "Working Emails", "No Email")  # not Deleted Leads (no filters there)
# the Opportunities list's columns (sortable) and the filter choices the pages offer (frontend listHelpers.js)
SORT_COLUMNS = ("Opportunity Name", "Client POC", "Account Name", "Amount", "Close Date", "Stage", "In stage", "Owner",
                "Created", "Last Modified")
IN_STAGE = ("on_track", "attention", "stalled")
PAST_RANGES = ("today", "week", "last7", "last30", "month", "quarter", "year", "custom")
FUTURE_RANGES = ("overdue", "today", "week", "next7", "next30", "month", "quarter", "custom")
LEAD_RANGES = ("today", "lastweek", "lastmonth", "custom")
POOL_OWNER = "unassigned"
REGION_NONE = "none"
MAX_VIEWS = 50
MAX_OWNERS = 50

# per list: its built-in views, choices, date filters, whether Owner may name the Unassigned Pool, and its sort
SPECS = {
    "opportunities": {
        "noun": "opportunities", "views": OPPORTUNITY_VIEWS,
        "choices": {"stage": OPPORTUNITY_STAGES, "in_stage": IN_STAGE, "currency": CURRENCIES, "overdue_stuck": ("1",)},
        "dates": {"close": FUTURE_RANGES, "created": PAST_RANGES, "modified": PAST_RANGES},
        "pool": False, "region": False,
        "sort_columns": SORT_COLUMNS, "directions": (1, -1), "default_sort": {"column": "Opportunity Name", "dir": 1},
    },
    "leads": {
        "noun": "leads", "views": LEAD_VIEWS,
        "choices": {"stage": LEAD_STAGES, "in_stage": IN_STAGE, "source": LEAD_SOURCES},
        "dates": {"created": LEAD_RANGES, "modified": LEAD_RANGES},
        "pool": True, "region": True,
        "sort_columns": (*LEAD_SORTS, CLOCK_SORT), "directions": ("asc", "desc"),
        "default_sort": {"column": "created", "dir": "desc"},
    },
}


class SavedViewIn(BaseModel):
    collection: str = "opportunities"
    name: str = Field(..., max_length=200)
    base_view: str = Field(..., max_length=60)
    filters: dict[str, str] = Field(default_factory=dict)
    search: str | None = Field(None, max_length=100)
    sort: dict | None = None


class SavedViewChange(BaseModel):
    """Rename (name) and/or Update View (filters, search and sort: all three, as the list is now). collection: the
    list the change comes from; it must be the view's own."""
    collection: str | None = None
    name: str | None = Field(None, max_length=200)
    filters: dict[str, str] | None = None
    search: str | None = Field(None, max_length=100)
    sort: dict | None = None


def problem(detail: str):
    raise HTTPException(status_code=400, detail=detail)


def owner_scope(db: Session, me) -> set[int] | None:
    """Whose records this user may filter by: everyone's with View team records (None = any user), else only their
    own."""
    return None if me.sees_team else {me.id}


def clean_filters(db: Session, me, raw: dict, base_view: str, strict: bool, collection: str = "opportunities") -> tuple[dict, bool]:
    """The filter choices, checked. strict (saving): anything not allowed is refused (400). Reading a saved view: what
    is no longer allowed (an owner outside the user's access now, a choice the page doesn't offer) is left out, and
    adjusted says so."""
    spec = SPECS[collection]
    out, adjusted = {}, False

    def drop(detail):
        nonlocal adjusted
        if strict:
            problem(detail)
        adjusted = True

    for key, value in raw.items():
        value = str(value).strip()
        if not value:
            continue
        if key in spec["choices"]:
            if value in spec["choices"][key]:
                out[key] = value
            else:
                drop(f"'{value}' isn't a choice for {key}")
        elif key == "region" and spec["region"]:
            if value.lower() == REGION_NONE or (len(value) == 2 and supported(value)):
                out[key] = value.lower() if value.lower() == REGION_NONE else value.upper()
            else:
                drop(f"'{value}' isn't a Region")
        elif key in spec["dates"]:
            if value not in spec["dates"][key]:
                drop(f"'{value}' isn't a date choice for {key}")
                continue
            out[key] = value
            if value == "custom":
                days = {}
                for end in ("from", "to"):
                    text = str(raw.get(f"{key}_{end}") or "").strip()
                    if not text:
                        continue
                    try:
                        days[end] = date.fromisoformat(text)
                    except ValueError:
                        drop(f"{key}: '{text}' isn't a date (yyyy-mm-dd)")
                        continue
                    out[f"{key}_{end}"] = days[end].isoformat()
                if not days:
                    drop(f"{key}: a custom range needs a From or a To date")
                    out.pop(key, None)
                elif len(days) == 2 and days["from"] > days["to"]:
                    drop(f"{key}: From can't be after To")
                    for end in ("", "_from", "_to"):
                        out.pop(f"{key}{end}", None)
        elif key.endswith(("_from", "_to")) and key.rsplit("_", 1)[0] in spec["dates"]:
            if raw.get(key.rsplit("_", 1)[0]) != "custom":
                drop(f"{key} goes only with a custom range")
        elif key == "owner":
            choices = value.split(",")
            if len(choices) > MAX_OWNERS or not all(c.isdigit() and len(c) <= 9 or (spec["pool"] and c == POOL_OWNER)
                                                    for c in choices):
                drop("Owner: choose people from the list")
                continue
            if base_view.startswith("My ") or base_view == "Unassigned Leads":
                drop(f"Owner isn't a filter on this view (it shows only your {spec['noun']} or the Unassigned Pool)")
                continue
            ids = list(dict.fromkeys(int(c) for c in choices if c != POOL_OWNER))
            existing = set(db.scalars(select(User.id).where(User.id.in_(ids))).all()) if ids else set()
            scope = owner_scope(db, me)
            allowed = [str(i) for i in ids if i in existing and (scope is None or i in scope)]
            if len(allowed) != len(ids):
                drop(f"Owner: you can only choose people whose {spec['noun']} you can see")
            if POOL_OWNER in choices:  # the Unassigned Pool: every user can list it (the list decides what it shows)
                allowed.append(POOL_OWNER)
            if allowed:
                out[key] = ",".join(allowed)
        else:
            drop(f"'{key}' isn't a filter on this list")
    return out, adjusted


def clean_sort(sort: dict | None, strict: bool, collection: str = "opportunities") -> dict:
    spec = SPECS[collection]
    if not sort:
        return dict(spec["default_sort"])
    ok = (sort.get("column") in spec["sort_columns"] and sort.get("dir") in spec["directions"]
          and not isinstance(sort.get("dir"), bool))
    if not ok and strict:
        problem("Sort: choose a column of the list and its direction")
    return {"column": sort["column"], "dir": sort["dir"]} if ok else dict(spec["default_sort"])


def clean_name(db: Session, me, name: str, collection: str, view_id: int | None = None) -> str:
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        problem("Enter a name for the view")
    if len(name) > 60:
        problem("The view's name can be up to 60 characters")
    if re.search(r"[\x00-\x1f<>]", name):
        problem("The view's name can't contain < or > or control characters")
    if name.lower() in {v.lower() for v in SPECS[collection]["views"]}:
        problem(f"'{name}' is a standard view. Choose another name")
    taken = select(SavedView.id).where(SavedView.user_id == me.id, SavedView.collection == collection,
                                       func.lower(SavedView.name) == name.lower())
    if view_id is not None:
        taken = taken.where(SavedView.id != view_id)
    if db.scalar(taken) is not None:
        problem(f"You already have a view called '{name}'")
    return name


def check_collection(collection: str) -> str:
    if collection not in SPECS:
        problem("Views can be saved for the Opportunities and Leads lists")
    return collection


def view_out(db: Session, me, v: SavedView) -> dict:
    spec = SPECS.get(v.collection, SPECS["opportunities"])
    base = v.base_view if v.base_view in spec["views"] else spec["views"][0]
    try:
        raw = json.loads(v.filters or "{}")
    except ValueError:
        raw = {}
    filters, adjusted = clean_filters(db, me, raw if isinstance(raw, dict) else {}, base, strict=False,
                                      collection=v.collection)
    try:
        sort = json.loads(v.sort) if v.sort else None
    except ValueError:
        sort = None
    return {"id": v.id, "name": v.name, "collection": v.collection, "base_view": base, "filters": filters,
            "search": v.search or "",
            "sort": clean_sort(sort if isinstance(sort, dict) else None, strict=False, collection=v.collection),
            "adjusted": adjusted or base != v.base_view, "created_at": v.created_at, "updated_at": v.updated_at}


def own_view(db: Session, me, view_id: int, collection: str | None = None) -> SavedView:
    view = db.get(SavedView, view_id)
    # someone else's view, or another list's, looks like it doesn't exist
    if view is None or view.user_id != me.id or (collection is not None and view.collection != collection):
        raise HTTPException(status_code=404, detail="This view doesn't exist or isn't yours")
    return view


@router.get("")
def list_views(collection: str = Query("opportunities"), db: Session = Depends(get_db)):
    """Your own saved views of a list, by name (each checked against your access now)."""
    me = acting_user()
    check_collection(collection)
    views = db.scalars(select(SavedView).where(SavedView.user_id == me.id, SavedView.collection == collection)
                       .order_by(func.lower(SavedView.name))).all()
    return [view_out(db, me, v) for v in views]


@router.post("", status_code=201)
def create_view(data: SavedViewIn, db: Session = Depends(get_db)):
    """Save the list's current filters, search and sort as your own named view."""
    me = acting_user()
    collection = check_collection(data.collection)
    if data.base_view not in SPECS[collection]["views"]:
        problem(f"Start from a standard view: {', '.join(SPECS[collection]['views'])}")
    count = db.scalar(select(func.count()).select_from(SavedView)
                      .where(SavedView.user_id == me.id, SavedView.collection == collection))
    if count >= MAX_VIEWS:
        problem(f"You can keep up to {MAX_VIEWS} views. Delete one you no longer use first")
    name = clean_name(db, me, data.name, collection)
    filters, _ = clean_filters(db, me, data.filters, data.base_view, strict=True, collection=collection)
    view = SavedView(user_id=me.id, collection=collection, name=name, base_view=data.base_view,
                     filters=json.dumps(filters), search=(data.search or "").strip() or None,
                     sort=json.dumps(clean_sort(data.sort, strict=True, collection=collection)))
    db.add(view)
    db.commit()
    db.refresh(view)
    return view_out(db, me, view)


@router.patch("/{view_id}")
def change_view(view_id: int, data: SavedViewChange, db: Session = Depends(get_db)):
    """Rename one of your views, or Update View: save the list's current filters, search and sort into it (its list and
    its standard view stay as they are). Checked like a new view."""
    me = acting_user()
    view = own_view(db, me, view_id, data.collection)
    if data.name is None and data.filters is None:
        problem("Send a new name, or the filters, search and sort to save")
    if data.name is not None:
        view.name = clean_name(db, me, data.name, view.collection, view.id)
    if data.filters is not None:
        filters, _ = clean_filters(db, me, data.filters, view.base_view, strict=True, collection=view.collection)
        view.filters = json.dumps(filters)
        view.search = (data.search or "").strip() or None
        view.sort = json.dumps(clean_sort(data.sort, strict=True, collection=view.collection))
    db.commit()
    db.refresh(view)
    return view_out(db, me, view)


@router.delete("/{view_id}")
def delete_view(view_id: int, collection: str | None = Query(None), db: Session = Depends(get_db)):
    """Delete one of your views (the built-in views can't be deleted; nothing else changes). Answers with JSON, as
    every API here does (the app treats an empty answer as an unreachable API)."""
    me = acting_user()
    db.delete(own_view(db, me, view_id, collection))
    db.commit()
    return {"deleted": view_id}
