"""LinkedIn profile autofill for the New Lead form and the contact forms (Apollo People Enrichment, see app/apollo.py).

Looks a profile up and returns the lead details found. Saves nothing and sends nothing: the user reviews the form
and saves the lead as usual. Same access as creating a lead: any signed-in user.
"""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import apollo
from app.schemas import linkedin_profile_url, valid_international_phone
from app.security import acting_user

router = APIRouter(prefix="/api/leads", tags=["Leads: LinkedIn autofill"])


class EnrichmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    linkedin_url: str = Field(..., min_length=1, max_length=300)


class EnrichmentOut(BaseModel):
    status: Literal["matched", "unverified", "no_match"]  # unverified: Apollo's LinkedIn URL missing/invalid/different
    linkedin_url: str  # the profile address in its saved form
    url_verified: bool = False  # true only when Apollo's returned LinkedIn URL is this same profile
    fields: dict[str, str] = {}  # first_name, last_name, company, title, industry, company_website,
    #                              company_linkedin_url, email, phone: only those found
    unavailable: dict[str, str] = {}  # the other fields, with the reason they are empty
    message: str | None = None
    cached: bool = False  # answered from this user's recent lookups (no new Apollo request)


@router.get("/enrichment")
def enrichment_status():
    """Whether LinkedIn autofill is available (an Apollo API key is set on the server). The key is never returned."""
    acting_user()
    return {"enabled": apollo.enabled()}


@router.post("/enrichment", response_model=EnrichmentOut)
async def enrich_lead(data: EnrichmentRequest):
    """Looks up a LinkedIn profile (linkedin.com/in/...) in Apollo for the New Lead form."""
    me = acting_user()
    try:
        url = linkedin_profile_url(data.linkedin_url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return await apollo.enrich(me.id, url)


# ---------- New Contact and New Opportunity > New contact ----------
# The same lookup (the same Apollo request, verification, work-email rule, cache and rate limit, and the same access:
# any signed-in user, who can also add contacts), answered with the person's contact details only. The company is
# never filled or changed: Apollo's current employer is only compared with the account the user chose.

contacts_router = APIRouter(prefix="/api/contacts", tags=["Contacts: LinkedIn autofill"])
CONTACT_FIELDS = {"first_name": "first_name", "last_name": "last_name", "title": "job_title", "email": "email",
                  "phone": "phone"}  # Apollo's lead field -> the contact field


class ContactEnrichmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    linkedin_url: str = Field(..., min_length=1, max_length=300)
    company: str | None = Field(None, max_length=200)  # the account chosen on the form (compared, never changed)


class ContactEnrichmentOut(BaseModel):
    status: Literal["matched", "unverified", "no_match"]
    linkedin_url: str
    url_verified: bool = False
    fields: dict[str, str] = {}  # first_name, last_name, job_title, email, phone: only those found
    unavailable: dict[str, str] = {}  # the other contact fields, with the reason they are empty
    message: str | None = None
    cached: bool = False
    employer: str | None = None  # Apollo's current employer for the person, when it gave one
    employer_matches: bool | None = None  # None: no account chosen yet, or no employer to compare


@contacts_router.post("/enrichment", response_model=ContactEnrichmentOut)
async def enrich_contact(data: ContactEnrichmentRequest):
    """Looks up a LinkedIn profile in Apollo for a new contact. Saves nothing; fills only the person's details."""
    from app.routers.lead_files import company_key  # the duplicate check's company comparison

    me = acting_user()
    try:
        url = linkedin_profile_url(data.linkedin_url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    answer = await apollo.enrich(me.id, url)
    fields = {CONTACT_FIELDS[k]: v for k, v in answer["fields"].items() if k in CONTACT_FIELDS}
    unavailable = {CONTACT_FIELDS[k]: v for k, v in answer["unavailable"].items() if k in CONTACT_FIELDS}
    if "phone" in fields:  # only a valid number with its country code reaches the form; anything else stays out
        phone = valid_international_phone(fields["phone"])
        if phone:
            fields["phone"] = phone
        else:
            del fields["phone"]
            unavailable["phone"] = "Apollo's number isn't a valid phone number with its country code, so it was not used"
    out = {**answer, "fields": fields, "unavailable": unavailable}
    if answer["status"] == "matched" and not fields:
        out |= {"status": "no_match", "url_verified": False, "unavailable": {},
                "message": "Apollo matched the profile but returned no contact details."}
    employer = answer["fields"].get("company") if out["status"] == "matched" else None
    chosen = company_key(data.company)
    out["employer"] = employer
    out["employer_matches"] = (company_key(employer) == chosen) if employer and chosen else None
    return out
