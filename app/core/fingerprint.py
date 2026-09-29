import hashlib
import re
from dataclasses import dataclass

from app.core.normalize import normalize_text

NON_APP_PATTERNS = [
    "site-packages",
    "dist-packages",
    "node_modules",
    "lib/python",
    "/usr/lib",
    "/usr/local/lib",
    "java.",
    "javax.",
    "sun.",
    "jdk.",
    "org.springframework.",
    "org.apache.",
    "runtime/",
    "internal/",
]


@dataclass
class Frame:
    file: str
    function: str
    is_app: bool


def _is_app_frame(file_or_class: str) -> bool:
    low = file_or_class.lower()
    for pat in NON_APP_PATTERNS:
        if pat.lower() in low:
            return False
    return True


def _clean_path(path: str) -> str:
    """Reduce path to the last two path segments."""
    parts = path.replace("\\", "/").strip("/").split("/")
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return parts[-1] if parts else path


def parse_stack_trace(text: str) -> tuple[str, list[Frame]]:
    """
    Parses stack trace in Python, Java, Node, or Go format.
    Returns (exception_type, list[Frame]).
    """
    frames: list[Frame] = []
    exc_type = "Error"

    # Python pattern: File "...", line ..., in ...
    py_pattern = re.compile(r'File\s+"([^"]+)",\s+line\s+\d+,\s+in\s+([a-zA-Z0-9_<>\.]+)')
    py_exc_pattern = re.compile(r'\b([A-Z][a-zA-Z0-9_]*Error|[A-Z][a-zA-Z0-9_]*Exception)\b')

    # Java pattern: at com.acme.Foo.bar(Foo.java:123)
    java_pattern = re.compile(r'at\s+([a-zA-Z0-9_$.]+)\.([a-zA-Z0-9_$]+)\(([^:)]+)(?::\d+)?\)')
    java_exc_pattern = re.compile(r'\b([a-zA-Z0-9_$.]*Exception|[a-zA-Z0-9_$.]*Error)\b:')

    # Node pattern: at [func] (path:line:col) or at path:line:col
    node_pattern1 = re.compile(r'at\s+([a-zA-Z0-9_$.<>]+)\s+\(([^:]+):\d+:\d+\)')
    node_pattern2 = re.compile(r'at\s+([^:]+):\d+:\d+')

    # Go pattern: pkg.Func(...) \n \t/path/file.go:line +0x...
    go_pattern = re.compile(r'([a-zA-Z0-9_./]+)\.([a-zA-Z0-9_]+)\(.*\)\n\s+([^\s:]+\.go):\d+')

    # Check for Java
    java_matches = java_pattern.findall(text)
    if java_matches:
        exc_match = java_exc_pattern.search(text)
        if exc_match:
            exc_type = exc_match.group(1).split(".")[-1]
        for cls, func, src in java_matches:
            is_app = _is_app_frame(cls)
            frames.append(Frame(file=_clean_path(src), function=func, is_app=is_app))
        return exc_type, frames

    # Check for Python
    py_matches = py_pattern.findall(text)
    if py_matches:
        exc_match = py_exc_pattern.search(text)
        if exc_match:
            exc_type = exc_match.group(1)
        for filepath, func in py_matches:
            is_app = _is_app_frame(filepath)
            frames.append(Frame(file=_clean_path(filepath), function=func, is_app=is_app))
        return exc_type, frames

    # Check for Node
    node_matches1 = node_pattern1.findall(text)
    if node_matches1:
        for func, filepath in node_matches1:
            is_app = _is_app_frame(filepath)
            frames.append(Frame(file=_clean_path(filepath), function=func, is_app=is_app))
        return exc_type, frames

    node_matches2 = node_pattern2.findall(text)
    if node_matches2:
        for filepath in node_matches2:
            is_app = _is_app_frame(filepath)
            frames.append(Frame(file=_clean_path(filepath), function="anonymous", is_app=is_app))
        return exc_type, frames

    # Check for Go
    go_matches = go_pattern.findall(text)
    if go_matches:
        for pkg, func, filepath in go_matches:
            is_app = _is_app_frame(pkg) and _is_app_frame(filepath)
            frames.append(Frame(file=_clean_path(filepath), function=func, is_app=is_app))
        return exc_type, frames

    return exc_type, frames


def fingerprints(text: str) -> list[str]:
    """
    Returns:
    - Stack fingerprint (if stack trace found): sha1(f"{exc_type}|{f1}|{f2}|{f3}")[:16]
      where f1..f3 are the innermost 3 is_app frames as file:function.
    - Message fingerprint: sha1(normalized_first_error_line)[:16].
    """
    fps = []

    # 1. Stack fingerprint
    exc_type, frames = parse_stack_trace(text)
    app_frames = [f for f in frames if f.is_app]
    if app_frames:
        innermost_3 = app_frames[-3:]
        frame_strs = [f"{f.file}:{f.function}" for f in innermost_3]
        stack_payload = f"{exc_type}|{'|'.join(frame_strs)}"
        stack_fp = hashlib.sha1(stack_payload.encode("utf-8")).hexdigest()[:16]
        fps.append(stack_fp)

    # 2. Message fingerprint
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    first_error_line = ""
    for ln in lines:
        if any(err_term in ln.lower() for err_term in ["error", "exception", "failed", "fatal", "panic", "timed out", "refused"]):
            first_error_line = ln
            break
    if not first_error_line and lines:
        first_error_line = lines[0]

    if first_error_line:
        norm_line = normalize_text(first_error_line)
        msg_fp = hashlib.sha1(norm_line.encode("utf-8")).hexdigest()[:16]
        fps.append(msg_fp)

    return fps
