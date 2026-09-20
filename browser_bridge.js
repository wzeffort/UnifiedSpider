window.browserCookieBridge = function(action, url, token) {
  const id=crypto.randomUUID();
  return new Promise(resolve=>{
    const finish=result=>{clearTimeout(timer);window.removeEventListener('message', receive);resolve(result);};
    const receive=event=>{if(event.source===window&&event.origin===location.origin&&event.data?.source==='collector-extension'&&event.data.id===id)finish(event.data.result);};
    const timer=setTimeout(()=>finish({status:'unavailable',message:action==='ping'?'未连接配套扩展。请在已安装扩展的浏览器中刷新本工具；普通导出插件不能自动连接。':'浏览器同步超过 8 秒未完成，已停止等待。请重新加载配套扩展并刷新页面，或取消后台同步后使用已导入状态。'}),action==='ping'?1000:8000);
    window.addEventListener('message',receive);
    window.postMessage({source:'collector-page',id,action,url,token},location.origin);
  });
};
