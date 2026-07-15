import re


_HINDI_HOURS = {
    1: "एक",
    2: "दो",
    3: "तीन",
    4: "चार",
    5: "पाँच",
    6: "छह",
    7: "सात",
    8: "आठ",
    9: "नौ",
    10: "दस",
    11: "ग्यारह",
    12: "बारह",
}
_HINDI_MINUTES = {
    0: "",
    15: "पंद्रह मिनट",
    30: "तीस मिनट",
    45: "पैंतालीस मिनट",
}
_TIME_PATTERN = re.compile(
    r"\b(1[0-2]|0?[1-9]):([0-5]\d)\s*(AM|PM)\b",
    re.IGNORECASE,
)
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^\s)]+\)")


def _expand_time(match: re.Match[str]) -> str:
    hour = int(match.group(1))
    minute = int(match.group(2))
    period = match.group(3).upper()
    if minute not in _HINDI_MINUTES:
        return match.group(0)

    day_part = "सुबह" if period == "AM" else "शाम"
    spoken = f"{day_part} {_HINDI_HOURS[hour]} बजे"
    if minute:
        spoken = (
            f"{day_part} {_HINDI_HOURS[hour]} बजकर "
            f"{_HINDI_MINUTES[minute]}"
        )
    return spoken


def prepare_text_for_speech(text: str, *, max_chars: int = 500) -> str:
    """Prepare display text for speech without changing the displayed value."""
    if not isinstance(text, str):
        raise TypeError("Speech text must be a string.")
    if max_chars < 1:
        raise ValueError("max_chars must be positive.")

    spoken = _MARKDOWN_LINK.sub(r"\1", text)
    spoken = re.sub(r"[`*_~#>]", "", spoken)
    spoken = re.sub(r"\bmeeting\b", "मीटिंग", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\bAI\b", "ए आई", spoken, flags=re.IGNORECASE)
    spoken = _TIME_PATTERN.sub(_expand_time, spoken)
    spoken = re.sub(r"([!?।,.])\1+", r"\1", spoken)
    spoken = re.sub(r"\s+", " ", spoken).strip()

    if len(spoken) > max_chars:
        shortened = spoken[:max_chars].rstrip()
        boundary = max(
            shortened.rfind("।"),
            shortened.rfind("?"),
            shortened.rfind("!"),
        )
        if boundary >= max_chars // 2:
            shortened = shortened[: boundary + 1]
        else:
            shortened = shortened.rsplit(" ", 1)[0].rstrip(" ,.;:")
        spoken = shortened

    if spoken and spoken[-1] not in "।.!?":
        spoken = f"{spoken}।"
    return spoken
