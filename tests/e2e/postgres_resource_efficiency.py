"""Run only against the disposable local database created for this acceptance.
E2E_POSTGRES_URL=postgresql://.../efficiency_e2e python ... --output /tmp/artifacts
"""

from __future__ import annotations
import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlparse

p = argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
args = p.parse_args()
url = os.environ["E2E_POSTGRES_URL"]
parsed = urlparse(url)
assert (
    parsed.hostname in ("localhost", "127.0.0.1") and parsed.path == "/efficiency_e2e"
)
data = tempfile.TemporaryDirectory(prefix="tg-pg-e2e-")
os.environ.update(
    APP_DATABASE_URL=url, APP_DATA_DIR=data.name, APP_SECRET_KEY="isolated-postgres-e2e"
)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import psycopg2
import psycopg2.extensions

calls = []


class CountingCursor(psycopg2.extensions.cursor):
    def execute(self, query, vars=None):
        calls.append(str(query))
        return super().execute(query, vars)


connect = psycopg2.connect


def observed_connect(*a, **kw):
    kw["cursor_factory"] = CountingCursor
    return connect(*a, **kw)


psycopg2.connect = observed_connect
from sqlalchemy import text, inspect
import backend.models
from backend.core.database import get_engine, get_session_local
from backend.core.schema_migrator import upgrade_schema
from backend.repositories.sign_task_config_repo import get_sign_task_config_repo
from backend.repositories.sign_task_history_repo import get_sign_task_history_repo
from backend.models.sign_task_run import SignTaskRun

engine = get_engine()
upgrade_schema(engine)
with engine.begin() as c:
    c.exec_driver_sql("ALTER TABLE sign_task_runs DROP COLUMN summary_json")
    c.exec_driver_sql("DROP INDEX ix_sign_task_runs_account_task_time")
    c.exec_driver_sql("UPDATE schema_version SET version=4 WHERE id=1")
assert upgrade_schema(engine) == 5
assert upgrade_schema(engine) == 5
assert "ix_sign_task_runs_account_task_time" in {
    i["name"] for i in inspect(engine).get_indexes("sign_task_runs")
}
repo = get_sign_task_history_repo()
get_sign_task_config_repo().save_config("sign", "pg", {"sign_at": "09:00", "chats": []})
for i in range(5):
    repo.save_entry(
        "sign",
        "pg",
        {
            "success": True,
            "message": str(i),
            "flow_items": [],
            "run_summary": {"status": "success"},
        },
        max_entries=3,
    )
assert len(repo.load_entries("sign", "pg")) == 3
assert len(repo.load_entries("sign", "pg", limit=1)) == 1
assert repo.get_latest_summaries("pg")[("pg", "sign")]["message"] == "4"
with get_session_local()() as db:
    db.add(
        SignTaskRun(
            account_name="pg",
            task_name="legacy",
            success=True,
            message="legacy",
            flow_items="[]",
            created_at=datetime.utcnow(),
        )
    )
    db.commit()
assert repo.get_latest_summaries("pg")[("pg", "legacy")]["message"] == "legacy"
with engine.connect() as c:
    c.exec_driver_sql("SELECT 42")
calls.clear()
with engine.connect() as c:
    assert c.exec_driver_sql("SELECT 42").scalar() == 42
    pid = c.exec_driver_sql("SELECT pg_backend_pid()").scalar()
pings = sum(q.strip().upper() == "SELECT 1" for q in calls)
assert pings == 1, calls
with connect(url) as admin:
    admin.autocommit = True
    with admin.cursor() as cursor:
        cursor.execute("SELECT pg_terminate_backend(%s)", (pid,))
with engine.connect() as c:
    assert c.exec_driver_sql("SELECT 42").scalar() == 42
    assert c.exec_driver_sql("SELECT pg_backend_pid()").scalar() != pid
engine.dispose()
args.output.mkdir(parents=True, exist_ok=True)
result = {
    "passed": True,
    "v4_migration": True,
    "summary_and_legacy_queries": True,
    "sql_limit_and_pruning": True,
    "checkout_pings": pings,
    "terminated_connection_recovered": True,
}
(args.output / "postgres-e2e.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result))
