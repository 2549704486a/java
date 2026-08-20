#!/usr/bin/env python3
"""Portable load test helper for the seckill interface."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List


def now_str(ts: float | None = None) -> str:
    timezone = dt.datetime.now().astimezone().tzinfo
    if ts is None:
        current = dt.datetime.now().astimezone()
    else:
        current = dt.datetime.fromtimestamp(ts, timezone)
    return current.strftime("%Y-%m-%d %H:%M:%S %z")


def percentile(values: List[float], percent: int) -> float:
    if not values:
        return 0.0
    index = math.ceil(len(values) * percent / 100) - 1
    index = max(0, min(index, len(values) - 1))
    return values[index]


def build_url(base_url: str, path: str, params: Dict[str, object]) -> str:
    query = urllib.parse.urlencode(params)
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}?{query}"


def fetch_json(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"Connection": "close"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.getcode(), response.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "ignore")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a load test against the seckill interface.")
    parser.add_argument("--base-url", required=True, help="Base URL, for example http://10.0.1.3:8088")
    parser.add_argument("--endpoint", default="/userAward/exchangeRedisMq", help="Exchange endpoint path")
    parser.add_argument("--result-endpoint", default="/userAward/result", help="Async result query endpoint path")
    parser.add_argument("--award-id", type=int, default=6)
    parser.add_argument("--user-start", type=int, default=3001)
    parser.add_argument("--user-count", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--t-plus", nargs="*", type=int, default=[5, 15, 30], help="Offsets in seconds")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    users = list(range(args.user_start, args.user_start + args.user_count))

    def hit_exchange(user_id: int) -> Dict[str, object]:
        url = build_url(
            args.base_url,
            args.endpoint,
            {"userId": user_id, "awardId": args.award_id},
        )
        start = time.perf_counter()
        status = None
        body = ""
        biz_code = None
        try:
            status, body = fetch_json(url, args.timeout)
            try:
                biz_code = json.loads(body).get("code")
            except Exception:
                biz_code = None
        except Exception as exc:
            body = str(exc)
        rt_ms = (time.perf_counter() - start) * 1000
        return {
            "userId": user_id,
            "status": status,
            "biz_code": biz_code,
            "rt_ms": rt_ms,
            "body": body[:200],
        }

    def query_result(user_id: int) -> str:
        url = build_url(
            args.base_url,
            args.result_endpoint,
            {"userId": user_id, "awardId": args.award_id},
        )
        try:
            _, body = fetch_json(url, args.timeout)
            payload = json.loads(body)
            code = payload.get("code")
            if code == 200:
                return "success"
            if code == 502:
                return "pending"
            return "fail"
        except Exception:
            return "fail"

    start_wall = time.time()
    start_label = now_str(start_wall)
    perf_start = time.perf_counter()
    results: List[Dict[str, object]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(hit_exchange, user_id) for user_id in users]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    perf_end = time.perf_counter()
    end_wall = time.time()
    end_label = now_str(end_wall)

    duration_s = perf_end - perf_start
    response_times = sorted(float(item["rt_ms"]) for item in results)
    http_status: Dict[str, int] = {}
    biz_code: Dict[str, int] = {}

    for item in results:
        http_status[str(item["status"])] = http_status.get(str(item["status"]), 0) + 1
        biz_code[str(item["biz_code"])] = biz_code.get(str(item["biz_code"]), 0) + 1

    accept_summary = {
        "start_time": start_label,
        "end_time": end_label,
        "duration_s": round(duration_s, 4),
        "total_requests": len(results),
        "concurrency": args.concurrency,
        "qps": round(len(results) / duration_s, 2) if duration_s > 0 else 0.0,
        "avg_rt_ms": round(statistics.mean(response_times), 2) if response_times else 0.0,
        "p50_ms": round(percentile(response_times, 50), 2),
        "p95_ms": round(percentile(response_times, 95), 2),
        "p99_ms": round(percentile(response_times, 99), 2),
        "max_rt_ms": round(max(response_times), 2) if response_times else 0.0,
        "http_status": http_status,
        "biz_code": biz_code,
    }

    def collect_after(offset_seconds: int) -> Dict[str, object]:
        target = perf_end + offset_seconds
        remain = target - time.perf_counter()
        if remain > 0:
            time.sleep(remain)
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            statuses = list(executor.map(query_result, users))
        return {
            "success": sum(1 for item in statuses if item == "success"),
            "pending": sum(1 for item in statuses if item == "pending"),
            "fail": sum(1 for item in statuses if item == "fail"),
            "observed_at": now_str(),
        }

    summary: Dict[str, object] = {"accept": accept_summary}
    for offset in args.t_plus:
        summary[f"t_plus_{offset}"] = collect_after(offset)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
