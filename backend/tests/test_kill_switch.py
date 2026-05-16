from datetime import date, timedelta
from types import SimpleNamespace


def test_kill_switch_triggers_on_paper_drawdown(monkeypatch):
    from app.services.kill_switch import KillSwitchMonitor

    week = date.today() - timedelta(weeks=1)
    trades = [
        SimpleNamespace(week_starting=week, realized_return=-0.20),
        SimpleNamespace(week_starting=week, realized_return=-0.10),
    ]

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return list(self._rows)

        def first(self):
            return self._rows[0] if self._rows else None

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            self.calls += 1
            if self.calls == 1:
                return FakeResult(trades)
            return FakeResult([])

        def add(self, obj):
            self.added = obj

        def commit(self):
            return None

        def refresh(self, obj):
            obj.id = 42

    session = FakeSession()
    monitor = KillSwitchMonitor(session)
    monkeypatch.setattr(
        monitor,
        "_get_config",
        lambda: SimpleNamespace(max_paper_drawdown_weeks=4, max_paper_drawdown_pct=0.10),
    )
    monkeypatch.setattr(monitor, "_send_notification", lambda event: None)

    events = monitor.check_paper_trading_performance(strategy_id=7)

    assert len(events) == 1
    assert events[0].trigger_type == "paper_poor"
    assert events[0].status == "active"
