import re

from app.core.redact import redact

UUID_REGEX = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

TIMESTAMP_REGEX = re.compile(
    r"(?:\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
    r"|(?:\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
    r"|(?:\b\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}\s+[+-]\d{4}\b)"
)

IPV6_REGEX = re.compile(
    r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"
    r"|\b(?:[0-9a-fA-F]{1,4}:){1,7}:[0-9a-fA-F]{1,4}\b"
    r"|\b::(?:[0-9a-fA-F]{1,4}:){0,6}[0-9a-fA-F]{1,4}\b"
)
IPV4_REGEX = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

HEX_REGEX = re.compile(r"\b(?:0x)?[0-9a-fA-F]{8,}\b")


def _replace_numbers_preserve_http_status(text: str) -> str:
    """
    Replace numbers with <n>, EXCEPT HTTP status codes matching \\b[1-5]\\d\\d\\b
    when the preceding word is one of http, status, code, error, or preceded by HTTP/.
    """
    pattern = re.compile(
        r"(?P<prefix>\b(?:http|status|code|error)\s+|HTTP/)(?P<http_code>[1-5]\d\d)\b|(?P<other_num>\d+)",
        re.IGNORECASE
    )

    def repl(m: re.Match) -> str:
        if m.group("http_code"):
            return f"{m.group('prefix')}{m.group('http_code')}"
        elif m.group("other_num"):
            return "<n>"
        return m.group(0)

    return pattern.sub(repl, text)


def normalize_text(s: str) -> str:
    """
    Normalize text in order:
    1. Redact secrets (redact())
    2. Replace UUIDs with <uuid>
    3. Replace timestamps with <ts>
    4. Replace IP addresses with <ip>
    5. Replace hex strings (>= 8 chars) with <hex>
    6. Replace numbers with <n> (preserving HTTP status codes)
    7. Collapse whitespace and strip
    """
    if not s:
        return ""

    # 1. Redact secrets
    s = redact(s)

    # 2. Replace UUIDs
    s = UUID_REGEX.sub("<uuid>", s)

    # 3. Replace Timestamps
    s = TIMESTAMP_REGEX.sub("<ts>", s)

    # 4. Replace IP addresses
    s = IPV6_REGEX.sub("<ip>", s)
    s = IPV4_REGEX.sub("<ip>", s)

    # 5. Replace Hex strings (>= 8 chars)
    s = HEX_REGEX.sub("<hex>", s)

    # 6. Replace Numbers (preserving HTTP status)
    s = _replace_numbers_preserve_http_status(s)

    # 7. Collapse whitespace; strip
    s = re.sub(r"\s+", " ", s).strip()

    return s
