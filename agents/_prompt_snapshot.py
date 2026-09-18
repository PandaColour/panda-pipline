"""Write rendered role prompts to fixed paths under the pipeline source tree."""

import hashlib
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from config import SOURCE_REPO_DIR

PROMPT_ROOT = Path(SOURCE_REPO_DIR) / 'temp-prompt-skills'
_LOCK = threading.Lock()


class FixedSystemPrompt(str):
    def __new__(cls, text, path):
        instance = super().__new__(cls, text)
        instance.path = path
        return instance


def freeze_system_prompt(text, source=None):
    if isinstance(text, FixedSystemPrompt) or not text:
        return text
    if source is None:
        # Direct backend callers lack a role filename; identical rules still reuse.
        relative = Path('inline') / (hashlib.sha256(text.encode('utf-8')).hexdigest() + '.md')
    else:
        source = Path(source).resolve()
        try:
            relative = source.relative_to(Path(SOURCE_REPO_DIR).resolve())
        except ValueError:
            relative = Path('custom') / hashlib.sha256(str(source).encode()).hexdigest()[:16] / source.name
    path = PROMPT_ROOT.resolve() / relative
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write completely before replacing the previous run's snapshot.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.writing-', delete=False) as output:
                temporary = Path(output.name)
                output.write(text.encode('utf-8'))
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        fixed = FixedSystemPrompt(text, path)
        return fixed


def prompt_file(text):
    return str(freeze_system_prompt(text).path)


def check_command_length(cmd):
    if sys.platform != 'win32':
        return
    executable = str(cmd[0]).lower()
    limit = 8191 if executable.endswith(('.cmd', '.bat', 'cmd.exe')) else 32767
    length = len(subprocess.list2cmdline([str(arg) for arg in cmd]).encode('utf-16-le')) // 2 + 1
    if length > limit:
        raise ValueError(f'Windows command line exceeds limit: {length} > {limit}; '
                         'task/options are still too long. No text was truncated.')
