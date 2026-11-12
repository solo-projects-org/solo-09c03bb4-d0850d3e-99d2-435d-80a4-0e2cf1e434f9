# 航段时间清洗 · DST 安全入仓

面向航司数据工程师的网页工具：把地服导出的**当地时间**航段链解析为唯一 **UTC** 时间链，
避免夏令时（DST）切换时被错误入仓。

## 快速启动

```bash
docker compose up --build
```

浏览器打开 <http://localhost:8000> ，点击「📦 载入内置夏令时样例」→「开始清洗」即可看到完整演示；
「🔢 载入大序号样例」演示 64 位有符号整数序号的精确显示与导出。

本地开发（不用 Docker）：

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

自检（仅标准库）：`python3 tests/test_solver.py`

## 输入 CSV 格式

UTF-8 编码，必需表头：

```csv
tail_number,seq,dep_local,dep_tz,arr_local,arr_tz,duration_min_minutes,duration_max_minutes
B-7001,1,2026-10-25 00:30,Europe/London,2026-10-25 02:15,Europe/Berlin,90,130
```

| 列 | 含义 |
| --- | --- |
| `tail_number` | 机尾号（同一机尾构成一条航段链） |
| `seq` | 航段顺序，整数，同一机尾内唯一，按升序链接；**支持 64 位有符号整数**（如 `9223372036854775807`） |
| `dep_local` / `arr_local` | 起飞/落地当地时间，`YYYY-MM-DD HH:MM`（也接受 `T` 分隔与秒） |
| `dep_tz` / `arr_tz` | 两端 IANA 时区名，如 `Europe/Berlin`、`America/New_York` |
| `duration_min_minutes` / `duration_max_minutes` | 飞行时长下/上限（分钟，**闭区间**） |

## 求解规则

1. 当地时间 → UTC 候选：
   - 普通时刻 → 1 个候选；
   - **重复时刻**（秋季拨回重叠，如柏林 2026-10-25 02:30）→ 保留 **2 个候选**参与整链求解；
   - **不存在的时刻**（春季拨快空洞，如柏林 2026-03-29 02:30）→ 该行报错，整架机尾禁止导出。
2. 每个航段的 (起飞, 落地) 候选组合必须满足：飞行时长 ∈ `[下限, 上限]`（闭区间）。
3. 按 `seq` 链接同一机尾：下一段起飞 **不得早于** 上一段落地（相等允许）。
4. 判定：
   - **整链唯一解** → 允许导出该机尾的 UTC CSV；
   - **无解** → 展示冲突航段（前向扫描定位第一个无法衔接的航段及其候选），禁止导出；
   - **多解** → 展示全部可行候选链（最多展示 20 条），禁止导出；
   - **行级错误**（不存在时刻 / 非法时区 / 格式错误 / seq 重复等）→ 禁止导出。

## 导出

- 网页上按机尾导出，或「导出全部可导出机尾」；
- 导出列：`tail_number,seq,dep_utc,arr_utc,duration_minutes`（UTC 为 ISO 8601 `Z` 格式）；
- 服务端在导出时会**重新求解并复核唯一性**，非唯一解返回 409，杜绝误导出。

## 内置样例（samples/dst_sample.csv）

| 机尾 | 场景 | 期望结果 |
| --- | --- | --- |
| B-7001 | 欧洲拨回日三连段，重复时刻由时长区间+链约束消歧 | 唯一解，可导出 |
| B-7002 | 柏林 2026-03-29 02:30 不存在（拨快空洞） | 数据错误 |
| B-7003 | 第二段起飞早于第一段落地 | 无解，展示冲突航段 |
| B-7004 | 起降均为重复时刻，区间宽松 | 多解（2 条候选链） |
| B-7005 | 美国拨回日（纽约/洛杉矶/丹佛） | 唯一解，可导出 |

## 大序号样例（samples/big_seq_sample.csv）

地服使用 64 位有符号整数作 `seq` 时，浏览器 JS Number（双精度浮点）在 |seq| > 2^53
会丢失精度，把相邻大序号显示成同一个数。本样例覆盖该场景，可在网页上直接上传核对：

| 机尾 | seq | 场景 | 期望结果 |
| --- | --- | --- | --- |
| B-8801 | `9223372036854775805`～`...807`（int64 上限附近） | 欧洲拨回日三连段 | 唯一解，可导出，序号逐位精确 |
| B-8802 | `9007199254740993`/`...994`（2^53 以上） | 第二段起飞早于第一段落地 | 无解，冲突提示显示精确序号 |
| B-8803 | `-9223372036854775808`/`...807`（int64 下限附近） | 起降均为重复时刻 | 多解（2 条候选链） |

实现方式：`/api/solve` 的 JSON 中 `seq` 保持**数值类型不变**（批处理调用方不受影响，
JSON 文本逐位保留全部数字），同时为每个航段、每条解、每处冲突附加 `seq_str` /
`segment_seq_str` 十进制字符串字段；网页一律用字符串字段显示序号并匹配唯一解高亮，
因此高亮的起降 UTC 与下载的 CSV 逐段一致。导出 CSV 的 `seq` 列同样逐位精确。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | 网页入口 |
| `GET` | `/api/sample` | 下载内置样例 CSV（默认夏令时样例；`?name=big_seq` 为大序号样例） |
| `POST` | `/api/solve` | 上传 CSV（multipart 字段 `file`），返回逐机尾求解结果 JSON |
| `POST` | `/api/export` | 字段 `file` + `tail`（`__all__` 表示全部可导出机尾），返回 UTC CSV；非唯一解 409 |
| `GET` | `/docs` | FastAPI 自动文档 |

`/api/solve` 返回中每个航段/解/冲突的 `seq` 为 JSON 数值（既有字段与类型不变），
并附加 `seq_str`（冲突为 `segment_seq_str`）十进制字符串，供需要精确显示 64 位
序号的调用方使用。

## 目录结构

```
app/
  main.py            # FastAPI 路由
  solver.py          # 候选生成 + 整链求解 + 冲突定位（纯标准库）
  static/index.html  # 单页前端
samples/dst_sample.csv      # 夏令时样例
samples/big_seq_sample.csv  # 64 位大序号样例
tests/test_solver.py
Dockerfile / docker-compose.yml / requirements.txt
```
