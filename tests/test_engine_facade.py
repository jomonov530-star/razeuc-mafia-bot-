"""Tests for GameEngine facade architecture and mixin integration."""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import Settings
from app.game_engine import GameEngine
from app.engine.core import CoreMixin
from app.engine.registration import RegistrationMixin
from app.engine.phase_night import NightPhaseMixin
from app.engine.phase_day import DayPhaseMixin
from app.engine.victory import VictoryMixin
from app.engine.hero_ops import HeroOpsMixin
from app.engine.economy_ops import EconomyOpsMixin
from app.engine.admin_ops import AdminOpsMixin
from app.engine.social_ops import SocialOpsMixin


def test_game_engine_inherits_all_mixins():
    """Verify that GameEngine subclassing connects all mixin components."""
    assert issubclass(GameEngine, CoreMixin)
    assert issubclass(GameEngine, RegistrationMixin)
    assert issubclass(GameEngine, NightPhaseMixin)
    assert issubclass(GameEngine, DayPhaseMixin)
    assert issubclass(GameEngine, VictoryMixin)
    assert issubclass(GameEngine, HeroOpsMixin)
    assert issubclass(GameEngine, EconomyOpsMixin)
    assert issubclass(GameEngine, AdminOpsMixin)
    assert issubclass(GameEngine, SocialOpsMixin)


def test_facade_exposes_essential_methods():
    """Verify facade class contains required public methods without attribute errors."""
    engine_cls = GameEngine
    methods = [
        "create_game_registration",
        "join_game",
        "close_registration",
        "send_night_prompts",
        "record_action",
        "resolve_night",
        "start_voting",
        "cast_vote",
        "resolve_voting",
        "check_winner",
        "finish_game",
        "is_credit_blocked",
        "invalidate_credit_blocked_cache",
        "registration_watchdog",
    ]
    for method in methods:
        assert hasattr(engine_cls, method), f"GameEngine missing method: {method}"


@pytest.mark.asyncio
async def test_game_engine_instantiation():
    """Verify GameEngine can be instantiated with settings and session_factory."""
    test_db_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(bind=test_db_engine)
    settings = Settings()
    
    engine = GameEngine(settings=settings, session_factory=session_factory)
    assert engine.settings == settings
    assert engine.session_factory == session_factory
    assert isinstance(engine._credit_blocked_cache, dict)
    await test_db_engine.dispose()


def test_facade_matches_full_original_manifest():
    """Verify that GameEngine contains ALL 284 original methods with exact parameter names."""
    import ast
    from pathlib import Path

    manifest_path = Path("scratch_old_engine.py")
    if not manifest_path.exists():
        pytest.skip("scratch_old_engine.py manifest file not found")

    content = manifest_path.read_bytes()
    for enc in ["utf-8", "utf-16", "utf-8-sig"]:
        try:
            tree = ast.parse(content.decode(enc))
            break
        except Exception:
            continue
    else:
        pytest.fail("Could not decode scratch_old_engine.py")

    old_methods: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "GameEngine":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [a.arg for a in item.args.args]
                    if item.args.vararg:
                        args.append(item.args.vararg.arg)
                    args.extend([a.arg for a in item.args.kwonlyargs])
                    if item.args.kwarg:
                        args.append(item.args.kwarg.arg)
                    old_methods[item.name] = args

    assert len(old_methods) >= 284, f"Expected at least 284 original methods, got {len(old_methods)}"

    missing_methods = []
    signature_mismatches = []

    for method_name, old_args in old_methods.items():
        if not hasattr(GameEngine, method_name):
            missing_methods.append(method_name)
            continue

        method_obj = getattr(GameEngine, method_name)
        if callable(method_obj):
            try:
                import inspect
                sig = inspect.signature(method_obj)
                current_args = list(sig.parameters.keys())
                if current_args != old_args and not method_name.startswith("__"):
                    signature_mismatches.append((method_name, old_args, current_args))
            except (TypeError, ValueError):
                pass

    assert not missing_methods, f"GameEngine missing {len(missing_methods)} original methods: {missing_methods}"
    assert not signature_mismatches, f"Signature mismatches found: {signature_mismatches[:5]}"


