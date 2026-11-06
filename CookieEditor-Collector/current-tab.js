// Explicit popup gesture: read only the selected tab, send its visible DOM to localhost.
const collectButton = document.getElementById('collect-current-tab');
const collectStatus = document.getElementById('collect-current-status');
collectButton.addEventListener('click', async () => {
  collectButton.disabled = true;
  let saved = false;
  let downloadStarted = false;
  try {
    collectStatus.textContent = '正在读取当前标签页…';
    const [tab] = await chrome.tabs.query({active:true, currentWindow:true});
    const source = new URL(tab?.url || 'about:blank');
    if (!['http:', 'https:'].includes(source.protocol) || source.username || source.password ||
        ['localhost','127.0.0.1','[::1]'].includes(source.hostname)) {
      throw Error('请先切换到文章标签页，完成验证并看到正文后再点击。');
    }
    const locals = (await chrome.tabs.query({})).filter(t => {
      try { const u=new URL(t.url); return ['http://127.0.0.1:18765','http://127.0.0.1:18767','http://localhost:18765','http://localhost:18767'].includes(u.origin) && u.pathname==='/'; }
      catch {return false;}
    });
    if (!locals.length) throw Error('请先在同一个浏览器打开本机工具 http://127.0.0.1:18765/，再回文章标签页采集。');
    const localTab = locals.sort((a,b)=>(b.lastAccessed||0)-(a.lastAccessed||0))[0];
    const [{result:snapshot}] = await chrome.scripting.executeScript({target:{tabId:tab.id},func:() => {
      if (!document.body) throw Error('页面尚未加载完成');
      const copy=document.body.cloneNode(true);
      const originals=[document.body,...document.body.querySelectorAll('*')];
      const clones=[copy,...copy.querySelectorAll('*')];
      originals.forEach((node,i)=>{
        const clone=clones[i], style=getComputedStyle(node);
        if (['SCRIPT','STYLE','NOSCRIPT','IFRAME','OBJECT','EMBED','TEMPLATE'].includes(node.tagName) ||
            node.hidden || node.getAttribute('aria-hidden')==='true' || style.display==='none' || style.visibility==='hidden') {
          clone.remove(); return;
        }
        for (const attr of [...clone.attributes]) {
          if (!['id','class','src','data-src','alt','href','title','colspan','rowspan','type','datetime'].includes(attr.name)) clone.removeAttribute(attr.name);
        }
        if(node.tagName==='IMG') {
          const image=node.getAttribute('data-src') || node.currentSrc || node.getAttribute('src');
          if(image) {try{clone.setAttribute('src',new URL(image,document.baseURI).href);clone.removeAttribute('data-src');}catch{}}
        }
        if(node.tagName==='A' && node.href) clone.setAttribute('href',node.href);
      });
      const metadata=[...document.querySelectorAll('meta[name="author"],meta[property="article:published_time"]')].map(n=>{const m=document.createElement('meta');for(const a of ['name','property','content'])if(n.hasAttribute(a))m.setAttribute(a,n.getAttribute(a));return m.outerHTML}).join('');
      const title=document.createElement('title'); title.textContent=document.title;
      return {url:location.href, html:'<!doctype html><html><head>'+title.outerHTML+metadata+'</head>'+copy.outerHTML+'</html>'};
    }});
    if (!snapshot || new TextEncoder().encode(JSON.stringify(snapshot)).length>1900000) throw Error('当前页面内容过大（上限约 1.9 MB），请使用复制正文保存。');
    // Read the token exclusively from the exact local tool page. It is never sent to the source tab.
    const [{result:token}] = await chrome.scripting.executeScript({target:{tabId:localTab.id},world:'MAIN',func:()=>typeof token==='string'?token:null});
    if (!token) throw Error('本机工具连接失效，请刷新本机工具页面后重试。');
    collectStatus.textContent = '正在保存正文…';
    const response=await fetch(new URL(localTab.url).origin+'/api/browser/page',{
      method:'POST',credentials:'omit',redirect:'error',headers:{'Content-Type':'application/json','X-Token':token},
      body:JSON.stringify(snapshot),signal:AbortSignal.timeout(10000)
    });
    const result=await response.json();
    if(!response.ok) throw Error(result.error || '保存失败，请刷新本机工具后重试。');
    saved = true;
    await chrome.scripting.executeScript({target:{tabId:localTab.id},world:'MAIN',args:[result.id],func:async id=>{
      // Download from the local tool's origin using its existing export filename.
      const link=document.createElement('a');
      link.href='/api/export/'+encodeURIComponent(id)+'?format=md';
      link.download='';
      document.body.append(link);
      link.click();
      link.remove();
      // Updating the tool's preview must not prevent a successful download.
      try {await show(id);await refresh();} catch {}
    }});
    downloadStarted = true;
    collectStatus.textContent = '正文已保存，已发起 Markdown 下载。可在浏览器下载列表查看；图片保留原链接。';
  } catch(error) {
    collectStatus.textContent = downloadStarted ? '正文已保存，已发起 Markdown 下载，请在浏览器下载列表查看。' : saved ? '正文已保存，请回本机工具的“以前收集的内容”查看下载。' : (error.message || '采集失败，请确认扩展已更新并允许读取当前标签页。');
  } finally {collectButton.disabled=false;}
});
