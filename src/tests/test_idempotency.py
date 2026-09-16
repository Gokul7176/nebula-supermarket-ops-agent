import os
import tempfile
import pytest
from src.db.connection import get_db_connection
from src.db.init_db import init_db
from src.bot.idempotency import check_and_start_update, mark_update_succeeded, mark_update_failed

@pytest.fixture
def test_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_idempotency.db")
        init_db(db_path)
        monkeypatch.setenv("DB_PATH", db_path)
        yield db_path

def test_telegram_update_idempotency_flow(test_db):
    update_id = 998877

    # 1. First arrival -> PROCEED
    action1, _ = check_and_start_update(update_id)
    assert action1 == "PROCEED"

    # 2. In-flight duplicate arrival -> SKIP_IN_FLIGHT
    action2, _ = check_and_start_update(update_id)
    assert action2 == "SKIP_IN_FLIGHT"

    # 3. Mark succeeded
    mark_update_succeeded(update_id, "Result Text Output")

    # 4. Subsequent duplicate arrival -> SKIP_CACHED with cached result
    action3, cached_res = check_and_start_update(update_id)
    assert action3 == "SKIP_CACHED"
    assert cached_res == "Result Text Output"

def test_failed_update_allows_retry(test_db):
    update_id = 112233

    # First arrival -> PROCEED
    action1, _ = check_and_start_update(update_id)
    assert action1 == "PROCEED"

    # Exception occurs -> mark failed
    mark_update_failed(update_id, "Database timeout error")

    # Retry arrival -> PROCEED (retry allowed)
    action2, _ = check_and_start_update(update_id)
    assert action2 == "PROCEED"
