"""Redacts secrets from text before it's stored or sent to Claude: commit
messages, session and window titles, and later transcripts. It errs towards
redacting too much, since a leaked token costs more than a lost word."""

import re

MARK = "[REDACTED]"

PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    re.compile(r"\b(?:glpat-[A-Za-z0-9_-]{20,}|npm_[A-Za-z0-9]{36})"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
]
# Keep the label, hide the value: "password=…", "api_key: …", "Bearer …", "https://user:pass@host".
LABELLED = re.compile(
    r"(?i)\b((?:password|passwd|pwd|passphrase|secret|client[_-]?secret|token|access[_-]?token|refresh[_-]?token"
    r"|api[_-]?key|access[_-]?key|private[_-]?key)\b[\"']?\s*[:=]\s*[\"']?)([^\s\"',;]{6,})")
BEARER = re.compile(r"(?i)\b((?:bearer|basic)\s+)([A-Za-z0-9._~+/=-]{16,})")
URL_CREDENTIALS = re.compile(r"(://)[^/\s:@]+:[^/\s@]+(@)")


def redact(text):
    if not text:
        return text
    for pattern in PATTERNS:
        text = pattern.sub(MARK, text)
    text = LABELLED.sub(lambda m: m.group(1) + MARK, text)
    text = BEARER.sub(lambda m: m.group(1) + MARK, text)
    return URL_CREDENTIALS.sub(lambda m: m.group(1) + MARK + m.group(2), text)
