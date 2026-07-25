# Literature Helper

```text
┃  ┛━┏┛┃ ┃┏━┛┃  ┏━┃┏━┛┏━┃
┃  ┃ ┃ ┏━┃┏━┛┃  ┏━┛┏━┛┏┏┛
━━┛┛ ┛ ┛ ┛━━┛━━┛┛  ━━┛┛ ┛
```

一个同时面向普通用户、自动化脚本和 Agent 的 Python + Playwright 工具模块。
项目只有三种调用模态，它们共享同一套应用核心：

| 模态 | 入口 | 主要调用者 | 交互与输出 |
| --- | --- | --- | --- |
| TUI | `lithelper` | 日常使用者 | 方向键菜单、页面式导航 |
| CLI | `lithelper fetch ...` | 熟练用户、Shell、CI、Agent | 人类表格或确定性 JSON |
| Python API | `literature_helper.LiteratureHelper` | Python 程序、服务、Agent Runtime | 带类型对象，不解析终端文本 |

Agent 的 `--format json --non-interactive` 是 CLI 模态的结构化运行方式，不是第四种
接口。
核心代码不依赖任何 AI 或 Agent 框架，后续可以按需接入任意编排系统。

## 工作流程

1. 输入一篇文献的 DOI 或准确标题；
2. 处理上一次遗留的历史“待确认”求助；
3. 智能提取文献信息，将结构化结果写入任务记录；
4. 确认信息后单次发布；
5. 进入求助详情，等待用户上传文件；
6. 点击 PDF，优先选择高速通道；
7. 下载后检查 PDF 文件头、大小、可读性、页数和 SHA-256；
8. 保存任务记录并发送系统通知；
9. 本次不立即采纳；下一次 `fetch` 前统一处理历史待确认项；
10. 顺便刷新当前账号积分；积分查询失败不影响文献任务结果。

需要多篇时使用顺序队列：每篇完整执行上述流程后才进入下一篇，绝不并发发布；
遇到等待超时、取消或失败时立即停止后续队列。

程序不会调用外部文献接口，不绕过验证码，也不会保存科研通账号密码。

## 从云端安装

要求 Python 3.11+ 和 Google Chrome。

从 GitHub 安装当前源码：

```bash
uv tool install "git+https://github.com/Shawp1n/literature-helper.git"
lithelper
```

从 PyPI 安装正式版本：

```bash
uv tool install literature-helper
lithelper
```

也可以不做持久安装，像 `npx` 一样临时启动：

```bash
uvx --from literature-helper lithelper
```

开发者在本地源码目录安装：

```bash
cd literature-helper
uv tool install . --force
```

没有 `uv` 时可以使用 `pipx install .` 或
`python3 -m pip install .`。开发和测试使用：

```bash
python3 -m pip install ".[dev]"
pytest
```

如果没有本机 Chrome，可以安装 Playwright Chromium，并在配置中把
`browser_channel` 设为 `null`：

```bash
playwright install chromium
```

## TUI 使用

直接运行：

```bash
lithelper
```

在真实终端中会显示方向键菜单：

```text
❯ 账号管理
  下载文献
  历史记录
  设置
  退出
```

所有选择菜单都会显示标题和方向键说明，并在提示行与菜单项之间保留一行空白，
包括主菜单及全部二级、深层菜单。二级及更深菜单可以按 `Esc` 立即返回上一级，
无需再按 Enter；主界面的 `Esc` 不执行退出，避免误操作。

主界面只保留这五个高频入口。恢复未完成求助和处理历史待确认收纳在
“历史记录”二级菜单，环境检查收纳在“设置”中；CLI 和 Python API 仍保留全部
功能。界面把三行固定 Logo、运行模式和下载目录收纳在同一个响应式外框中，
上方显示金色 Logo，下方以灰色显示英文状态信息；状态标签和值之间使用灰色竖线
分隔，例如 `MODE │ HEADLESS`。外框以及嵌入右下方边框的名称与版本号使用白色，
横线从文字两侧贯穿。功能菜单仍使用中文。外框会按终端宽度调整，并按实际字符宽度裁剪过长路径，
中文目录不会挤断右边框。方向键在菜单首尾处停止，不会从第一项跳到最后一项或
反向循环；设置页在每次操作后整页重绘。
账号、下载、历史记录和设置均采用页面式导航，执行结果会保留到用户按下 Enter，
返回上一级后立即清屏重绘，不会累计已经完成的选择、输入或过程日志。这里吸收了
成熟 TUI 工具的页面生命周期经验，但不依赖或复制其源码：交互菜单、页头、过程
输出和清屏指令统一写入 `stdout`；每次换页会同时清除当前可视区和滚动缓冲区，
避免较长的详情页在返回菜单后残留在上方，同时不创建额外的备用屏幕或输出通道。
所有“按 Enter 返回…”提示与上方结果内容之间固定保留一个空行。

