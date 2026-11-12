"""求解器自检：直接运行 `python3 tests/test_solver.py`（仅依赖标准库 + tzdata）。"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.solver import (  # noqa: E402
    build_export_csv, solve_csv, utc_candidates,
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

    # 5) 64 位大序号：求解、seq_str 字段、JSON 文本精度、导出 CSV
    big = solve_csv(BIG_SEQ_SAMPLE.read_text(encoding="utf-8"))
    bb = {t["tail"]: t for t in big["tails"]}

    check("B-8801（int64 上限附近相邻序号）整链唯一解",
          bb["B-8801"]["status"] == "unique")
    check("B-8801 三段序号保持精确 int",
          [s["seq"] for s in bb["B-8801"]["segments"]]
          == [9223372036854775805, 9223372036854775806, 9223372036854775807])
    check("B-8801 segments 带精确 seq_str",
          [s["seq_str"] for s in bb["B-8801"]["segments"]]
          == ["9223372036854775805", "9223372036854775806", "9223372036854775807"])
    check("B-8801 solution 带精确 seq_str",
          [s["seq_str"] for s in bb["B-8801"]["solution"]]
          == ["9223372036854775805", "9223372036854775806", "9223372036854775807"])
    sol_big = bb["B-8801"]["solution"]
    check("B-8801 seg1 起飞 UTC", sol_big[0]["dep_utc"] == "2026-10-24T23:30:00Z")
    check("B-8801 seg1 落地 UTC", sol_big[0]["arr_utc"] == "2026-10-25T01:15:00Z")
    check("B-8801 seg2 起降 UTC（链约束消歧）",
          (sol_big[1]["dep_utc"], sol_big[1]["arr_utc"])
          == ("2026-10-25T01:50:00Z", "2026-10-25T03:20:00Z"))

    check("B-8802 链断裂 → no_solution", bb["B-8802"]["status"] == "no_solution")
    check("B-8802 冲突定位在 seq=9007199254740994（2^53 以上）",
          bb["B-8802"]["conflict"]["segment_seq"] == 9007199254740994)
    check("B-8802 冲突带精确 segment_seq_str",
          bb["B-8802"]["conflict"]["segment_seq_str"] == "9007199254740994")

    check("B-8803（int64 下限附近）多解", bb["B-8803"]["status"] == "multiple")
    check("B-8803 恰好 2 条候选链", bb["B-8803"]["solution_count"] == 2)
    check("B-8803 候选链带精确 seq_str",
          bb["B-8803"]["solutions"][0][0]["seq_str"] == "-9223372036854775808")

    # JSON 序列化文本必须逐位保留大序号（批处理方用精确解析器读取时不丢精度）
    payload = json.dumps(big)
    check("JSON 文本保留 int64 最大序号", "9223372036854775807" in payload)
    check("JSON 文本保留 int64 最小序号", "-9223372036854775808" in payload)
    check("JSON 文本保留 2^53+1 序号", "9007199254740993" in payload)

    # 导出 CSV 的 seq 列逐位精确，且与唯一解高亮同源（同一 solution 视图）
    big_csv = build_export_csv(big, ["B-8801", "B-8802", "B-8803"])
    check("大序号导出仅含唯一解机尾 B-8801 的 3 段",
          len(big_csv.strip().splitlines()) == 1 + 3)
    for seq_text in ("9223372036854775805", "9223372036854775806",
                     "9223372036854775807"):
        check(f"导出 CSV 含精确序号 {seq_text}", seq_text in big_csv)
    check("导出 CSV 逐段 UTC 与 solution 视图一致",
          all(f"B-8801,{s['seq_str']},{s['dep_utc']},{s['arr_utc']}" in big_csv
              for s in sol_big))

    print("\n全部自检通过 ✅")


if __name__ == "__main__":
    main()
