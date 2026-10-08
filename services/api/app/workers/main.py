"""python -m app.workers.main: explicit server polling process, no setup effects."""

import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from app.core.db import dispose_engine, get_engine
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.catalog import models as catalog_models  # noqa: F401
from app.workers.notifications import process_outbox, send_due_notifications


def main(*, on_ready=None):
    factory = sessionmaker(get_engine(), expire_on_commit=False)
    ready_reported = False
    try:
        while True:
            try:
                now = datetime.now(timezone.utc)
                with factory() as db:
                    process_outbox(db, now)
                    db.commit()
                if not ready_reported and on_ready is not None:
                    on_ready()
                    ready_reported = True
                send_due_notifications(
                    datetime.now(timezone.utc),
                    session_factory=factory,
                    clock=lambda: datetime.now(timezone.utc),
                )
            except Exception:
                # Database/transport exceptions can contain credentials. Never log repr/traceback.
                logging.error("notification_worker_iteration_failed")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        dispose_engine()


if __name__ == "__main__":
    main()