第一次启动会引导设置下载目录和默认运行模式（默认无界面），并可立即输入科研通邮箱与密码。
密码只用于当次登录请求，不会写入配置、SQLite、日志或命令历史；工具保存的是
网站返回的浏览器会话。遇到验证码时可从登录菜单选择“打开浏览器手动登录”。

TUI 中可以：

- 从“账号管理”登录账号；“积分管理”内含“积分刷新 / 积分签到 / 积分充值”；
- 从“下载文献”子菜单输入 DOI 或准确标题并下载；可选择“返回”，文本输入时也可
  按 `Esc` 回到下载子菜单；
- 从“顺序下载多篇”逐行输入最多 10 个 DOI 或标题，空行结束输入；开始前会显示
  完整队列并再次确认；
- 选择无界面或显示浏览器模式；
- “查看任务与下载记录”按时间倒序显示编号后的文献标题；标题缺失的旧任务会回退
  显示 DOI 或原始输入；
- 上下选择标题并回车后，查看智能识别保存的标题、DOI、链接、期刊、作者、
  出版日期、年份、数据来源和识别时间，以及任务状态、PDF 和事件；
- 任务详情下方可以删除本地历史记录及其事件；已下载的 PDF 和科研通网站求助
  不会被删除；
- 在“历史记录”中恢复求助并处理待确认项；
- 在“设置”中修改下载目录、运行模式、等待时间和高速通道偏好；
- 在“设置”中检查依赖、配置和登录会话目录。

TUI 只是调用公共 API 的展示层，不包含独立的业务流程。

## 命令行使用

TUI 之外的所有原有命令仍然可用。首次登录与检查：

初始化并检查环境：

```bash
lithelper init
lithelper doctor
lithelper login
```

`lithelper login` 默认在终端依次提示输入邮箱和密码。密码输入不回显，也不会
进入命令历史、配置文件、SQLite 或日志；程序只保存科研通返回的浏览器登录会话。

也可以把邮箱作为非敏感参数传入，密码仍在终端安全输入：

```bash
lithelper login --email "name@example.com"
```

如果科研通要求验证码，终端登录会停止。此时执行一次可视登录：

```bash
lithelper login --manual-browser
```

登录会话默认保存在系统用户数据目录：

- macOS：`~/Library/Application Support/literature-helper/browser-profile`
- Linux：`~/.local/share/literature-helper/browser-profile`
- Windows：`%LOCALAPPDATA%\literature-helper\browser-profile`

不要同步或提交该目录。

登录后可随时查询当前总积分：

```bash
lithelper points
```

该命令只读取科研通的“积分详情”页，不执行签到、转移或其他积分操作。

签到和充值使用可视浏览器：

```bash
lithelper check-in
lithelper recharge
```

科研通的签到说明明确要求不可利用程序自动签到，因此工具只打开签到页面，由你
手动点击“今日打卡签到”。充值同样只打开科研通官方页面，由你核对金额并完成
支付；工具不会填写金额、提交订单或接触支付信息。完成或取消后回到终端按
Enter（期间保持浏览器窗口打开），程序会刷新并显示当前积分。这两个动作不能
使用 `--non-interactive`。

## 日常使用

使用 DOI：

```bash
lithelper fetch "10.1038/s41586-024-00000-0"
```

使用准确标题：

```bash
lithelper fetch "Exact title of the paper"
```

顺序下载多篇（每个标题作为一个带引号的参数）：

```bash
lithelper fetch-many \
  "10.1038/s41586-024-00000-0" \
  "Exact title of another paper"
```

单次队列最多 10 篇，队列内不允许重复。程序一次只处理一篇；当前篇成功下载后，
下一篇才会开始。为处理上一篇下载后的待确认状态，顺序队列要求保持默认的
`auto_accept_historical_pending: true`，或者启用下载后立即采纳。

无界面运行：

```bash
lithelper fetch "10.xxxx/example" --headless
```

Headless 模式不会打开浏览器窗口，但仍使用 Playwright 浏览器引擎和已经保存的
登录会话。如果登录失效或网站出现验证码，任务会明确停止，不会绕过验证。

指定下载目录：

```bash
lithelper fetch "10.xxxx/example" --download-dir "/path/to/papers"
```

发布前人工检查：

```bash
lithelper fetch "10.xxxx/example" --manual-publish
```

`--manual-publish` 需要可视浏览器，不能与 Headless 人工确认混用。

如果求助已经发布，不要重复 `fetch`。从网站待确认记录继续下载：

```bash
lithelper recover
lithelper recover TASK_ID
```

批量处理历史待确认项，或立即确认单个任务：

```bash
lithelper accept-all
lithelper confirm TASK_ID
```

查看、标记或解除本地任务：

