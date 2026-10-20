"""
src/utils/tail.py - read a growing log file from the end.

events.jsonl and MANIFEST.sha256.jsonl only ever grow, and their readers want
the newest lines. Reading backwards in fixed blocks makes that cost depend on
how many lines are wanted, not on how old the file is.

Author: Bloodawn (KheivenD), 2026-10-13.
"""

from __future__ import annotations

import os
from typing import Iterator

_BLOCK_SIZE = 64 * 1024


def iter_lines_backwards(path, block_size: int = _BLOCK_SIZE) -> Iterator[str]:
    """Yield the lines of a UTF-8 text file from last to first.

    Lines are split like ``str.splitlines()`` (so CRLF files work) except that
    empty lines may be skipped; invalid UTF-8 is replaced, not raised. Raises
    OSError if the file cannot be opened. Close the generator (or exhaust it)
    to release the file handle.
    """
    with open(path, "rb") as fh:
        pos = fh.seek(0, os.SEEK_END)
        partial = b""
        while pos > 0:
            step = min(block_size, pos)
            pos -= step
            fh.seek(pos)
            # Splitting bytes on b"\n" is safe: 0x0A never occurs inside a
            # multi-byte UTF-8 sequence.
            pieces = (fh.read(step) + partial).split(b"\n")
            partial = pieces[0]  # may continue in the previous block
            for raw in reversed(pieces[1:]):
                yield from reversed(raw.decode("utf-8", "replace").splitlines())
        yield from reversed(partial.decode("utf-8", "replace").splitlines())
