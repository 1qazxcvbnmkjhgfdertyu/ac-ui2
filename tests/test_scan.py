"""Tests for the cancellable background scanner (scan.py)."""
import time

from ac_ui.scan import BackgroundScan


def test_runs_and_returns_result():
    scan = BackgroundScan(lambda cancel: 21 * 2).start()
    assert scan.join(timeout=2.0) == 42
    assert scan.done
    assert scan.error is None


def test_worker_receives_cancel_predicate_and_stops():
    progress = []

    def worker(should_cancel):
        for i in range(1000):
            if should_cancel():
                return ("cancelled", i)
            progress.append(i)
            time.sleep(0.005)
        return ("complete", 1000)

    scan = BackgroundScan(worker).start()
    time.sleep(0.02)
    scan.cancel()
    result = scan.join(timeout=2.0)
    assert result[0] == "cancelled"
    assert scan.done


def test_error_is_captured_not_raised():
    def boom(should_cancel):
        raise ValueError("kaboom")

    scan = BackgroundScan(boom).start()
    scan.join(timeout=2.0)
    assert scan.done
    assert isinstance(scan.error, ValueError)
    assert scan.result is None


def test_double_start_is_idempotent():
    scan = BackgroundScan(lambda cancel: 1)
    scan.start()
    t1 = scan._thread
    scan.start()
    assert scan._thread is t1
    scan.join(timeout=2.0)
