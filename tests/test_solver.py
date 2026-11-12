"""求解器自检：直接运行 `python3 tests/test_solver.py`（仅依赖标准库 + tzdata）。"""
import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.solver import (  # noqa: E402
    INT64_MAX, INT64_MIN, build_export_csv, solve_csv, utc_candidates,
)

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "dst_sample.csv"
BIG_SEQ_SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "big_seq_sample.csv"


def check(name, cond):
    print(("PASS" if cond else "FAIL"), "-", name)
    if not cond:
        raise SystemExit(1)


def main():
    # 1) 时区候选映射
    cands, err = utc_candidates(datetime(2026, 10, 25, 2, 30), "Europe/Berlin")
    check("柏林拨回：重复时刻保留两个候选", err is None and len(cands) == 2)

    cands, err = utc_candidates(datetime(2026, 3, 29, 2, 30), "Europe/Berlin")
    check("柏林拨快：不存在时刻报错", err == "nonexistent")

    cands, err = utc_candidates(datetime(2026, 6, 1, 12, 0), "Europe/Berlin")
    check("普通时刻：唯一候选", err is None and len(cands) == 1)

    cands, err = utc_candidates(datetime(2026, 1, 1, 0, 0), "Mars/Olympus")
    check("非法 IANA 时区", err == "unknown_tz")

    # 2) 样例整体求解
    result = solve_csv(SAMPLE.read_text(encoding="utf-8"))
    by_tail = {t["tail"]: t for t in result["tails"]}

    check("B-7001 整链唯一解", by_tail["B-7001"]["status"] == "unique")
    check("B-7002 不存在时刻 → error", by_tail["B-7002"]["status"] == "error")
    check("B-7003 链断裂 → no_solution", by_tail["B-7003"]["status"] == "no_solution")
    check("B-7003 冲突定位在 seq=2",
          by_tail["B-7003"]["conflict"]["segment_seq"] == 2)
    check("B-7004 多解", by_tail["B-7004"]["status"] == "multiple")
    check("B-7004 恰好 2 条候选链", by_tail["B-7004"]["solution_count"] == 2)
    check("B-7005 整链唯一解", by_tail["B-7005"]["status"] == "unique")

    # 3) 唯一解内容校验（B-7001 第一段：伦敦 00:30 BST → 23:30Z；
    #    柏林 02:15 双候选 00:15Z/01:15Z，时长 45/165 分钟，区间 [90,130] 只留下 01:15Z）
    sol1 = by_tail["B-7001"]["solution"][0]
    check("B-7001 seg1 起飞 UTC", sol1["dep_utc"] == "2026-10-24T23:30:00Z")
    check("B-7001 seg1 落地 UTC", sol1["arr_utc"] == "2026-10-25T01:15:00Z")

    # 4) 导出只包含唯一解机尾
    csv_out = build_export_csv(result, ["B-7001", "B-7004", "B-7005"])
    lines = [l for l in csv_out.strip().splitlines()]
    check("导出 CSV 行数 = 表头 + B-7001(3) + B-7005(2)", len(lines) == 1 + 3 + 2)
    check("导出 CSV 不含多解机尾 B-7004", "B-7004" not in csv_out)

    # 5) 大序号（int64）样例：字符串序号精确、默认数字字段保留、高亮与导出逐段一致
    big = solve_csv(BIG_SEQ_SAMPLE.read_text(encoding="utf-8"))
    big_by_tail = {t["tail"]: t for t in big["tails"]}
    check("大序号样例：L-1001 唯一解", big_by_tail["L-1001"]["status"] == "unique")
    check("大序号样例：L-1002 无解", big_by_tail["L-1002"]["status"] == "no_solution")
    check("大序号样例：L-1003 多解", big_by_tail["L-1003"]["status"] == "multiple")

    l1 = big_by_tail["L-1001"]
    expected_seqs = ["9007199254740992", "9007199254740993", str(INT64_MAX)]
    check("航段明细 seq_text 为精确十进制字符串",
          [s["seq_text"] for s in l1["segments"]] == expected_seqs)
    check("默认 seq 数字字段与类型保持不变",
          all(isinstance(s["seq"], int) for s in l1["segments"])
          and all(isinstance(s["seq"], int) for s in l1["solution"]))
    check("唯一解每行带 seq_text",
          [s["seq_text"] for s in l1["solution"]] == expected_seqs)
    check("无解冲突提示带精确 segment_seq_text",
          big_by_tail["L-1002"]["conflict"]["segment_seq_text"]
          == "9223372036854775806")
    check("多解候选链带精确 seq_text",
          all(s["seq_text"] in ("9007199254740994", "9007199254740995")
              for sol in big_by_tail["L-1003"]["solutions"] for s in sol))

    # JSON 往返后数字字段仍为整数（FastAPI 直接以该结构响应）
    roundtrip = json.loads(json.dumps(big))
    check("JSON 序列化后 seq 仍为整数且值不丢失",
          all(isinstance(tail["segments"][0]["seq"], int)
              for tail in roundtrip["tails"]))

    # 唯一解高亮的起降 UTC 与下载 CSV 逐段相符
    export = build_export_csv(big, ["L-1001"])
    rows = list(csv.DictReader(io.StringIO(export)))
    check("导出行数与唯一解段数一致", len(rows) == len(l1["solution"]))
    check("导出 CSV 与唯一解逐段相符（seq/dep_utc/arr_utc/duration）",
          all(
              row["seq"] == sol["seq_text"]
              and row["dep_utc"] == sol["dep_utc"]
              and row["arr_utc"] == sol["arr_utc"]
              and row["duration_minutes"] == str(sol["duration_minutes"])
              for row, sol in zip(rows, l1["solution"])
          ))

    # 6) int64 边界：边界值接受，越界值判行级错误
    header = BIG_SEQ_SAMPLE.read_text(encoding="utf-8").splitlines()[0]
    line_tpl = "{tail},{seq},2026-06-01 10:00,Europe/Berlin,2026-06-01 12:00,Europe/Berlin,60,180"
    edge = solve_csv("\n".join([
        header,
        line_tpl.format(tail="X-MIN", seq=INT64_MIN),
        line_tpl.format(tail="X-MAX", seq=INT64_MAX),
    ]))
    edge_status = {t["tail"]: t["status"] for t in edge["tails"]}
    check("int64 上下边界序号可正常求解",
          edge_status == {"X-MIN": "unique", "X-MAX": "unique"})
    overflow = solve_csv("\n".join(
        [header, line_tpl.format(tail="X-OVF", seq=INT64_MAX + 1)]))
    check("超过 int64 上界 → 行级错误且禁止导出",
          overflow["tails"][0]["status"] == "error"
          and "64 位有符号整数范围" in overflow["tails"][0]["errors"][0]["messages"][0])
    underflow = solve_csv("\n".join(
        [header, line_tpl.format(tail="X-UNF", seq=INT64_MIN - 1)]))
    check("低于 int64 下界 → 行级错误",
          underflow["tails"][0]["status"] == "error")

    # 7) 非唯一解仍禁止整链导出（限制不变）
    denied = build_export_csv(big, ["L-1002", "L-1003"])
    check("无解/多解机尾不会出现在导出 CSV",
          "L-1002" not in denied and "L-1003" not in denied and denied.strip() != "")

    print("\n全部自检通过 ✅")


if __name__ == "__main__":
    main()
