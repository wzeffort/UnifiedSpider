# 测试目录

所有命令从仓库根目录执行，使用已安装项目依赖的 Python 环境。

| 目录 | 用途 | 是否需要运行中的采集服务 |
|---|---|---|
| `unit/` | 存储、查重、导出、Cookie 校验、OCR 调度等组件测试 | 否 |
| `browser/` | 隔离 Chromium、模拟 DOM 和本地测试站点 | 否 |
| `integration/` | 扩展授权、真实接口、网页下载等端到端测试 | 是，使用隔离服务 |

## 默认检查

```sh
python -m unittest discover -s tests/unit -t .
```

部分测试会启动临时 HTTP 服务；MinerU 凭据测试使用 Windows DPAPI，需要 Windows。

## 浏览器检查

先安装 Playwright 及匹配的 Chromium，然后运行：

```sh
python -m unittest tests.browser.test_author_navigation tests.browser.test_author_discovery_browser
python -m unittest tests.browser.test_membership
python -m tests.browser.test_pagination
```

`browser/` 和 `integration/` 不参与默认 unittest 递归发现。部分旧端到端脚本在导入时就会运行，因此按模块显式执行，不对整个 tests 目录运行 pytest 自动收集。

## 服务集成检查

集成测试目前使用 `127.0.0.1:18765`，会写入测试任务与合成 Cookie。先确保该端口没有日常采集服务，再给测试服务和测试进程设置同一个临时 `SPIDER_STATE_ROOT`。

PowerShell 示例，两个终端均先设置同一路径：

```powershell
$env:SPIDER_STATE_ROOT = Join-Path $env:TEMP 'unifiedspider-integration'
$env:SPIDER_PORT = '18765'
# 第一个终端
python app.py --no-browser
# 第二个终端，设置上述环境变量后
python -m tests.integration.test_cookie_editor_bridge
```

其他检查同样使用模块路径，例如 `python -m tests.integration.test_author_batch_extension`。不要连接正在采集的本地服务或云端服务。测试结束后只停止自己启动的测试服务。
