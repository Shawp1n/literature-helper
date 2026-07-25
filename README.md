# Literature Helper

```text
┃  ┛━┏┛┃ ┃┏━┛┃  ┏━┃┏━┛┏━┃
┃  ┃ ┃ ┏━┃┏━┛┃  ┏━┛┏━┛┏┏┛
━━┛┛ ┛ ┛ ┛━━┛━━┛┛  ━━┛┛ ┛
```

[![CI](https://github.com/Shawp1n/literature-helper/actions/workflows/ci.yml/badge.svg)](https://github.com/Shawp1n/literature-helper/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**AI4CAE 原创的个人文献获取工具。** 输入 DOI 或准确标题，Literature Helper
通过科研通完成求助、等待、下载和 PDF 检查，并保存可查询的文献与任务记录。

## 功能

- 方向键 TUI，适合日常交互使用；
- 单篇下载或最多 10 篇的顺序队列；
- 保存科研通智能识别的标题、DOI、期刊、作者和出版日期；
- 检查 PDF 文件头、大小、可读性、页数和 SHA-256；
- 管理历史任务、未完成求助、待确认文件和账号积分；
- 提供 CLI JSON 模式与 Python API，便于脚本和 Agent 接入。

## 快速开始

需要 Python 3.11+、Google Chrome 和本人的科研通账号。

使用 `uv` 安装：

```bash
uv tool install literature-helper
```

也可以直接安装 GitHub 上的当前版本：

```bash
uv tool install "git+https://github.com/Shawp1n/literature-helper.git"
```

启动：

```bash
lithelper
```

首次运行会引导设置下载目录、运行模式和登录账号。

## TUI

```text
❯ 账号管理
  下载文献
  历史记录
  设置
  退出
```

使用 `↑↓` 选择、`Enter` 确认，二级菜单按 `Esc` 返回。

- **账号管理**：登录、积分刷新、积分签到和积分充值；
- **下载文献**：下载单篇或建立顺序队列；
- **历史记录**：查看文献信息和下载结果，恢复任务或处理待确认项；
- **设置**：调整下载目录、浏览器模式、等待时间和下载通道。

## 常用命令

登录与环境检查：

```bash
lithelper doctor
lithelper login
lithelper login --manual-browser
```

获取文献：

```bash
lithelper fetch "10.1038/s41586-024-00000-0"
lithelper fetch "Exact title of the paper"
```

顺序获取多篇：

```bash
lithelper fetch-many \
  "10.1038/s41586-024-00000-0" \
  "Exact title of another paper"
```

查看任务：

```bash
lithelper list
lithelper show TASK_ID
lithelper recover TASK_ID
```

查询积分：

```bash
lithelper points
```

查看全部命令：

```bash
lithelper --help
```

## 三种调用方式

| 方式 | 入口 | 适用场景 |
| --- | --- | --- |
| TUI | `lithelper` | 日常交互 |
| CLI | `lithelper fetch ...` | Shell、CI 和跨语言调用 |
| Python API | `literature_helper.LiteratureHelper` | Python 应用和 Agent Runtime |

三种入口共享同一套业务流程，不会分别维护三份实现。

### Agent / JSON

Agent 应使用非交互 JSON 模式，不解析 TUI：

```bash
lithelper fetch "10.xxxx/example" --format json --non-interactive
lithelper list --format json --non-interactive
```

JSON 结果写入 stdout，过程日志写入 stderr；登录失效、验证码或必须人工确认时
返回非零退出码。

### Python API

```python
import asyncio

from literature_helper import LiteratureHelper


async def main() -> None:
    app = LiteratureHelper()
    task = await app.fetch("10.1016/j.example", headless=True)
    print(task.to_dict())


asyncio.run(main())
```

API 默认静默；需要过程输出时使用 `LiteratureHelper(output=print)`。

## 数据与使用边界

- 密码只用于当次登录，不写入配置、数据库或日志；
- 浏览器会话、任务数据库和诊断材料保存在系统用户数据目录；
- 验证码、签到和充值保留人工操作，不做绕过或自动支付；
- 多篇任务严格串行，面向本人、小规模、学习研究用途；
- 删除本地历史记录不会删除已下载的 PDF 或科研通网站求助。

请勿提交浏览器会话和本地数据。诊断截图可能包含账号、积分和求助信息，分享前
请先脱敏。

## 开发

```bash
git clone https://github.com/Shawp1n/literature-helper.git
cd literature-helper
uv sync --extra dev
uv run --extra dev pytest
uv run lithelper --help
```

项目使用扁平的 `src` 布局。TUI、CLI 和 Python API 通过公共应用门面共享
workflow；网站操作集中在 adapter，任务和接口数据使用明确的类型模型。

## 开源协议与原创性

项目源码采用 [MIT License](LICENSE) 开源，可在协议范围内使用、复制、修改和
分发。

**AI4CAE 是作者原创的技术内容与产品 IP。** Literature Helper 的产品定位、
交互设计和三模态工具模式由 AI4CAE 原创设计与持续维护。MIT License 针对项目
源码，不表示 AI4CAE 名称、标识、视觉形象和品牌表达发生转让。
