import sys


def executable_name(name):
    return f"{name}.cmd" if sys.platform == "win32" else name
