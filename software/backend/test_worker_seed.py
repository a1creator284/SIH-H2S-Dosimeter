"""
test_worker_seed.py
===================
Offline tests for the idempotent demo-worker bootstrap and the
``GET /workers/?active_only=...`` filter — the exact path that produced
"No active workers found. Add a worker in the admin dashboard first."

No server and no network required; runs against a temporary in-memory SQLite DB.

Usage:  python test_worker_seed.py
"""
import sys
import os
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Isolate from any local h2s_dosimeter.db — must be set BEFORE importing config.
os.environ["DATABASE_URL"] = "sqlite://"        # in-memory
os.environ.setdefault("APP_ENV", "development")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
import demo_seed
from demo_seed import DEMO_WORKER, ensure_demo_worker
from routes.workers import list_workers

PASS, FAIL = 0, 0


def check(label, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}")


def fresh_session():
    """A brand-new empty in-memory DB with the real schema."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def main():
    print("=" * 60)
    print("  WORKER-AVAILABILITY CHECKS (offline, in-memory DB)")
    print("=" * 60)

    # ── A. Empty roster → seed creates exactly the demo worker ──────────
    print("\n[A] Empty roster bootstraps WRK001")
    db = fresh_session()
    check("roster starts empty", db.query(models.Worker).count() == 0)
    check("ensure_demo_worker() reports it created a worker", ensure_demo_worker(db) is True)

    rows = db.query(models.Worker).all()
    check("exactly one worker exists", len(rows) == 1)
    w = rows[0]
    check("worker_id == 'WRK001'", w.worker_id == "WRK001")
    check("full_name == 'Raj Aryan'", w.full_name == "Raj Aryan")
    check("department == 'Field Operations'", w.department == "Field Operations")
    check("designation == 'Worker'", w.designation == "Worker")
    check("site == 'SIH Demo Site'", w.site == "SIH Demo Site")
    check("shift == 'A'", w.shift == "A")
    check("worker is ACTIVE (visible to active_only=true)", w.is_active is True)

    # ── B. The endpoint the mobile app actually calls ───────────────────
    print("\n[B] GET /workers/?active_only=true returns the worker")
    active = list_workers(site=None, shift=None, active_only=True, db=db)
    check("active_only=true -> 1 row (was [] in production)", len(active) == 1)
    check("active_only=true -> WRK001", active[0].worker_id == "WRK001")
    allw = list_workers(site=None, shift=None, active_only=False, db=db)
    check("active_only=false -> 1 row", len(allw) == 1)

    # ── C. Idempotency: repeated startups must not duplicate ───────────
    print("\n[C] Idempotent across restarts")
    check("2nd run skips (returns False)", ensure_demo_worker(db) is False)
    check("3rd run skips (returns False)", ensure_demo_worker(db) is False)
    check("still exactly one worker", db.query(models.Worker).count() == 1)
    check(
        "no duplicate WRK001",
        db.query(models.Worker).filter(models.Worker.worker_id == "WRK001").count() == 1,
    )

    # ── D. Existing roster is never touched ────────────────────────────
    print("\n[D] Existing roster preserved, never overwritten")
    db2 = fresh_session()
    db2.add(models.Worker(
        worker_id="WRK042", full_name="Existing Person",
        department="Drilling", site="Refinery Unit-1", shift="B",
    ))
    db2.commit()
    check("seed skipped when a roster exists", ensure_demo_worker(db2) is False)
    check("no WRK001 injected into a real roster",
          db2.query(models.Worker).filter(models.Worker.worker_id == "WRK001").first() is None)
    kept = db2.query(models.Worker).filter(models.Worker.worker_id == "WRK042").first()
    check("existing worker untouched", kept is not None and kept.full_name == "Existing Person")
    check("roster size unchanged", db2.query(models.Worker).count() == 1)

    # ── E. A deliberately DEACTIVATED roster is not resurrected ────────
    print("\n[E] Deactivated single-worker roster is not resurrected")
    db3 = fresh_session()
    db3.add(models.Worker(worker_id="WRK001", full_name="Retired Worker", is_active=False))
    db3.commit()
    check("seed skipped (inactive worker still counts as a roster)",
          ensure_demo_worker(db3) is False)
    only = db3.query(models.Worker).filter(models.Worker.worker_id == "WRK001").first()
    check("deactivated worker NOT reactivated", only.is_active is False)
    check("name NOT overwritten with 'Raj Aryan'", only.full_name == "Retired Worker")
    check("active_only=true correctly returns []",
          len(list_workers(site=None, shift=None, active_only=True, db=db3)) == 0)

    # ── F. Kill-switch ─────────────────────────────────────────────────
    print("\n[F] SEED_DEMO_WORKER=false disables seeding")
    db4 = fresh_session()
    original = demo_seed.SEED_DEMO_WORKER
    try:
        demo_seed.SEED_DEMO_WORKER = False
        check("seed skipped when disabled", ensure_demo_worker(db4) is False)
        check("roster stays empty", db4.query(models.Worker).count() == 0)
    finally:
        demo_seed.SEED_DEMO_WORKER = original
    check("re-enabled seed works", ensure_demo_worker(db4) is True)

    # ── G. Payload matches the schema the API returns ──────────────────
    print("\n[G] Demo payload only uses real Worker columns")
    cols = {c.name for c in models.Worker.__table__.columns}
    check("all DEMO_WORKER keys are Worker columns",
          set(DEMO_WORKER).issubset(cols))

    print("\n" + "=" * 60)
    print(f"  RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 60 + "\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
