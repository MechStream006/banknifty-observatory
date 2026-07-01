"""Tests for DiscoveryController's InstrumentRegistry wiring (L2 M1c).

Reuses the mock-based harness from test_controller.py (_make_controller,
_SchedulerStub, _DT_1/_DT_2, _make_session/_make_archiver) so these tests
exercise the exact same controller construction path as the rest of the
suite, with an added `registry` argument.

Proves:
  1. registry.build() is called exactly once during startup, regardless of
     tick count.
  2. The same registry instance is injected into every chain_fetchers
     entry via its `.registry` setter.
  3. RegistryBuildError raised from build() aborts startup cleanly
     (STARTING -> ABORTED), matching SessionAcquireError's existing
     behaviour, without raising out of run().
  4. registry=None (the default, matching all current callers) preserves
     existing controller behaviour exactly: no build() call, no injection.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lib.discovery._errors import RegistryBuildError
from lib.discovery.controller import DiscoveryController, _STATE_ABORTED, _STATE_STOPPED
from tests.unit.test_discovery.test_controller import (
    _DT_1,
    _DT_2,
    _DT_3,
    _SchedulerStub,
    _make_chain_result,
    _make_controller,
)


def _make_registry(*, build_side_effect: Exception | None = None) -> MagicMock:
    registry = MagicMock()
    registry.resolved_expiries = ["26JUN2026"]
    if build_side_effect is not None:
        registry.build.side_effect = build_side_effect
    return registry


def _make_chain_fetcher_mock() -> MagicMock:
    cf = MagicMock()
    cf.fetch.return_value = _make_chain_result()
    return cf


# ===========================================================================
# registry.build() called exactly once
# ===========================================================================


class TestRegistryBuildCalledOnce:
    def test_build_called_once_across_multiple_ticks(self) -> None:
        registry = _make_registry()
        ctrl = _make_controller(
            registry=registry,
            scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3),
        )
        ctrl.run()
        assert registry.build.call_count == 1

    def test_build_called_with_smart_and_expiries(self) -> None:
        registry = _make_registry()
        expiries = ["26JUN2026", "31JUL2026"]
        chain_fetchers = [_make_chain_fetcher_mock(), _make_chain_fetcher_mock()]
        ctrl = _make_controller(
            registry=registry,
            expiries=expiries,
            chain_fetchers=chain_fetchers,
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        args, kwargs = registry.build.call_args
        assert args[1] == expiries or kwargs.get("expiries") == expiries

    def test_build_called_after_session_connect(self) -> None:
        registry = _make_registry()
        session = MagicMock()
        session.refresh_if_needed.return_value = False
        call_order: list[str] = []
        session.connect.side_effect = lambda: call_order.append("connect")
        registry.build.side_effect = lambda *a, **k: call_order.append("build")
        session.smart = MagicMock()

        ctrl = _make_controller(registry=registry, session=session, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()

        assert call_order == ["connect", "build"]

    def test_build_not_called_when_registry_is_none(self) -> None:
        # Default — matches every existing caller (discovery_run.py unchanged).
        ctrl = _make_controller(scheduler=_SchedulerStub(_DT_1))
        ctrl.run()  # must not raise, no registry to call build() on

    def test_no_ticks_still_builds_registry_once(self) -> None:
        registry = _make_registry()
        ctrl = _make_controller(registry=registry, scheduler=_SchedulerStub())
        ctrl.run()
        assert registry.build.call_count == 1


# ===========================================================================
# Same registry instance injected into every ChainFetcher
# ===========================================================================


class TestRegistryInjectedIntoAllChainFetchers:
    def test_registry_attribute_set_on_single_fetcher(self) -> None:
        registry = _make_registry()
        cf = _make_chain_fetcher_mock()
        ctrl = _make_controller(registry=registry, chain_fetchers=[cf], scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        assert cf.registry is registry

    def test_registry_attribute_set_on_every_fetcher(self) -> None:
        registry = _make_registry()
        fetchers = [_make_chain_fetcher_mock() for _ in range(3)]
        ctrl = _make_controller(
            registry=registry,
            chain_fetchers=fetchers,
            expiries=["E1", "E2", "E3"],
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        assert all(f.registry is registry for f in fetchers)

    def test_all_fetchers_share_the_identical_instance(self) -> None:
        registry = _make_registry()
        fetchers = [_make_chain_fetcher_mock() for _ in range(2)]
        ctrl = _make_controller(
            registry=registry,
            chain_fetchers=fetchers,
            expiries=["E1", "E2"],
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        assert fetchers[0].registry is fetchers[1].registry

    def test_registry_not_injected_when_none(self) -> None:
        cf = _make_chain_fetcher_mock()
        # MagicMock auto-creates attributes on first access; capture that
        # placeholder before run() so we can prove it is never overwritten.
        original_registry_attr = cf.registry
        ctrl = _make_controller(chain_fetchers=[cf], scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        assert cf.registry is original_registry_attr

    def test_injection_happens_before_first_tick_fetch(self) -> None:
        registry = _make_registry()
        cf = _make_chain_fetcher_mock()

        def _assert_registry_wired(smart, spot):
            assert cf.registry is registry
            return _make_chain_result()

        cf.fetch.side_effect = _assert_registry_wired
        ctrl = _make_controller(registry=registry, chain_fetchers=[cf], scheduler=_SchedulerStub(_DT_1))
        result = ctrl.run()
        assert result.total_ticks == 1


# ===========================================================================
# RegistryBuildError aborts startup cleanly
# ===========================================================================


class TestRegistryBuildErrorAbortsStartup:
    def test_run_returns_phase_result_not_raises(self) -> None:
        registry = _make_registry(build_side_effect=RegistryBuildError("no instruments"))
        ctrl = _make_controller(registry=registry, scheduler=_SchedulerStub(_DT_1, _DT_2))
        result = ctrl.run()  # must not raise
        assert result is not None

    def test_state_is_aborted(self) -> None:
        registry = _make_registry(build_side_effect=RegistryBuildError("no instruments"))
        ctrl = _make_controller(registry=registry, scheduler=_SchedulerStub(_DT_1, _DT_2))
        ctrl.run()
        assert ctrl.state == _STATE_ABORTED

    def test_ended_early_is_true(self) -> None:
        registry = _make_registry(build_side_effect=RegistryBuildError("no instruments"))
        ctrl = _make_controller(registry=registry, scheduler=_SchedulerStub(_DT_1, _DT_2))
        result = ctrl.run()
        assert result.ended_early is True

    def test_zero_ticks_processed(self) -> None:
        registry = _make_registry(build_side_effect=RegistryBuildError("no instruments"))
        ctrl = _make_controller(registry=registry, scheduler=_SchedulerStub(_DT_1, _DT_2))
        result = ctrl.run()
        assert result.total_ticks == 0

    def test_chain_fetchers_never_called(self) -> None:
        registry = _make_registry(build_side_effect=RegistryBuildError("no instruments"))
        cf = _make_chain_fetcher_mock()
        ctrl = _make_controller(
            registry=registry, chain_fetchers=[cf], scheduler=_SchedulerStub(_DT_1, _DT_2)
        )
        ctrl.run()
        cf.fetch.assert_not_called()

    def test_archiver_still_closed(self) -> None:
        registry = _make_registry(build_side_effect=RegistryBuildError("no instruments"))
        archiver = MagicMock()
        archiver.current_file_path = None
        ctrl = _make_controller(
            registry=registry, archiver=archiver, scheduler=_SchedulerStub(_DT_1, _DT_2)
        )
        ctrl.run()
        archiver.close.assert_called_once()

    def test_registry_never_injected_into_fetchers_on_build_failure(self) -> None:
        registry = _make_registry(build_side_effect=RegistryBuildError("no instruments"))
        cf = _make_chain_fetcher_mock()
        original_registry_attr = cf.registry
        ctrl = _make_controller(
            registry=registry, chain_fetchers=[cf], scheduler=_SchedulerStub(_DT_1, _DT_2)
        )
        ctrl.run()
        assert cf.registry is original_registry_attr

    def test_generic_exception_from_build_not_swallowed_as_registry_build_error(self) -> None:
        # A plain, unrelated exception from build() is NOT RegistryBuildError
        # and must propagate exactly like any other unhandled controller
        # exception (existing "controller_unhandled_error" path) — this is
        # not a case the registry-fatal handling silently absorbs.
        registry = _make_registry(build_side_effect=RuntimeError("unexpected"))
        ctrl = _make_controller(registry=registry, scheduler=_SchedulerStub(_DT_1))
        with pytest.raises(RuntimeError):
            ctrl.run()


# ===========================================================================
# registry=None preserves existing behaviour exactly
# ===========================================================================


class TestRegistryNonePreservesExistingBehaviour:
    def test_run_completes_normally_without_registry(self) -> None:
        ctrl = _make_controller(scheduler=_SchedulerStub(_DT_1, _DT_2))
        result = ctrl.run()
        assert result.ended_early is False

    def test_state_is_stopped_without_registry(self) -> None:
        ctrl = _make_controller(scheduler=_SchedulerStub(_DT_1, _DT_2))
        ctrl.run()
        assert ctrl.state == _STATE_STOPPED

    def test_ticks_processed_normally_without_registry(self) -> None:
        ctrl = _make_controller(scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3))
        result = ctrl.run()
        assert result.total_ticks == 3
