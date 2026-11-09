# 会员页面处理与源码核对

不会仅因页面属于会员资源就自动跳过。已保存本站状态时，使用 Crawl4AI / Playwright 带状态访问；若仍出现解锁提示，保留为需要人工处理的任务，可自行登录有权限的账号、确认全文可见后保存。不会自动登录或付费，也不能保证各站点均能采集。

只含会员属性元数据但已显示全文的页面仍允许提取；仅在文章中讨论“会员”不会被拦截。提示识别是规则判断，仍可能误判，不代表可靠的权限检测。

本地四个项目源码核对：

- EasySpider：`ExecuteStage/easyspider_executestage.py` 的 `add_cookie`，向浏览器装载 Cookie。
- Crawl4AI：`crawl4ai/async_configs.py` 的 `storage_state`、`user_data_dir`；本工具实际使用其浏览器采集接口及状态复用。
- Maxun：`maxun-core/src/interpret.ts` 从当前页面 context 读取本站 Cookie，供工作流判断使用。不是会员解锁逻辑。
- Firecrawl：`apps/api/src/scraper/scrapeURL/lib/request-context.ts` 检查 headers/actions/profile；采集支持请求上下文和页面操作。不是通用会员解锁接口。

没有把四套项目拼装为四引擎轮流冲击限制页面。当前实际后端仍为 FastAPI + Scrapy + Crawl4AI / Playwright。

下载名使用网页标题、采集时间、任务标识；多页增加页数。中文名与四种扩展名同时通过接口响应和前端下载链接设置。已有下载文件不会被重命名。

验证：`test_membership.py` 使用本机测试站验证匿名会员提示保留待处理、有授权 Cookie 后取得正文，并检查公开文章不误伤及动态命名；`test_manual.py` 实际浏览器下载验证中文标题文件名。未使用真实会员账号，未验证具体付费网站。
