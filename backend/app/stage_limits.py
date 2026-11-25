"""In stage limits the Admin changes (Leads and Opportunities, each its own setting): reading them and saving them.

Each kind keeps its defaults in app/stage_clock.py (STAGE_DAYS for lead statuses, OPPORTUNITY_STAGE_DAYS for open
opportunity stages) and its own app_settings row, so changing one never changes the other. Whole days, 0 <= needs
attention < stalled <= MAX_LIMIT_DAYS. A stage sent as null (or left out) goes back to its default; values equal to
the default aren't kept as custom. Every change is in the Admin's Activity Log.
"""
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, StrictInt
from sqlalchemy.orm import Session

from app.models import AppSetting, User
from app.security import acting_user
from app.services import log_activity
from app.stage_clock import (LEAD_LIMITS_SETTING, MAX_LIMIT_DAYS, OPPORTUNITY_LIMITS_SETTING, OPPORTUNITY_STAGE_DAYS,
                             STAGE_DAYS, custom_limits, valid_limit)

# kind -> (app_settings key, defaults, Activity Log target, Activity Log action)
KINDS = {
    "opportunity": (OPPORTUNITY_LIMITS_SETTING, OPPORTUNITY_STAGE_DAYS, "Opportunities", "In stage limits changed"),
    "lead": (LEAD_LIMITS_SETTING, STAGE_DAYS, "Leads", "Lead In stage limits changed"),
}


class StageLimitsIn(BaseModel):
    # a rated stage -> [needs attention at, stalled at] in whole days; null or left out: the default
    limits: dict[str, list[StrictInt] | None]


def limits_out(db: Session, kind: str) -> dict:
    setting, defaults, _, _ = KINDS[kind]
    row = db.get(AppSetting, setting)
    who = db.get(User, row.updated_by_id) if row and row.updated_by_id else None
    custom = custom_limits(db, setting, defaults)
    return {"limits": {stage: list(pair) for stage, pair in {**defaults, **custom}.items()},
            "defaults": {stage: list(pair) for stage, pair in defaults.items()},
            "custom": sorted(custom), "max_days": MAX_LIMIT_DAYS,
            "updated_by": who.full_name if who else None, "updated_at": row.updated_at if row else None}


def save_limits(db: Session, kind: str, data: StageLimitsIn) -> dict:
    """The Admin changes one kind's limits; nothing is saved on the records: the ratings follow at once."""
    setting, defaults, target, action = KINDS[kind]
    me = acting_user()
    if not me.is_admin:
        raise HTTPException(status_code=403, detail="Only the Admin can change the In stage limits")
    saved = {}
    for stage, pair in data.limits.items():
        if stage not in defaults:
            raise HTTPException(status_code=400, detail=f"'{stage}' has no limits. Use: {', '.join(defaults)}")
        if pair is None:
            continue
        if not valid_limit(pair):
            raise HTTPException(status_code=400, detail=f"{stage}: Needs attention must be 0 or more and less than Stalled, "
                                                        f"and Stalled at most {MAX_LIMIT_DAYS} days")
        if tuple(pair) != defaults[stage]:
            saved[stage] = list(pair)
    row = db.get(AppSetting, setting) or AppSetting(key=setting)
    row.value, row.updated_by_id, row.updated_at = json.dumps(saved), me.id, datetime.now(timezone.utc)
    db.add(row)
    effective = {**defaults, **{s: tuple(p) for s, p in saved.items()}}
    log_activity(db, me.id, action, target,
                 "; ".join(f"{s}: needs attention at {a} days, stalled at {b}" for s, (a, b) in effective.items()))
    db.commit()
    return limits_out(db, kind)
