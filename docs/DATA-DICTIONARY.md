# 潮窗数据字典

| 原件 | 字段 | 定义 |
|---|---|---|
| observations.csv | station, observed_at, level, unit, quality | 文本站号、带偏移整秒、潮尺小数、m/cm/mm、OK/BAD |
| stations.csv | station, section, datum_m, bed_m, priority, offset_s, gap_s | 测站及断面、基准和河床高程、正整数优先级、过断面时间偏移、允许插值的最大观测间隔 |
| vessels.csv | vessel, draft_m, clearance_m, start, end, requested | 船期键、吃水和富余、出发时窗及申请时刻 |

CSV 接受 UTF-8 BOM 和任意字段排列。输入必须有全部字段，空串及 `-`、`N/A`、`NULL`、`未知` 进入逐行隔离。纯空文件、空行文件和仅表头分别报告。单份自带 UTF-8 文本上限 256 KB。结构性有误的测站或船期表中止计算，观测坏行保留原件与行号。

水深 = 潮尺读数换算到米 + 站点基准 − 河床高程。水位使用精确有理数，JSON 以分数字符串保留精度。输出时刻以 UTC Unix 秒表示，插值交点可为分数秒。相邻有效读数之间仅在间隔未超过 `gap_s` 时插值，读数本身可作为独立时点证据，不向时窗两头外推。

同站同刻、同水深保留最早原始行。冲突水深隔离全部冲突行。优先级数值小的站优先；同优先级矛盾时保留冲突，若一致按站号排序。船期 `[start,end)`，断面达标包含恰等瞬时。跨日连续求交不按自然日截断。已知低水位足以驳回，其余情况只要有缺证即缺证。持续时间按互斥区间累计，单点计 0 秒。

归档以规则版本、原件 SHA-256 定址。导出附原件、阶段结果、运行参数和摘要。验签用于检出内容变化，摘要没有第三方身份签名含义。

## 装载档位与补录

| 报文 | 字段 | 定义 |
|---|---|---|
| `POST /api/sailing/advice` | sample, vessel, tiers | 样例键、船期键、1 至 6 档装载方案 |
| tiers[] | tier, draft_m, air_m, bridge_m | 档位名（唯一，≤20 字）、该档吃水、水上船高、桥底标高，均为正小数；吃水逐档递减，水上船高逐档递增 |
| `POST /api/sailing/supplement` | sample, rows | 样例键、1 至 200 行补录潮尺 |
| rows[] | station, observed_at, level, unit, quality | 与 observations.csv 同义；空串及哨兵值拒收，其余坏行随采信流程隔离 |

浅段断面取 `下游浅滩`，过桥断面取 `上游外闸`，到达时刻 = 出发时刻 + 断面 `offset_s`。桥下净空 = 桥底标高 − 到达时刻水位。建议版本以样例、船期、档位与潮据版本（有效潮尺 SHA-256）定址；状态为未确认、已确认、已失效。`POST /api/sailing/advice/<id>/confirm` 确认入簿，`GET /api/sailing/advice/<id>` 查留档。
