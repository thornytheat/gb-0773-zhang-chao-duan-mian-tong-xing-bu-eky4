# 涨潮断面通行簿

内河调度员用潮尺、站点基准和船期表核对放行时间。工作台默认打开断测场次，左侧可依次查看采信、测站归一、阈值交点、全程潮窗、船期覆盖、船期装载建议、运行留档和证据签发。

## 启动

```sh
docker compose up --build
```

访问 `http://localhost:18472`。本机也可安装 `requirements.txt` 后执行 `python -m app.main`。留档存入 `TIDE_DB` 指定的 SQLite 库，默认 `var/tide.sqlite3`。清空演示归档时先停止应用，再移除该库或 Compose 命名卷。

## 复核

1. 首页选海棠17，核对 3000 秒窗口中的 1500 秒可行、900 秒不可行、600 秒缺证。
2. 打开全程可行潮窗，查看放行起止、临界点和断面潮尺行。
3. 打开运行留档，复算并保留原归档号，再到潮窗证据签发下载 JSON 或打印。
4. 切换连续测站样例，海棠17的全部 3000 秒均可行。
5. 打开船期装载建议，核算三档后得本潮满装出发；补录与 U1 矛盾的潮尺行使建议失效并重算，失效版不能确认入簿，留档结论仍可查。

`GET /api/stage/{readings,datum,crossings,windows,coverage}` 可查看样例阶段结果。对同路径执行 POST 可提交 `{"sources":{"observations":"...","stations":"...","vessels":"..."}}`。`POST /api/journal` 接受同一输入或 `{"sample":"dirty"}`。`GET /api/journal/<id>` 查归档，`POST /api/journal/<id>/rerun` 复算，`GET /api/export/<id>` 下载证据。

`POST /api/sailing/advice` 提交 `{"sample":"dirty","vessel":"海棠17","tiers":[{"tier":"满档","draft_m":"2.5","air_m":"6.2","bridge_m":"8.5"},...]}` 核算装载档位与出发建议；`POST /api/sailing/supplement` 提交 `{"sample":"dirty","rows":[{"station":"U1","observed_at":"...","level":"210","unit":"cm","quality":"OK"}]}` 补录潮尺并重算失效建议；`POST /api/sailing/advice/<id>/confirm` 确认入簿，`GET /api/sailing/advice/<id>` 查留档版本。

字段见 [数据字典](docs/DATA-DICTIONARY.md)，规则与回归见 [深度登记](docs/DEPTH.md)。本机运行 `python -m pytest -q`。
