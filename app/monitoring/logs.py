from typing import List, Tuple, Optional
import os
import re


def tail_log(path: str, lines: int = 50, max_bytes: int = 200_000) -> List[str]:
    """Return last `lines` lines from file without loading entire file. Hard-limits bytes scanned."""
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        file_size = f.tell()
        to_read = min(file_size, max_bytes)
        f.seek(max(0, file_size - to_read))
        data = f.read(to_read)
    try:
        text = data.decode(errors="replace")
    except Exception:
        text = ""
    all_lines = text.splitlines()
    return all_lines[-lines:]


def tail_log_page(path: str, page: int = 0, page_size: int = 50, max_bytes: int = 500_000) -> Tuple[List[str], int]:
    """Return a page of newest-first lines. page=0 newest. Returns (lines, total_lines_estimate)"""
    lines = tail_log(path, lines=page_size * (page + 1), max_bytes=max_bytes)
    if not lines:
        return [], 0
    # lines currently oldest->newest from tail_log; get newest-first slice
    newest = list(reversed(lines))
    start = page * page_size
    end = start + page_size
    page_lines = newest[start:end]
    total_est = len(lines)  # conservative estimate within max_bytes
    return page_lines, total_est


def filter_lines_by_level(lines: List[str], level: str) -> List[str]:
    lvl = level.upper() if level else ""
    if not lvl:
        return lines
    out = []
    for l in lines:
        if lvl in l:
            out.append(l)
    return out


def search_log_with_filters(path: str, query: str, level: Optional[str] = None, max_results: int = 100, max_bytes: int = 500_000) -> List[str]:
    results = search_log(path, query, max_results=max_results, max_bytes=max_bytes)
    if level:
        results = filter_lines_by_level(results, level)
    return results



def search_log(path: str, query: str, max_results: int = 100, max_bytes: int = 500_000) -> List[str]:
    if not os.path.exists(path):
        return []
    results: List[str] = []
    scanned = 0
    with open(path, "rb") as f:
        for line in f:
            scanned += len(line)
            if scanned > max_bytes:
                break
            try:
                text = line.decode(errors="replace")
            except Exception:
                continue
            if query in text:
                results.append(text)
                if len(results) >= max_results:
                    break
    return results


def stream_log(path: str, last_pos: int, max_bytes: int = 200_000) -> Tuple[List[str], int]:
    """Return new lines since last_pos and new position."""
    if not os.path.exists(path):
        return [], last_pos
    lines: List[str] = []
    new_pos = last_pos
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        if last_pos > end:
            last_pos = 0
        f.seek(last_pos)
        scanned = 0
        while True:
            chunk = f.readline()
            if not chunk:
                break
            scanned += len(chunk)
            if scanned > max_bytes:
                break
            try:
                lines.append(chunk.decode(errors="replace"))
            except Exception:
                lines.append("")
        new_pos = f.tell()
    return lines, new_pos
