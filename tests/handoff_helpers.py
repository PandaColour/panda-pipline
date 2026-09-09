"""Read referenced test artifacts as an agent would; never change production prompts."""
import re
from pathlib import Path


def read_handoff(message):
    pending = [str(message)]
    seen = set()
    content = []
    while pending:
        text = pending.pop()
        content.append(text)
        for value in re.findall(r'/(?:[^\s"<>、；。，]+)', text):
            path = Path(value.rstrip(',:)}]'))
            if path in seen:
                continue
            seen.add(path)
            if path.is_file() and path.suffix in {'.txt', '.json', '.md'}:
                pending.append(path.read_text(encoding='utf-8'))
    return '\n'.join(content)
