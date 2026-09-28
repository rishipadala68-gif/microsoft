import re

REDACTION_PATTERNS = [
    # Private key blocks
    (re.compile(r"-----BEGIN[ A-Z_-]+PRIVATE KEY-----.*?-----END[ A-Z_-]+PRIVATE KEY-----", re.DOTALL), "<redacted>"),
    # AWS access keys
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<redacted>"),
    # Slack tokens
    (re.compile(r"\bxox[baprs]-[0-9a-zA-Z-]+\b"), "<redacted>"),
    # GitHub tokens
    (re.compile(r"\bgh[pousr]_[0-9a-zA-Z]{36,}\b"), "<redacted>"),
    # JWT tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]+\b"), "<redacted>"),
    # Bearer tokens
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_.~+/-]{16,}\b"), "Bearer <redacted>"),
    # Secrets / Passwords in key-value pairs
    (re.compile(r"(?i)\b(password|passwd|secret|api_key|token)\s*[:=]\s*['\"]?([^\s'\",]+)['\"]?"), r"\1=<redacted>"),
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<redacted>"),
    # Phone numbers (US/International standard formats)
    (re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}\b"), "<redacted>"),
]


def redact(s: str) -> str:
    """Redact sensitive information, secrets, credentials, and PII from text."""
    if not s:
        return s
    result = s
    for pattern, replacement in REDACTION_PATTERNS:
        result = pattern.sub(replacement, result)
    return result
