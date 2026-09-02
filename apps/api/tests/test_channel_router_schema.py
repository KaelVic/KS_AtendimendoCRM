from __future__ import annotations

from src.db.models import Base


def test_channel_router_tables_are_tenant_scoped_and_fenced() -> None:
    expected_tables = {"gateway_shards", "channel_sessions", "session_assignments"}
    assert expected_tables <= set(Base.metadata.tables)

    for table_name in expected_tables:
        table = Base.metadata.tables[table_name]
        assert "tenant_id" in table.c
        assert "gateway_id" in table.c
        assert "status" in table.c
        assert "owner_epoch" in table.c
        assert "version" in table.c

    session = Base.metadata.tables["channel_sessions"]
    assert "external_session_id" in session.c
    assert "engine" in session.c
    assert "lease_expires_at" in session.c

    assignment = Base.metadata.tables["session_assignments"]
    assert {"external_session_id", "engine"} <= set(assignment.c.keys())
    assert "uq_session_assignments_active_owner" in {index.name for index in assignment.indexes}
    assert any(
        index.unique and index.name == "uq_session_assignments_active_owner"
        for index in assignment.indexes
    )
