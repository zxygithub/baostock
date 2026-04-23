"""Test BaoStock concurrency limits."""

import sys
import time
import sqlite3
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))

import baostock as bs
from src.config import DAILY_KLINE_FIELDS, DB_PATH
from src.utils.helpers import fetch_all_rows, setup_logging

_lock = threading.Lock()


def download_multi_session(code: str, worker_id: int) -> dict:
    result = {"code": code, "worker": worker_id, "rows": 0, "time": 0, "error": None}
    start = time.time()
    try:
        lg = bs.login()
        if lg.error_code != "0":
            result["error"] = f"login: {lg.error_msg}"
            return result
        rs = bs.query_history_k_data_plus(
            code, DAILY_KLINE_FIELDS, "2024-01-01", "2024-12-31", "d", "3"
        )
        if rs.error_code != "0":
            result["error"] = f"query: {rs.error_msg}"
            bs.logout()
            return result
        rows = fetch_all_rows(rs)
        result["rows"] = len(rows)
        bs.logout()
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    result["time"] = time.time() - start
    return result


def download_single_session(code: str, worker_id: int) -> dict:
    result = {"code": code, "worker": worker_id, "rows": 0, "time": 0, "error": None}
    start = time.time()
    try:
        with _lock:
            rs = bs.query_history_k_data_plus(
                code, DAILY_KLINE_FIELDS, "2024-01-01", "2024-12-31", "d", "3"
            )
        if rs.error_code != "0":
            result["error"] = f"query: {rs.error_msg}"
            return result
        rows = fetch_all_rows(rs)
        result["rows"] = len(rows)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    result["time"] = time.time() - start
    return result


def run_test(name, func, codes, workers, logger):
    logger.info(f"\n{'=' * 50}")
    logger.info(f"{name} ({workers} workers)")
    logger.info(f"{'=' * 50}")

    start = time.time()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(func, code, i): code
            for i, code in enumerate(codes[:workers])
        }
        for future in as_completed(futures):
            r = future.result()
            status = "OK" if r["error"] is None else f"FAIL: {r['error']}"
            logger.info(
                f"  Worker {r['worker']}: {r['code']} -> {r['rows']} rows, {r['time']:.2f}s [{status}]"
            )

    total = time.time() - start
    logger.info(f"  Total: {total:.2f}s")


def main():
    logger = setup_logging("concurrency_test")
    logger.info("BaoStock Concurrency Test")

    conn = sqlite3.connect(str(DB_PATH))
    codes = [
        row[0]
        for row in conn.execute(
            "SELECT code FROM stock_basic WHERE type=1 AND status=1 LIMIT 10"
        ).fetchall()
    ]
    conn.close()
    logger.info(f"Loaded {len(codes)} test stocks")

    for w in [1, 2, 3]:
        run_test("Multi-Session", download_multi_session, codes, w, logger)
        time.sleep(2)

    bs.login()
    for w in [1, 2, 3]:
        run_test("Single-Session (shared)", download_single_session, codes, w, logger)
        time.sleep(1)
    bs.logout()

    logger.info("\nTest complete.")


if __name__ == "__main__":
    main()
