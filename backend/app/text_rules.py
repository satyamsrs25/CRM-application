"""Which characters the CRM's text fields accept (values such as "...", "@@@", "<b>" or "Buyer1" were saved as they
were typed). The same rules run in the browser (frontend/src/domain.js, the *Problem functions).

- Person names (a lead's or contact's First / Last Name, a user's Full Name): letters in any language, with spaces,
  hyphens, apostrophes and dots ("Anne-Marie", "O'Neil", "D'Souza", "J. R.", "José", "प्रिया"). No digits or symbols.
- Company and account names: letters and digits in any language with the punctuation company names use
  ("AT&T", "Acme, Inc.", "Yahoo!", "E*Trade", "1-800-Flowers", "(Old) Acme"), starting with a letter or digit.
  At least one letter or digit is required (schemas.company_name_problem).
- Other text (Title, Industry, Location, Address, "Specify lead source"): any language and the usual punctuation, but
  no markup or code characters (< > { } [ ] \\ | ^ ~ `) and no control characters; Title and Industry need a letter.

New records are checked in full. An edit checks only the fields it changes, so an older record keeps its values and an
unrelated edit still saves (as for a lead's company name). Nothing stored is rewritten.
Uploads skip only rows whose company or last name is unusable ("...", "@@"), and leave out a Title, Industry or
Location with markup characters (listed as a warning).
"""
import unicodedata

from pydantic_core import PydanticCustomError

JOINERS = "\u200c\u200d"  # zero-width (non-)joiner: part of how some Indic and Persian words are written
NAME_PUNCTUATION = " .'’-" + JOINERS
COMPANY_PUNCTUATION = " &.,'’-()/+@!#:*_"
COMPANY_START = "(@'#"
TEXT_FORBIDDEN = set("<>{}[]\\|^~`")


def _kind(ch: str) -> str:
    return unicodedata.category(ch)[0]  # L letter, M mark (Indic vowel signs, accents), N number, C control...


def has_letter(text: str | None) -> bool:
    return any(_kind(ch) == "L" for ch in (text or ""))


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def person_name_problem(value, label: str) -> str:
    """"" when the name is fine (or empty: whether it is required is checked elsewhere), otherwise the message."""
    text = _text(value)
    if not text:
        return ""
    if has_letter(text) and all(_kind(ch) in "LM" or ch in NAME_PUNCTUATION for ch in text):
        return ""
    return f"Enter a valid {label}: letters only (spaces, hyphens, apostrophes and dots are fine)."


def company_characters_problem(value, what: str = "company name") -> str:
    """The company / account name's characters ("" when fine). Whether it has a letter or digit at all is
    schemas.company_name_problem's check (it runs first)."""
    text = _text(value)
    if not text:
        return ""
    bad = []
    for ch in text:
        if not (ch.isalnum() or _kind(ch) == "M" or ch in COMPANY_PUNCTUATION) and ch not in bad:
            bad.append(ch)
    if bad:
        return (f"The {what} can't contain {' '.join(bad)}. Use letters, numbers, spaces and "
                "& . , ' - ( ) / + @ ! # : * _ only.")
    if not (text[0].isalnum() or text[0] in COMPANY_START):
        return f"Start the {what} with a letter or number."
    return ""


def text_problem(value, label: str, *, letter: bool = True, multiline: bool = False) -> str:
    """Title, Industry, Location, Address...: "" when fine (or empty), otherwise the message."""
    text = _text(value)
    if not text:
        return ""
    allowed_controls = JOINERS + ("\n\r\t" if multiline else "")
    if any(ch in TEXT_FORBIDDEN or (_kind(ch) == "C" and ch not in allowed_controls) for ch in text):
        return f"The {label} can't contain < > {{ }} [ ] \\ | ^ ~ ` or special characters."
    if letter and not has_letter(text):
        return f"Enter a {label} with at least one letter."
    if not letter and not any(ch.isalnum() for ch in text):
        return f"Enter a {label} with at least one letter or number."
    return ""


def checked(problem, *args, keep_empty: bool = False, **kwargs):
    """A pydantic BeforeValidator: the value trimmed (empty -> None, or "" with keep_empty so a required field's
    own "required" message still shows), or the problem as a field error."""
    def validate(value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise PydanticCustomError("text_type", "Enter this as text.")
        message = problem(value, *args, **kwargs)
        if message:
            raise PydanticCustomError("text_invalid", message)
        text = value.strip()
        return text if (text or keep_empty) else None
    return validate