```bash
lithelper list
lithelper show TASK_ID
lithelper reject TASK_ID --reason "标题与求助不一致"
lithelper cancel TASK_ID
```

同一 DOI/标题到达发布边界后，程序默认禁止再次发布。只有确认网站上不存在重复
求助时才使用：

```bash
lithelper fetch "10.xxxx/example" --allow-repeat-after-checking-site
```

## Python 调用

`LiteratureHelper` 是稳定的程序调用入口。所有操作返回 `Task` 或明确的数据对象，
调用方不需要解析终端文本。

```python
import asyncio
import getpass

from literature_helper import LiteratureHelper


async def main() -> None:
    app = LiteratureHelper()

    # 首次使用时调用；不要在源码中硬编码密码。
    await app.login(
        email=input("科研通邮箱："),
        password=getpass.getpass("科研通密码："),
        headless=True,
    )

    points = await app.account_points(headless=True)
    print(points.total)

    # 以下两项会打开浏览器并等待用户手动操作：
    # await app.check_in()
    # await app.recharge_points()

    task = await app.fetch(
        "10.1016/j.example",
        headless=True,
    )
    print(task.to_dict())
    if task.literature:
        print(task.literature.title)
        print(task.literature.authors)

    queue = await app.fetch_many(
        [
            "10.1000/first",
            "Exact title of the second paper",
        ],
        headless=True,
    )
    print(queue.to_dict())


asyncio.run(main())
```

常用方法：

- `await app.fetch(...)`
- `await app.fetch_many([...])`
- `await app.account_points(...)`
- `await app.check_in()`（人工浏览器操作）
- `await app.recharge_points()`（人工浏览器操作）
- `await app.recover(...)`
- `await app.accept_all()`
- `await app.confirm(task_id)`
- `app.list_tasks()`
- `app.task_details(task_id)`
- `app.reject(task_id, reason=...)`
- `app.cancel(task_id)`
- `app.delete_task(task_id)`（只删除本地记录和事件，保留 PDF）

API 默认不打印过程日志。需要日志时传入 `LiteratureHelper(output=print)`。

## CLI 的 Agent 调用模式

`--format json`（简写 `-f json`）让标准输出只包含 JSON，过程日志改写到标准
错误，便于 Shell、调度器或其他程序稳定调用。格式参数可以写在子命令前后：

```bash
lithelper --format json --non-interactive fetch "10.xxxx/example"
lithelper fetch-many "10.xxxx/one" "10.xxxx/two" -f json --non-interactive
lithelper points -f json --non-interactive
lithelper list -f json --non-interactive
lithelper show TASK_ID -f json --non-interactive
```

原有 `--json` 仍作为 `--format json` 的兼容别名保留。
`--non-interactive` 保证程序不会等待终端输入；`fetch` 会自动使用 Headless 模式。
`points`、`recover`、`confirm` 和 `accept-all` 也会无界面运行。登录失效、验证码或必须
人工确认时会立即以非零退出码返回结构化错误。Agent 不应解析或操纵 TUI。

`fetch-many` 返回 `FetchQueueResult`，包含原始顺序、已经产生的任务、
`successful_count`、停止位置和结构化错误。队列中断时，Agent 应检查结果后再决定
是否提交剩余项目，不应盲目重跑整个队列。

`fetch` 返回的任务记录和 `show` 结果都包含 `literature`。这部分数据直接来自
科研通“智能提取文献信息”后填入页面的内容：

```json
{
  "literature": {
    "title": "A structured paper title",
    "doi": "10.1000/example",
    "url": "https://doi.org/10.1000/example",
    "journal": "Journal of Examples",
    "authors": [
      "Ada Lovelace",
      "Alan Turing"
    ],
    "publication_date": "2024-10-01",
    "source": "ablesci_intelligent_extract",
    "extracted_at": "2026-07-25T04:00:00+00:00",
    "publication_year": 2024
  }
}
```

其中 `publication_year` 由 `publication_date` 生成，便于直接统计。网站没有返回
或程序无法可靠识别的字段使用 `null` 或空数组，不会推测补全。普通命令行结果
会显示标题、DOI、期刊和出版日期；完整结构可通过 `--json`、`show` 或 Python
API 获取。

成功结果是任务或操作数据；失败时返回非零退出码，并输出：

```json
{
  "ok": false,
  "error": {
    "type": "LoginRequired",
    "message": "科研通登录状态已失效"
  },
  "meta": {
    "command": "fetch",
    "exit_code": 77
  }
}
```

## 项目结构

项目保持扁平的 `src` 布局，每个模块只有一个明确职责：

