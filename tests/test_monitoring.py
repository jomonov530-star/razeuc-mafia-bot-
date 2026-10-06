import asyncio
import os
import types
import tempfile

import pytest

from app import monitoring


class FakeMessage:
    def __init__(self):
        self.last_text = None

    async def edit_text(self, text, reply_markup=None):
        self.last_text = text


class FakeCallback:
    def __init__(self, user_id: int, message: FakeMessage | None = None):
        self.from_user = types.SimpleNamespace(id=user_id)
        self.message = message
        self.answered = False

    async def answer(self, *args, **kwargs):
        self.answered = True


class DummySettings:
    def __init__(self, admin_ids=None):
        self.admin_ids = set(admin_ids or [])


class FakeEngine:
    def __init__(self, admin_ids=None):
        self.settings = DummySettings(admin_ids=admin_ids)

    async def has_admin_permission(self, user_id: int, role: str = "any") -> bool:
        return user_id in self.settings.admin_ids


@pytest.mark.asyncio
async def test_owner_monitor_server_permission_denied():
    cb = FakeCallback(user_id=123, message=FakeMessage())
    settings = DummySettings(admin_ids={999})
    engine = FakeEngine(admin_ids={999})
    # call handler
    from app.handlers.monitoring import owner_monitor_server

    await owner_monitor_server(cb, engine, settings)
    assert cb.answered is True
    assert cb.message.last_text is None


@pytest.mark.asyncio
async def test_owner_monitor_server_shows_info_for_owner():
    cb = FakeCallback(user_id=1, message=FakeMessage())
    settings = DummySettings(admin_ids={1})
    engine = FakeEngine(admin_ids={1})
    from app.handlers.monitoring import owner_monitor_server

    await owner_monitor_server(cb, engine, settings)
    assert cb.answered is True
    assert cb.message.last_text is not None
    assert "Server status" in cb.message.last_text or "Server" in cb.message.last_text


def test_tail_log_missing():
    out = monitoring.tail_log("nonexistent.log")
    assert out == []


def test_tail_log_large_file():
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as t:
        path = t.name
        for i in range(200):
            t.write(f"line {i}\n")
    try:
        lines = monitoring.tail_log(path, lines=10)
        assert len(lines) == 10
        assert lines[0].startswith("line 190")
    finally:
        os.unlink(path)


def test_db_masking(monkeypatch):
    # monkeypatch app.database
    import app

    fake_engine = types.SimpleNamespace(url="postgresql://secret:pass@localhost/db", name="postgresql")
    monkeypatch.setattr(app, "database", types.SimpleNamespace(engine=fake_engine), raising=False)
    res = monitoring.get_db_status()
    assert "postgresql" in str(res.get("engine")) or res.get("engine") == "postgresql"
    assert "secret" not in str(res.get("url"))


def test_tail_log_page_and_pagination():
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as t:
        path = t.name
        for i in range(200):
            t.write(f"line {i}\n")
    try:
        page_lines, total = monitoring.tail_log_page(path, page=0, page_size=20)
        assert len(page_lines) == 20
        # newest-first should start with last line
        assert page_lines[0].startswith("line 199")
        # page 1 should start with line 179
        page_lines2, _ = monitoring.tail_log_page(path, page=1, page_size=20)
        assert page_lines2[0].startswith("line 179")
    finally:
        os.unlink(path)


def test_search_log_with_filters_and_levels(tmp_path):
    p = tmp_path / "test.log"
    p.write_text("INFO ok\nERROR bad\nWARNING warn\nERROR another\n")
    res = monitoring.search_log_with_filters(str(p), "ERROR", level="ERROR", max_results=10)
    assert any("ERROR" in r for r in res)


def test_owner_monitor_menu_access():
    from app.handlers.monitoring import owner_monitor_menu
    cb = FakeCallback(user_id=5, message=FakeMessage())
    settings = DummySettings(admin_ids={1})
    engine = FakeEngine(admin_ids={1})
    # non-owner
    import asyncio

    asyncio.run(owner_monitor_menu(cb, engine, settings))
    assert cb.answered is True


def test_psutil_unavailable(monkeypatch):
    import sys

    monitoring.system._cache.clear()
    monkeypatch.setitem(sys.modules, "psutil", None)
    cpu = monitoring.get_cpu_info()
    assert cpu.get("cpu_percent") == "N/A"
    # cleanup
    del sys.modules["psutil"]
