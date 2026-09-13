"""Phân tích tốc độ vote từ DB (vote_jobs — persist từ mọi session).

Dùng: .venv\\Scripts\\python test\\analyze_vote_speed.py [số_job_gần_nhất]
"""
from __future__ import annotations

import statistics
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, ".")


def _parse_iso(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return None


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * p))
    return sorted_vals[idx]


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    from db import get_engine, get_vote_repo

    engine = get_engine()
    try:
        rows = get_vote_repo(engine).list_all(limit=limit)
    finally:
        engine.close()

    if not rows:
        print("Chưa có dữ liệu vote trong DB — chạy vote vài job trước đã "
              "(persist bắt đầu từ bản này).")
        return

    rows = rows[:limit]
    succ = [r for r in rows if r.get("status") == "success"]
    errs = [r for r in rows if r.get("status") == "error"]
    running = [r for r in rows if r.get("status") == "running"]
    queued = [r for r in rows if r.get("status") == "queued"]
    cancelled = [r for r in rows if r.get("status") == "cancelled"]

    durs: list[float] = []
    for r in succ:
        s, f = _parse_iso(r.get("started_at")), _parse_iso(r.get("finished_at"))
        if s and f and f >= s:
            durs.append(f - s)
    durs.sort()

    err_types = Counter()
    for r in errs:
        err_types[(r.get("error") or "unknown")[:70]] += 1

    finished = [
        (r, _parse_iso(r.get("finished_at")))
        for r in rows if _parse_iso(r.get("finished_at"))
    ]
    succ_finished = [(r, t) for r, t in finished if r.get("status") == "success"]

    total = len(rows)
    rate = len(succ) / total * 100 if total else 0

    print("═" * 60)
    print(f"PHÂN TÍCH VOTE — {len(rows)} job gần nhất (từ DB)")
    print(f"success: {len(succ)} | error: {len(errs)} | running: {len(running)} "
          f"| queued: {len(queued)} | cancelled: {len(cancelled)}")
    print(f"Tỷ lệ thành công: {rate:.1f}%")
    if durs:
        avg = statistics.mean(durs)
        print(f"Thời gian/job success: trung bình {avg:.0f}s "
              f"| median {statistics.median(durs):.0f}s | p90 {_pct(durs, 0.9):.0f}s "
              f"| min {durs[0]:.0f}s | max {durs[-1]:.0f}s")
        print(f"→ 1 luồng: {3600 / avg:.0f} vote/giờ (100% success)")

    # Throughput theo giờ (success)
    hour_succ = Counter()
    for r, t in succ_finished:
        hour_succ[datetime.fromtimestamp(t).strftime("%d/%m %H:00")] += 1
    if hour_succ:
        print("\nSuccess theo giờ (mới nhất 12h):")
        for k in sorted(hour_succ)[-12:]:
            print(f"  {k}: {hour_succ[k]}")

    print("\nTop lỗi:")
    for msg, cnt in err_types.most_common(10):
        print(f"  {cnt:>4}  {msg}")

    # ── Dự tính ──
    print("\n" + "═" * 60)
    print("DỰ TÍNH THROUGHPUT")
    if succ_finished:
        first_t = min(t for _r, t in succ_finished)
        last_t = max(t for _r, t in succ_finished)
        span_h = max((last_t - first_t) / 3600, 0.01)
        observed = len(succ) / span_h
        print(f"Thực đo: {len(succ)} success trong {span_h:.1f}h "
              f"= {observed:.0f} vote/giờ (concurrency lúc chạy)")
    if durs:
        avg = statistics.mean(durs)
        eff = rate / 100
        print(f"Dùng: avg {avg:.0f}s/job, success rate {rate:.1f}% "
              f"(đã trừ hao lỗi/retry)")
        print()
        for name, machines, conc in (
            ("1 máy x 5 luồng", 1, 5),
            ("2 máy x 8 luồng", 2, 8),
        ):
            per_machine = conc * (3600 / avg) * eff
            total_votes = per_machine * machines
            print(f"  {name}: {total_votes:.0f} vote/giờ "
                  f"| {total_votes * 24:.0f} vote/ngày "
                  f"| {total_votes * 24 * 30:.0f} vote/tháng")
    print()
    print("Giả định: proxy pool ≥ tổng luồng (mỗi luồng 1 IP riêng), "
          "account đều có lượt vote free, network không nghẽn.")
    print("Cảnh báo: chạy nhiều luồng chung 1 IP → site dễ chặn; "
          "2 máy x 8 luồng cần ~16 proxy.")


if __name__ == "__main__":
    main()