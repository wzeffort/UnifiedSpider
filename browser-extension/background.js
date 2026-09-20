const LOCAL = new Set(['http://127.0.0.1:18765', 'http://localhost:18765']);
function sourceOrigin(sender) {
  const u = new URL(sender.url || 'about:blank');
  if (sender.frameId !== 0 || !sender.tab || !LOCAL.has(u.origin) || u.pathname !== '/') throw Error('Invalid sender');
  return u.origin;
}
async function handle(message, sender) {
  const local = sourceOrigin(sender);
  if (message.action === 'ping') {
    const ua = navigator.userAgent;
    const browser = /Edg\//.test(ua) ? 'Microsoft Edge' : /Chrome\//.test(ua) ? 'Google Chrome / Chromium' : '当前浏览器';
    return {status:'connected', browser, version:chrome.runtime.getManifest().version,
      message:`已连接 ${browser} 的配套扩展，收集时将后台同步当前个人资料中的本站 Cookie。`};
  }
  if (!['capture','capture-quiet','authorize'].includes(message.action) || typeof message.token !== 'string' || message.token.length > 200) throw Error('Invalid request');
  const inputs = Array.isArray(message.url) ? message.url : [message.url];
  if (!inputs.length || inputs.length > 100 || inputs.some(u => typeof u !== 'string')) throw Error('Invalid URLs');
  const urls = inputs.map(u => new URL(u)), url = urls[0];
  if (urls.some(u => !['http:', 'https:'].includes(u.protocol) || u.username || u.password || ['localhost','127.0.0.1','[::1]'].includes(u.hostname))) return {status:'unsupported', message:'此类网址不读取浏览器 Cookie。'};
  if (urls.some(u => u.origin !== url.origin)) throw Error('Mixed origins');
  const pattern = `${url.protocol}//${url.hostname}/*`;
  if (!(await chrome.permissions.contains({origins:[pattern]}))) {
    if(message.action==='capture-quiet')return {status:'permission',message:`${url.hostname} 尚未授权。点击“授权本站并同步”即可沿用当前浏览器登录状态，也可以手动导入 Cookie。`};
    // Store only a website permission request, never a cookie or local API token.
    const {pending:previous} = await chrome.storage.session.get('pending');
    let windowExists=false;
    if(previous?.pattern===pattern && previous.tabId===sender.tab.id && previous.windowId){
      try{await chrome.windows.get(previous.windowId);windowExists=true}catch{}
    }
    if(!windowExists || message.action==='authorize'){
      const pending={pattern,host:url.hostname,tabId:sender.tab.id,expires:Date.now()+600000};
      await chrome.storage.session.set({pending});
      await chrome.action.setBadgeText({text:'授权'});
      // An extension page opens first; the browser permission prompt still requires a click.
      // Do not reopen a dismissed window on every polling tick.
      if(message.action==='authorize'||!previous||previous.pattern!==pattern||previous.tabId!==sender.tab.id||previous.expires<Date.now()){
        try{
          if(windowExists){await chrome.windows.update(previous.windowId,{focused:true});pending.windowId=previous.windowId}
          else {const w=await chrome.windows.create({url:chrome.runtime.getURL('popup.html'),type:'popup',width:410,height:440,focused:true});pending.windowId=w.id}
          await chrome.storage.session.set({pending});
        }catch{}
      }
    }
    return {status:'permission', message:`等待授权 ${url.hostname}：请在授权窗口点击“允许后台获取本站 Cookie”，再确认浏览器提示。如未看到窗口，点击下方“打开授权窗口”。`};
  }
  if(message.action==='authorize')return {status:'authorized',message:'本站已授权，将继续同步。'};
  // Read only cookies applicable to this URL from this browser profile's store.
  const stores = await chrome.cookies.getAllCookieStores();
  const store = stores.find(s => s.tabIds.includes(sender.tab.id));
  if (!store) throw Error('Cookie store unavailable');
  const selected = new Map();
  for (const target of urls) {
    for (const cookie of await chrome.cookies.getAll({url:target.href, storeId:store.id})) {
      if (!cookie.partitionKey) selected.set(JSON.stringify([cookie.domain,cookie.path,cookie.name]),cookie);
    }
  }
  const cookies = [...selected.values()];
  if (!cookies.length) return {status:'empty', message:'当前浏览器未找到适用于此网址的 Cookie。公开页面可直接采集；需登录的页面请先在当前浏览器登录。'};
  const response = await fetch(local+'/api/cookies/import', {
    method:'POST', credentials:'omit', redirect:'error',
    headers:{'Content-Type':'application/json', 'X-Token':message.token},
    body:JSON.stringify({url:url.href, data:cookies}), signal:AbortSignal.timeout(5000)
  });
  const result = await response.json();
  if (!response.ok) return {status:'error', message:result.error || '本站状态未保存，请刷新后重试。'};
  // Never return cookie values to the web page, popup, logs or extension storage.
  return {status:'saved', count:result.cookie_count, message:`已从当前浏览器后台同步本站 ${result.cookie_count} 条 Cookie。是否登录有效仍需网站确认。`};
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  handle(message, sender).then(reply).catch(() => reply({status:'error', message:'后台同步未完成，请确认网站授权与本机服务，刷新后再试。'}));
  return true;
});