```text
literature-helper/
├── .github/workflows/        # GitHub 自动测试与 PyPI 可信发布
│   ├── ci.yml
│   └── publish.yml
├── pyproject.toml             # 构建配置、依赖、版本与 lithelper 命令入口
├── uv.lock                    # 锁定开发和测试依赖，保证本地与 CI 环境一致
├── README.md                  # 安装、使用、输出格式与维护说明
├── LICENSE                    # MIT 开源许可证
├── selectors.example.json     # 网站改版时可选的页面选择器覆盖模板
├── .gitignore                 # 排除缓存、构建产物、系统文件和本地运行数据
├── src/literature_helper/
│   ├── __init__.py            # 公共类型、API 与版本号导出
│   ├── __main__.py            # 支持 python -m literature_helper
│   ├── api.py                 # 供 Python、自动化程序调用的稳定入口
│   ├── cli.py                 # 子命令、JSON 输出与 TUI 安全分流
│   ├── tui.py                 # 仅面向人的方向键交互界面
│   ├── workflow.py            # 发布、轮询、下载、恢复与采纳流程编排
│   ├── adapter.py             # 科研通页面操作及文献信息读取
│   ├── config.py              # 配置加载、校验与用户数据目录
│   ├── diagnostics.py         # CLI 与 TUI 共用的环境检查
│   ├── models.py              # 任务状态和结构化输入/输出模型
│   ├── storage.py             # SQLite 任务、文献信息与事件记录
│   ├── pdfcheck.py            # PDF 文件头、大小、可读性和哈希检查
│   └── notifier.py            # macOS、Windows、Linux 本地系统通知
└── tests/                     # 不访问真实网站的单元与工作流回归测试
```

`selectors.example.json` 只是完整的覆盖示例，程序默认使用 `adapter.py` 内置
选择器，不会自动读取该文件。网站改版时复制它、只修改需要校准的选择器，再把
配置项 `selectors_path` 指向副本即可。`pyproject.toml` 则是 Python 包的唯一
项目清单，集中声明运行依赖、开发依赖、构建方式和 CLI 入口。

这套结构也适合类似的小型 Python 工具：

1. `api.py` 是三个模态共同依赖的应用门面；
2. `cli.py` 和 `tui.py` 只把输入转换为 API 调用，不直接访问存储或网站；
3. `workflow.py` 只编排步骤，不处理终端菜单和输出格式；
4. 外部网站或服务细节隔离在 `adapter.py`，持久化隔离在 `storage.py`；
5. 输入和输出使用带类型的数据对象，JSON 只在 CLI 边界序列化；
6. 运行数据放在系统用户目录，不写入源码目录；
7. Agent 只使用非交互 CLI 或 Python API，不解析 TUI；
8. README 集中说明使用与架构，接口变更需要同步测试。

这种边界既方便人阅读和测试，也允许未来被任何外部框架包装，而无需改写核心逻辑。

## 配置与数据

`lithelper init` 生成 `config.json`。常用字段：

```json
{
  "download_dir": "/Users/me/Downloads/科研通",
  "browser_channel": "chrome",
  "headless": true,
  "initial_poll_delay_seconds": 8.0,
  "poll_interval_seconds": 3.0,
  "poll_timeout_seconds": 180.0,
  "download_timeout_seconds": 180.0,
  "minimum_pdf_bytes": 8000,
  "auto_publish": true,
  "prefer_high_speed_download": true,
  "auto_accept_after_validation": false,
  "auto_accept_historical_pending": true,
  "save_debug_artifacts": true,
  "selectors_path": null
}
```

可通过 `--config /path/to/config.json` 使用其他配置，也可以设置
`LITHELPER_HOME` 改变默认数据目录。

任务、提取到的文献信息与事件保存在 `tasks.sqlite3`。程序会自动兼容并升级
旧数据库结构。主要状态：

- `waiting_login`：登录状态不可用；
- `matching`：正在提取或匹配文献；
- `ready_to_publish`：已到发布边界；
- `waiting_file`：已发布，正在等待应助；
- `downloading`：正在下载；
- `downloaded_pending_review`：下载和基础检查完成；
- `confirmed` / `rejected`：任务已处理；
- `timed_out` / `failed` / `cancelled`：未正常完成。

## 使用边界

本工具只面向本人、小规模、个人学习研究用途：

- 优先使用 DOI，标题应准确且唯一；
- 多篇功能只允许最多 10 篇的顺序队列，不并发发布、不高频刷新、不替他人求助；
- 不传播或用于盈利；
- 轮询间隔硬性限制为不低于 3 秒；
- 验证码和网站规则确认始终保留人工处理；
- PDF 基础检查不能代替病毒扫描，也不能判断正文内容是否完全正确。

## 网站改版与测试

网站结构变化时，程序会在用户数据目录的 `debug` 中保存截图和可见文本。
可以复制 `selectors.example.json`，修改选择器后通过配置中的
`selectors_path` 加载。

诊断截图可能包含用户名、积分和求助信息，分享前应先脱敏。

运行测试：

```bash
pytest
```

自动化测试不会真实发布求助。
