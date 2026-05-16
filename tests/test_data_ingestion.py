from datetime import date

from app.services.data_ingestion import DataIngestionService


class _DummySession:
    def __init__(self):
        self.executed = []
        self.committed = False

    def execute(self, stmt):
        self.executed.append(stmt)
        return None

    def commit(self):
        self.committed = True


def test_record_universe_snapshot_commits_changes():
    session = _DummySession()
    svc = DataIngestionService(session)

    count = svc.record_universe_snapshot(date(2026, 5, 15), ["AAPL", "MSFT"])

    assert count == 2
    assert session.committed is True
    assert len(session.executed) == 1
