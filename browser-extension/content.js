// The bridge is active only on the collector's exact local origin and root page.
if (['http://127.0.0.1:18765', 'http://localhost:18765'].includes(location.origin) && location.pathname === '/') {
  window.addEventListener('message', async event => {
    const m = event.data;
    if (event.source !== window || event.origin !== location.origin || !m || m.source !== 'collector-page' || !['ping', 'capture','capture-quiet','authorize'].includes(m.action) || typeof m.id !== 'string') return;
    let result;
    try { result = await chrome.runtime.sendMessage({action:m.action, url:m.url, token:m.token}); }
    catch { result = {status:'unavailable', message:'配套扩展连接已失效，请刷新页面。'}; }
    window.postMessage({source:'collector-extension', id:m.id, result}, location.origin);
  });
}
