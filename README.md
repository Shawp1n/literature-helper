# Literature Helper

```text
┃  ┛━┏┛┃ ┃┏━┛┃  ┏━┃┏━┛┏━┃
┃  ┃ ┃ ┏━┃┏━┛┃  ┏━┛┏━┛┏┏┛
━━┛┛ ┛ ┛ ┛━━┛━━┛┛  ━━┛┛ ┛
```

一个同时面向普通用户和自动化系统的 Python + Playwright 文献工具。普通用户
可以通过方向键 TUI 完成登录、下载、恢复和历史记录管理；脚本与 Agent 则使用
确定性 CLI、JSON 输出或 Python API。

项目提供三种等价入口：

- 日常使用：直接运行 `lithelper` 打开 TUI；
- 熟练用户：`lithelper fetch ...` 等子命令；
- 脚本调用：`literature_helper.LiteratureHelper` Python API；
- Agent 编排：CLI 的 `--json --non-interactive` 结构化模式。

核心代码不依赖任何 AI 或 Agent 框架，后续可以按需作为普通工具接入其他系统。

## 工作流程

1. 输入一篇文献的 DOI 或准确标题；
2. 处理上一次遗留的历史“待确认”求助；
3. 智能提取文献信息，将结构化结果写入任务记录；
4. 确认信息后单次发布；
5. 进入求助详情，等待用户上传文件；
6. 点击 PDF，优先选择高速通道；
7. 下载后检查 PDF 文件头、大小、可读性、页数和 SHA-256；
8. 保存任务记录并发送系统通知；
9. 本次不立即采纳；下一次 `fetch` 前统一处理历史待确认项。

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
❯ 获取文献
  历史任务与下载记录
  恢复网站已有求助
  批量采纳历史待确认
  登录账号（密码不保存）
  设置
  环境检查
  退出
```

第一次启动会引导设置下载目录和默认运行模式，并可立即输入科研通邮箱与密码。
密码只用于当次登录请求，不会写入配置、SQLite、日志或命令历史；工具保存的是
网站返回的浏览器会话。遇到验证码时可从登录菜单选择“打开浏览器手动登录”。

TUI 中可以：

- 输入 DOI 或准确标题并下载文献；
- 选择无界面或显示浏览器模式；
- 查看最近 50 条任务、文献信息、PDF 检查结果和事件记录；
- 恢复网站上已经发布的求助；
- 采纳、标记有误或解除遗留任务；
- 修改下载目录、等待时间和高速通道偏好；
- 检查依赖、配置和登录会话目录。

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

## 日常使用

使用 DOI：

```bash
lithelper fetch "10.1038/s41586-024-00000-0"
```

使用准确标题：

```bash
lithelper fetch "Exact title of the paper"
```

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

    task = await app.fetch(
        "10.1016/j.example",
        headless=True,
    )
    print(task.to_dict())
    if task.literature:
        print(task.literature.title)
        print(task.literature.authors)


asyncio.run(main())
```

常用方法：

- `await app.fetch(...)`
- `await app.recover(...)`
- `await app.accept_all()`
- `await app.confirm(task_id)`
- `app.list_tasks()`
- `app.task_details(task_id)`
- `app.reject(task_id, reason=...)`
- `app.cancel(task_id)`

API 默认不打印过程日志。需要日志时传入 `LiteratureHelper(output=print)`。

## Agent 与结构化 CLI

全局 `--json` 让标准输出只包含 JSON，过程日志改写到标准错误，便于 shell、
调度器或其他程序稳定调用：

```bash
lithelper --json --non-interactive fetch "10.xxxx/example"
lithelper --json --non-interactive list
lithelper --json --non-interactive show TASK_ID
```

`--non-interactive` 保证程序不会等待终端输入；`fetch` 会自动使用 Headless 模式。
`recover`、`confirm` 和 `accept-all` 也会无界面运行。登录失效、验证码或必须
人工确认时会立即以非零退出码返回结构化错误。Agent 不应解析或操纵 TUI。

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
├── src/keyantong_helper/      # 0.x Python 导入兼容层，不含业务代码
└── tests/                     # 不访问真实网站的单元与工作流回归测试
```

`selectors.example.json` 只是完整的覆盖示例，程序默认使用 `adapter.py` 内置
选择器，不会自动读取该文件。网站改版时复制它、只修改需要校准的选择器，再把
配置项 `selectors_path` 指向副本即可。`pyproject.toml` 则是 Python 包的唯一
项目清单，集中声明运行依赖、开发依赖、构建方式和 CLI 入口。

这套结构也适合类似的小型 Python 工具：

1. `api.py` 是唯一推荐给外部程序使用的入口；
2. `cli.py` 和 `tui.py` 都只把用户输入转换为 API 调用；
3. `workflow.py` 只编排步骤，不处理终端菜单；
4. 外部网站或服务细节隔离在 `adapter.py`；
5. 输入和输出使用带类型的数据对象；
6. 运行数据放在系统用户目录，不写入源码目录；
7. Agent 只使用非交互 CLI 或 Python API。

这种边界既方便人阅读和测试，也允许未来被任何外部框架包装，而无需改写核心逻辑。

## 配置与数据

`lithelper init` 生成 `config.json`。常用字段：

```json
{
  "download_dir": "/Users/me/Downloads/科研通",
  "browser_channel": "chrome",
  "headless": false,
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
`LITHELPER_HOME` 改变默认数据目录。旧版 `KEYANTONG_HOME` 仍然兼容。

升级用户会继续使用原来的 `keyantong-helper` 数据目录，以保留任务数据库和
浏览器登录会话；全新安装使用 `literature-helper` 数据目录。

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

本工具只面向本人、单篇、个人学习研究用途：

- 优先使用 DOI，标题应准确且唯一；
- 不批量发布、不高频刷新、不替他人求助；
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

## 旧名称兼容

0.x 版本使用过的 `keyantong` 命令、`keyantong_helper` Python 导入和
`Keyantong` 类名暂时保留为兼容别名：

```bash
keyantong list
```

```python
from keyantong_helper import Keyantong
```

新代码统一使用 `lithelper`、`literature_helper` 和 `LiteratureHelper`。兼容层
只转发到新实现，不复制业务代码。
