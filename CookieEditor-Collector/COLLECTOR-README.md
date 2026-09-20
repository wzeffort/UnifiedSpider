# Cookie-Editor 本机收集版（非官方修改版）

上游：https://github.com/Moustachauve/cookie-editor
上游提交：9f3f8fb6f7d94985009d612a9cbfd0e7f439d77d
上游版本：1.13.0；修改版：1.13.2；修改日期：2026-09-20。
沿用 GPL-3.0-only，完整许可证见 LICENSE。发行包包含完整可编辑源码和构建配置。本修改版不是 Cookie-Editor 官方发行版，无担保。

## 安装

1. Edge 打开 edge://extensions，Chrome 打开 chrome://extensions。
2. 暂时关闭旧的“网页资料收集助手 · 本机连接”扩展，避免两套桥接同时回应。原商店版 Cookie-Editor 可以先停用，不必卸载。
3. 开启开发人员模式，点击“加载解压缩的扩展”，选择本文件所在文件夹（含 manifest.json）。
4. 在同一个日常浏览器个人资料中打开 http://127.0.0.1:18765/，刷新并输入网址。
5. 首次会弹出 Cookie-Editor 本机授权窗口，点击“允许本站连接”。成功保存到本机后自动关闭该授权窗口，工具显示绿色获取结果；保存失败时不关闭。以后该站点后台同步，不再弹窗。

点击扩展图标仍是原来的 Cookie-Editor，原 Export → JSON、编辑等功能保留。原浏览器网站登录状态不变。
无法静默升级商店版；修改版需单独加载，商店不会自动更新本副本。以后更新本目录后，在扩展管理页重新加载。

## 变更与数据边界

- 新增 manifest.json、collector-background.js、collector-content.js、collector-authorize.html/js；cookie-editor.js 仅新增桥接模块导入。
- 保留原 Cookies API 权限和编辑/导出界面。自动传给采集工具还需按站点独立同意，并不因原有所有网站权限而直接全量导出。
- 只接受本机 18765 根页面的请求，按 URL 过滤 Cookie，使用当前个人资料的 Cookie store，跳过分区 Cookie。
- Cookie 不返回网页消息、不写入扩展存储或日志，仅发给本机带令牌的导入接口。网站授权记录存本机扩展，浏览器本身持有 Cookie。
- Cookie 存在不保证登录有效，也不绕过会员权限或网站限制。
- 要撤销授权，可在该站授权窗口点击撤销，或移除此修改版。工具已有的本地会话副本不随扩展移除而自动删除。
- 可直接加载源码，无需 npm install。附带上游开发配置，未发布、未上传 GitHub、未修改您已安装的商店插件。
