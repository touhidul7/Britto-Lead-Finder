import time
from datetime import datetime, timezone

from .config import SCHEDULER_POLL_SECONDS
from .scheduler import run_due_mandates


def run_loop():
    print(f"ListingsFinder scheduler loop started. Polling every {SCHEDULER_POLL_SECONDS} seconds.", flush=True)
    while True:
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            results = run_due_mandates()
            if results:
                print(f"[{started}] Ran scheduled mandates: {results}", flush=True)
            else:
                print(f"[{started}] No due mandates found.", flush=True)
        except Exception as exc:
            print(f"[{started}] Scheduler error: {exc}", flush=True)
        time.sleep(max(60, SCHEDULER_POLL_SECONDS))


if __name__ == "__main__":
    run_loop()