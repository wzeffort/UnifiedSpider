# UnifiedSpider 网页资料收集助手

通过浏览器扩展采集可访问的网页正文，按作者增量保存文章和图片，并用 MinerU 识别图片中的文字与表格，输出适合 RAG 入库的 Markdown 和 JSONL。

## 启动

Windows 日常使用只需双击根目录 **`start.bat`**。默认本机地址为 `http://127.0.0.1:18765/`。

启动脚本使用 `D:\Anaconda\envs\spider-crawl4ai\python.exe`；换电脑后修改脚本中的 Python 路径。首次安装或修复依赖使用 `scripts/install.bat`，启动过程不会自动安装软件。

新建 Conda 环境：

```powershell
cd config
conda env create -f environment.yml
cd ..
```

已有 Python 环境也可以直接运行：

```sh
python -m pip install -r config/requirements.txt
python -m playwright install chromium
python app/app.py
```

## 浏览器扩展

1. 打开工具网页，下载页面提供的 Cookie-Editor 收集版 ZIP。
2. 解压，在 Edge / Chrome 的扩展管理页面加载解压后的目录。
3. 保持工具与目标网站在同一个浏览器个人资料中，刷新工具页面。
4. 首次采集站点时允许连接；Cookie 保存成功后授权窗口自动关闭。遇到登录或验证码时，由用户在网页完成。

当前 Cookie-Editor 收集版为 **1.14.8**，源码位于 `app/CookieEditor-Collector/`；独立采集扩展位于 `app/browser-extension/`。两者选择一个启用，避免重复响应。Cookie-Editor 是非官方修改版，其 GPL-3.0-only 许可与上游说明保留在扩展目录内。

扩展只连接已允许的本机工具地址，不会把浏览器全部站点的 Cookie 打包上传。使用 SSH 转发时，本站 Cookie 实际保存到对应云端服务的 `sessions/`，不要公开该目录。

## 按作者采集

- 输入雪球作者主页，或微信公众号可访问的历史列表、合集链接，每行一个。
- **首次采集选“补齐历史”**；日常获取新文章选“快速增量更新”。
- 同一作者已有文章会按链接查重；已识别的相同图片复用 OCR 缓存。
- 勾选自动处理后，图片识别与采集可交错进行，处理完成后自动导出。
- 验证、页面异常或列表加载停滞会显示具体状态；“正文已入库”“图片识别”“已导出”是不同阶段。

历史采集只包含已经发现且可访问的内容，不保证拿到作者全部历史。删除、登录限制、付费和验证页面不会被当作完整正文保存。会员内容限制见 [docs/MEMBERSHIP.md](docs/MEMBERSHIP.md)。

## 保存与 RAG

保存目录由页面设置。同一作者使用一个稳定目录，例如 `雪球_行中衡/`；名称暂不可用时先用账号编号，取得名称后改名，内部仍按账号 ID 查重。同名作者会区分目录。

每个作者目录包含：

- `documents.jsonl`：每行一篇文章，包含正文、来源、作者、日期与图片识别信息。
- `*.md`：便于阅读的正文及 OCR 结果。
- `images/`：已下载图片。
- `export.json`：导出状态、数量与文件校验信息。

RAG 导入优先读取 `documents.jsonl`，使用 `document_id` 更新已有文章；不要同时把 JSONL 与 Markdown 重复入库。先检查 `export.json` 的 `ready=true`，并确认读取前后 `generation` 一致。OCR 是机器识别，尤其数字、公式和表格需要核验。

应用内部使用 SQLite 保存任务文章与查重记录，不是 MySQL，也不是向量数据库。向量化、分块及检索由下游 RAG 项目完成。

## AutoDL

已配置的云端爬虫监听 **8889**。在 VS Code Remote SSH 的端口面板转发 `8889`，本地端口也用 `8889`，然后打开 `http://127.0.0.1:8889/`。

- 运行数据：`/root/autodl-tmp/unifiedspider/state/data`
- 作者导出：`/root/autodl-tmp/unifiedspider/rag`
- 图片处理：自部署 MinerU 与官方 API 两路分配不同图片，各一路并发，共享缓存。
- 网页采集仍依赖本地浏览器与转发连接；图片处理和导出在服务器运行。

具体部署脚本、依赖与密钥存放要求见 [deploy/AUTODL.md](deploy/AUTODL.md)。云端仅部署已提交的版本，密钥、Cookie、模型和用户资料不提交 Git。

## 项目结构

```text
UnifiedSpider/
├── start.bat          # Windows 日常启动入口
├── README.md
├── app/               # Python 服务、网页资源与浏览器扩展
├── config/            # Python / Conda 依赖配置
├── scripts/           # 安装与离线包构建脚本
├── deploy/            # AutoDL 部署脚本和说明
├── tests/
│   ├── unit/          # 不依赖运行中服务的组件测试
│   ├── browser/       # 隔离浏览器与模拟网页测试
│   └── integration/   # 独立测试服务上的端到端检查
└── docs/              # 补充说明与历史验证记录
```

本地原有 `data/`、`sessions/` 和 `browser_profiles/` 仍位于项目根目录，不随代码整理搬动。设置 `SPIDER_STATE_ROOT` 可把运行数据放在独立目录；它们都不会提交 Git。

## 开发与测试

从仓库根目录执行：

```sh
python -m unittest discover -s tests/unit -t .
python -m unittest tests.browser.test_author_navigation tests.browser.test_author_discovery_browser
```

端到端测试需要隔离服务和数据目录，不要连接日常采集服务。详细命令见 [tests/README.md](tests/README.md)。离线 Windows 打包脚本位于 `scripts/`，使用前检查其中的环境与浏览器路径。
