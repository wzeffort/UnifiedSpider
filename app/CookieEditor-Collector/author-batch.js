// Local tool requests one bounded browser step at a time. No credentials persist here.
const authorStepLocks = new Set();
const authorNavigationLocks = new Set();

async function pacedAuthorNavigation(local, tabId, url) {
  const host=new URL(url).hostname.replace(/^www\./,'');
  const key='author-navigation:'+local+':'+host;
  if(authorNavigationLocks.has(key))return false;
  authorNavigationLocks.add(key);
  try{
    const last=(await chrome.storage.session.get(key))[key]||0;
    if(Date.now()-last<3000)return false;
    await chrome.storage.session.set({[key]:Date.now()});
    await chrome.tabs.update(tabId,{url});
    return true;
  }finally{authorNavigationLocks.delete(key)}
}

async function prefetchAuthorArticle(local,key,batch) {
  const spareKey=key+':spare', positionKey=spareKey+':position';
  let spare;
  const id=(await chrome.storage.session.get(spareKey))[spareKey];
  if(id){try{spare=await chrome.tabs.get(id)}catch{}}
  if(batch.state!=='running'||batch.phase!=='capture'||batch.article_retry){
    if(spare)await chrome.tabs.update(spare.id,{url:'about:blank'});
    await chrome.storage.session.remove(positionKey);
    return;
  }
  const target=new URL(batch.url);
  if(target.protocol!=='https:'||!['xueqiu.com','www.xueqiu.com','mp.weixin.qq.com'].includes(target.hostname)||target.username||target.password||target.port)return;
  if(!(await chrome.permissions.contains({origins:[target.origin+'/*']})))return;
  if(chrome.runtime.getManifest().name.includes('Cookie-Editor')&&!(await chrome.storage.local.get('collector-approved:'+target.origin))['collector-approved:'+target.origin])return;
  if(!spare){spare=await chrome.tabs.create({url:'about:blank',active:false});await chrome.storage.session.set({[spareKey]:spare.id})}
  if(await pacedAuthorNavigation(local,spare.id,batch.url)){
    await chrome.storage.session.set({[positionKey]:batch.id+':capture:'+batch.url+':retry0'});
  }
}
globalThis.runAuthorBatchStep = async function(message, sender, local) {
  const lock=sender.tab.id;
  if(authorStepLocks.has(lock))return {status:'loading',message:'上一步页面导航或正文提交尚未结束，正在等待。'};
  authorStepLocks.add(lock);
  try{return await runAuthorStep(message,sender,local)}finally{authorStepLocks.delete(lock)}
};
async function runAuthorStep(message, sender, local) {
  if(typeof message.url!=='string' || !/^[\da-f-]{36}$/i.test(message.url) ||
     typeof message.token!=='string' || message.token.length>200) throw Error('Invalid batch');
  const endpoint=local+'/api/authors/'+message.url;
  const response=await fetch(endpoint,{redirect:'error',credentials:'omit'});
  if(!response.ok)throw Error('Unknown batch');
  let batch=await response.json(),captureLease;
  if(batch.state!=='running')return {status:'batch',batch};
  if(batch.capture_claim_supported){
    const workerKey='author-worker-id:'+local+':'+sender.tab.id;
    let worker=(await chrome.storage.session.get(workerKey))[workerKey];
    if(!worker){worker=crypto.randomUUID();await chrome.storage.session.set({[workerKey]:worker})}
    const claimed=await fetch(endpoint+'/claim',{method:'POST',credentials:'omit',redirect:'error',
      headers:{'Content-Type':'application/json','X-Token':message.token},body:JSON.stringify({worker}),signal:AbortSignal.timeout(10000)});
    const result=await claimed.json();
    if(!claimed.ok)return {status:'error',message:result.error||'领取采集任务失败'};
    if(result.status!=='claimed')return result;
    batch=result.batch;captureLease=result.lease;
  }
  if(batch.phase!=='capture'&&Date.now()/1000<batch.not_before)return {status:'batch',batch,retry_after_ms:Math.max(250,Math.min(3000,batch.not_before*1000-Date.now()))};
  if(batch.phase==='capture'&&!batch.article_retry_supported)return {status:'error',message:'请先重启本地爬虫服务以加载失败重试功能，再继续原任务。'};
  const target=new URL(batch.url);
  if(target.protocol!=='https:' || !['xueqiu.com','www.xueqiu.com','mp.weixin.qq.com'].includes(target.hostname) || target.username || target.password || target.port)throw Error('Unsupported site');
  const pattern=target.origin+'/*';
  if(!(await chrome.permissions.contains({origins:[pattern]})))return {status:'permission',message:'请先授权此作者网站，再点击继续。'};
  if(chrome.runtime.getManifest().name.includes('Cookie-Editor') &&
     !(await chrome.storage.local.get('collector-approved:'+target.origin))['collector-approved:'+target.origin])
    return {status:'permission',message:'请先允许本站连接，再点击继续。'};
  // Reuse at most two owned tabs. Only the leased current article may submit.
  const key='author-worker:'+sender.tab.id;
  const stored=(await chrome.storage.session.get(key))[key];
  let tab;
  if(stored){try{tab=await chrome.tabs.get(stored)}catch{}}
  if(!tab){
    tab=await chrome.tabs.create({url:'about:blank',active:false});
    await chrome.storage.session.set({[key]:tab.id});
    await chrome.storage.session.remove(key+':position');
    return {status:'loading',message:'已打开作者采集标签页，等待页面显示。'};
  }
  const positionKey=key+':position';
  const position=batch.id+':'+batch.phase+':'+batch.url+':retry'+(batch.article_retry||0);
  let last=(await chrome.storage.session.get(positionKey))[positionKey];
  if(captureLease&&last!==position){
    const spareKey=key+':spare', sparePosition=spareKey+':position';
    if((await chrome.storage.session.get(sparePosition))[sparePosition]===position){
      const spareId=(await chrome.storage.session.get(spareKey))[spareKey];
      let spare;try{spare=await chrome.tabs.get(spareId)}catch{}
      if(spare){
        await chrome.storage.session.set({[key]:spare.id,[positionKey]:position,[spareKey]:tab.id,[sparePosition]:last});
        tab=spare;last=position;
      }
    }
  }
  if(last!==position){
    if(captureLease){
      if(!(await pacedAuthorNavigation(local,tab.id,batch.url)))return {status:'loading',message:'保持文章访问间隔，稍后打开下一篇。',retry_after_ms:800};
    }else await chrome.tabs.update(tab.id,{url:batch.url});
    await chrome.storage.session.set({[positionKey]:position});
    return {status:'loading',message:'正在打开作者采集页面。'};
  }
  if(tab.url==='about:blank' || tab.pendingUrl || tab.status!=='complete')return {status:'loading',message:'页面正在加载；如需验证，请在采集标签页完成。'};
  const actual=new URL(tab.url);
  if(actual.origin!==target.origin && !(actual.protocol==='https:' && actual.hostname.replace(/^www\./,'')==='xueqiu.com' && target.hostname.replace(/^www\./,'')==='xueqiu.com'))
    return {status:'error',message:'采集标签页已跳转到其他网站，请回到指定作者网站后继续。'};
  if(!(await chrome.permissions.contains({origins:[actual.origin+'/*']})))return {status:'permission',permissionUrl:tab.url,message:'页面跳转到了本站的另一域名，请授权实际页面后继续。'};
  // Loading may overlap the server's submission cooldown; reading/submitting may not.
  if(Date.now()/1000<batch.not_before)return {status:'batch',batch,retry_after_ms:Math.max(250,Math.min(800,batch.not_before*1000-Date.now()))};
  const matchesArticle=value=>{
    try{
      const u=new URL(value);
      if(u.protocol!=='https:')return false;
      if(target.hostname.replace(/^www\./,'')==='xueqiu.com')return u.hostname.replace(/^www\./,'')==='xueqiu.com' && u.pathname.replace(/\/$/,'')===target.pathname.replace(/\/$/,'');
      if(u.origin!==target.origin||u.pathname!==target.pathname)return false;
      return target.pathname==='/s'?['__biz','mid','idx','sn'].every(k=>u.searchParams.get(k)===target.searchParams.get(k)):true;
    }catch{return false}
  };
  const [{result:documentData}]=await chrome.scripting.executeScript({target:{tabId:tab.id},args:[batch.phase],func:phase=>{
    if(!document.body)return null;
    const copy=document.body.cloneNode(true);
    const originals=[document.body,...document.body.querySelectorAll('*')];
    const copies=[copy,...copy.querySelectorAll('*')];
    originals.forEach((node,i)=>{
      const cloned=copies[i],style=getComputedStyle(node);
      if(['SCRIPT','STYLE','NOSCRIPT','IFRAME','OBJECT','EMBED','TEMPLATE'].includes(node.tagName) || node.hidden || node.getAttribute('aria-hidden')==='true' || style.display==='none' || style.visibility==='hidden') {cloned.remove();return;}
      for(const attr of [...cloned.attributes])if(!['id','class','src','data-src','alt','href','title','colspan','rowspan','type','datetime'].includes(attr.name))cloned.removeAttribute(attr.name);
      if(node.tagName==='IMG') {const src=node.getAttribute('data-src')||node.currentSrc||node.getAttribute('src');if(src)try{cloned.setAttribute('src',new URL(src,document.baseURI).href)}catch{}}
    });
    const metadata=[...document.querySelectorAll('meta[name="author"],meta[property="article:published_time"]')].map(n=>{const m=document.createElement('meta');for(const a of ['name','property','content'])if(n.hasAttribute(a))m.setAttribute(a,n.getAttribute(a));return m.outerHTML}).join('');
      const title=document.createElement('title');title.textContent=document.title;
    const links=[...document.querySelectorAll('a[href], [data-link], [data-url]')].filter(n=>n.getClientRects().length).map(n=>{
      try{return new URL(n.getAttribute('href')||n.getAttribute('data-link')||n.getAttribute('data-url'),document.baseURI).href}catch{return '';}
    }).filter(Boolean).slice(0,10000);
    const result={url:location.href,html:'<html><head>'+title.outerHTML+metadata+'</head>'+copy.outerHTML+'</html>',links};
    if(phase==='scan'){
      const visible=n=>n.getClientRects().length && getComputedStyle(n).visibility!=='hidden';
      const disabled=n=>n.disabled || /disabled|--disable/.test(String(n.className)) || n.getAttribute('aria-disabled')==='true' || !!n.closest('.disabled,[aria-disabled="true"]');
      const controls=[...document.querySelectorAll('a,button,[role="button"],.pagination__next,.pagination-next,.load-more,.load_more')].filter(visible);
      const next=controls.find(n=> /^(下一页|下一頁|下页|加载更多|查看更多|更多历史|Next)[\s›»>]*$/i.test((n.getAttribute('aria-label')||n.textContent).trim()) || n.matches('[rel="next"],.pagination__next,.pagination-next') || (n.closest('.pagination,.pager,[role="navigation"]') && /^[›»>]$/.test(n.textContent.trim())));
      const linkNodes=[...document.querySelectorAll('a[href]')].filter(n=>{try{const u=new URL(n.href);return /\/\d+\/\d+/.test(u.pathname)||u.hostname==='mp.weixin.qq.com'}catch{return false}});
      const containers=[...document.querySelectorAll('main,section,div')].filter(n=>n.clientHeight>150 && n.scrollHeight>n.clientHeight+50 && /auto|scroll/.test(getComputedStyle(n).overflowY) && linkNodes.some(a=>n.contains(a)));
      const scroller=containers.sort((a,b)=>b.clientHeight-a.clientHeight)[0]||document.scrollingElement;
      const atBottom=scroller.scrollTop+scroller.clientHeight>=scroller.scrollHeight-60;
      const loading=[...document.querySelectorAll('[aria-busy="true"],.loading,.load-more,.load_more')].some(n=>visible(n)&&(/加载中|正在加载|loading/i.test(n.textContent)||n.getAttribute('aria-busy')==='true'));
      const end=[...document.querySelectorAll('.no-more,.nomore,.load-more,.load_more,.empty,.pagination,.pager,[role="status"]')].some(n=>visible(n)&&/^(没有更多了?[。！!]?|暂无更多[内容文章]*[。！!]?|已到底[了部]*[。！!]?|全部加载完毕|No more.*)$/i.test(n.textContent.trim()));
      const signature=location.href+'|'+links.join('|')+'|'+(document.querySelector('.pagination .active,.pagination__current,[aria-current="page"]')?.textContent||'');
      const previous=window.__collectorScanState||{};
      let action='wait',localNext=true;
      if(next?.href){try{const u=new URL(next.href);localNext=u.origin===location.origin&&u.pathname===location.pathname}catch{localNext=false}}
      if(next && !disabled(next) && localNext && !loading){
        if(previous.signature!==signature || Date.now()-(previous.clickedAt||0)>15000){
          next.scrollIntoView({block:'center'});next.click();action='next';
          window.__collectorScanState={signature,clickedAt:Date.now()};
        }
      }else if(!atBottom&&!loading){scroller.scrollBy(0,Math.max(600,scroller.clientHeight*0.9));action='scroll'}
      result.scan={at_bottom:atBottom,loading,action,progress:action==='scroll',has_next:!!next&&!disabled(next),explicit_end:atBottom&&!loading&&(end||!!next&&disabled(next)),signature};
    }
    return result;
  }});
  if(!documentData)return {status:'loading',message:'等待正文显示。'};
  if(batch.phase==='capture'){
    const latest=await chrome.tabs.get(tab.id);
    if(latest.pendingUrl||latest.status!=='complete'||(latest.url!==documentData.url&&!(matchesArticle(latest.url)&&matchesArticle(documentData.url))))
      return {status:'loading',message:'读取正文期间页面发生导航，已丢弃本次内容，等待页面稳定。'};
  }
  const payload=JSON.stringify({...documentData,revision:batch.revision,...(captureLease?{capture_lease:captureLease}:{})});
  if(new TextEncoder().encode(payload).length>1900000)return {status:'error',message:'当前页面超过约 1.9 MB，请改用单页复制保存。任务可暂停后继续。'};
  const saved=await fetch(endpoint+'/report',{method:'POST',credentials:'omit',redirect:'error',
    headers:{'Content-Type':'application/json','X-Token':message.token},body:payload,signal:AbortSignal.timeout(10000)});
  const result=await saved.json();
  // Preload only after the server accepted the current article. Never preload
  // past a login/verification gate, a retry, or a stale revision.
  if(saved.ok&&captureLease&&(result.processed>batch.processed||result.state!=='running')){
    try{await prefetchAuthorArticle(local,key,result)}catch{/* Normal navigation will retry next time. */}
  }
  if(saved.ok && result.state==='needs_user'){
    await chrome.tabs.update(tab.id,{active:true});
  }
  return saved.ok?{status:'batch',batch:result}:{status:'error',message:result.error||'保存失败，请检查页面后继续。'};
};
