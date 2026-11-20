"""Region: the country chosen beside a lead's or contact's phone (leads.phone_country, contacts.phone_country).

Region means the country, not a state, province or sales territory. It is a two-letter code (IN, US, CA...) from the
phone's country list (Google's libphonenumber regions, the same list as the form's libphonenumber-js), shown by name
("India"). The rules:
- It is saved only when it was chosen: on the form, picking a country or entering a number for it; through the API,
  sending phone_country. Nothing is guessed from a number's digits, and older records keep an empty Region.
- Countries that share a calling code (+1: the United States, Canada, Jamaica...; +44: the United Kingdom, Guernsey...)
  stay distinct: the list names one country, so the choice says which one. A bare "+1" never picks a country.
- The phone stays optional: a Region can be saved without a number, and clearing the number keeps the Region.
- With a Region chosen, the number must be valid in that country's own numbering plan, typed with or without its
  +code (phone_region_problem): a +1 number can't be saved with Region India, and a Toronto number can't be saved with
  Region United States. Shared numbers (+1 toll-free) count for every +1 country. Without a Region, a number without
  + is checked for India (the form's default) and one with + for its own code, as before.
"""
from functools import lru_cache

from pydantic_core import PydanticCustomError

REGION_INVALID = "Choose the phone number's country."
# libphonenumber has no English name for these few regions (its geocoder only names countries with example numbers)
NAME_FALLBACK = {"AC": "Ascension Island", "BL": "Saint Barthélemy", "EH": "Western Sahara", "MF": "Saint Martin",
                 "TA": "Tristan da Cunha", "XK": "Kosovo"}


@lru_cache(maxsize=1)
def _names() -> dict[str, str]:
    import phonenumbers
    from phonenumbers import geocoder

    names = {}
    for region in phonenumbers.SUPPORTED_REGIONS:
        example = phonenumbers.example_number(region)
        name = geocoder.country_name_for_number(example, "en") if example else ""
        names[region] = name or NAME_FALLBACK.get(region, region)
    return names


def supported(code: str | None) -> bool:
    return bool(code) and code.upper() in _names()


def country_name(code: str | None) -> str | None:
    """'IN' -> 'India'; None for an empty or unknown code."""
    return _names().get(code.upper()) if code else None


def calling_code(code: str) -> int:
    import phonenumbers

    return phonenumbers.country_code_for_region(code.upper())


def region_code(value) -> str | None:
    """A Region sent to the API: a supported two-letter code, upper-cased; empty -> None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise PydanticCustomError("phone_country", REGION_INVALID)
    text = value.strip().upper()
    if not text:
        return None
    if not supported(text):
        raise PydanticCustomError("phone_country", REGION_INVALID)
    return text


def phone_region_problem(phone: str | None, region: str | None) -> str:
    """"" unless a number given with its own +code doesn't belong to the chosen Region. Two checks, in this order:
    - calling code: +44 can't be saved with Region India (+91);
    - the Region's own numbering plan (Google libphonenumber's is_valid_number_for_region, the same check a number
      typed without + gets for the chosen country): +1 416 555 0142 is a Canadian number, so it isn't saved with Region
      United States, while a shared +1 toll-free number (800, 888...) is valid for the United States, Canada and
      Jamaica alike. The country comes from libphonenumber's per-country patterns, never from a +1 -> US mapping.
    A number without + was already checked for the Region itself; an unreadable one is the phone check's to report."""
    import phonenumbers

    text = (phone or "").strip()
    if not region or not text.startswith("+"):
        return ""
    try:
        number = phonenumbers.parse(text, None)
    except phonenumbers.NumberParseException:
        return ""
    wanted = calling_code(region)
    if number.country_code != wanted:
        return (f"This number's country code is +{number.country_code}, but the Region is {country_name(region)} "
                f"(+{wanted}). Choose the number's country.")
    if phonenumbers.is_valid_number(number) and not phonenumbers.is_valid_number_for_region(number, region.upper()):
        return (f"This number isn't valid for the Region, {country_name(region)} (+{wanted}). "
                "Choose the number's country.")
    return ""


@lru_cache(maxsize=1)
def _by_name() -> dict[str, str]:
    return {name.casefold(): code for code, name in _names().items()}


def region_from_text(value: str | None) -> tuple[str | None, str]:
    """A Region from a file's cell: (code, "") when it names one country: a two-letter code (IN), an English country
    name (India) or a calling code only one country uses (+91). (None, why) for a calling code that several countries
    share (+1), and (None, "") for anything else (e.g. a state or territory, which older files may call Region)."""
    import phonenumbers

    text = " ".join((value or "").split())
    if not text:
        return None, ""
    if len(text) == 2 and supported(text):
        return text.upper(), ""
    digits = text.lstrip("+").replace(" ", "")
    if text.startswith("+") or digits.isdigit():
        if not digits.isdigit():
            return None, ""
        regions = [r for r in phonenumbers.region_codes_for_country_code(int(digits)) if supported(r)]
        if len(regions) == 1:
            return regions[0], ""
        if len(regions) > 1:
            return None, f"+{digits} is shared by several countries ({', '.join(sorted(regions)[:5])}...)"
        return None, ""
    return _by_name().get(text.casefold()), ""
