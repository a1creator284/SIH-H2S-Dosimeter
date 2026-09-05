"""
demo_seed.py
============
Idempotent bootstrap of the *minimum* roster the field mobile app needs.

Why this exists
---------------
``POST /workers/`` is admin-only and the roster is stored in the database, so a
freshly provisioned deployment starts with **zero** workers. The mobile app then
correctly renders "No active workers found. Add a worker in the admin dashboard
first." and no scan can be performed.

On Render's free tier that is not a one-off: ``DATABASE_URL`` defaults to
``sqlite:///./h2s_dosimeter.db`` on the container's **ephemeral** filesystem, so
the file is discarded on every deploy/restart and any worker added through the
dashboard disappears with it. See ``.env.example`` — point ``DATABASE_URL`` at a
managed PostgreSQL instance for durable storage.

Contract (deliberately conservative — the DB stays the source of truth)
-----------------------------------------------------------------------
* Runs **only** when the ``workers`` table is completely empty.
* Never updates, deactivates or deletes an existing worker.
* Never creates a duplicate ``worker_id``.
* Never runs on a restart where any worker already exists.
* Disable entirely with ``SEED_DEMO_WORKER=false``.

This is a *bootstrap*, not a fixture loader: for the full multi-worker demo
dataset use ``seed.py`` (which wipes the DB and is dev-only).
"""
import logging

import models
from config import SEED_DEMO_WORKER

log = logging.getLogger(__name__)

# The single worker the SIH demo needs in order to reach the scan flow.
DEMO_WORKER = {
    "worker_id": "WRK001",
    "full_name": "Raj Aryan",
    "department": "Field Operations",
    "designation": "Worker",
    "site": "SIH Demo Site",
    "shift": "A",
    "is_active": True,
}


def ensure_demo_worker(db) -> bool:
    """
    Create the demo worker **only** if the roster is entirely empty.

    :returns: ``True`` if a worker was created, ``False`` if the seed was
              skipped (roster already populated, or seeding disabled).
    """
    if not SEED_DEMO_WORKER:
        log.info("Demo-worker seed disabled (SEED_DEMO_WORKER=false).")
        return False

    # Any worker at all — active OR inactive — means a real roster exists and
    # must be left untouched. Checking `is_active` here would resurrect a
    # deliberately deactivated single-worker roster on the next restart.
    if db.query(models.Worker).first() is not None:
        return False

    db.add(models.Worker(**DEMO_WORKER))
    db.commit()
    return True
