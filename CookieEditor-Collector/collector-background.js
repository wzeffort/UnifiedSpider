// SPDX-License-Identifier: GPL-3.0-only
// Local collector integration, added 2026-09-20. No cookie values in logs/storage replies.
const LOCAL = new Set(['http://127.0.0.1:18765','http://localhost:18765']);
chrome.runtime.onMessage.addListener((m,s,reply)=>{
  if(m?.source!=='cookie-editor-collector')return false;
  handle(m,s).then(reply).catch(()=>reply({status:'error',message:'Cookie-Editor 本机同步失败，请检查本机服务或重新授权。'}));
  return true;
});
async function handle(m,s){
  const page=new URL(s.url||'about:blank');
  if(!s.tab||s.frameId!==0||!LOCAL.has(page.origin)||page.pathname!=='/')throw Error('Invalid sender');
  if(m.action==='ping')return {status:'connected',version:'1.3.0',provider:'cookie-editor',message:'已连接 Cookie-Editor 本机收集版，可获取当前浏览器已有的本站 Cookie。'};
  if(!['capture','capture-quiet','authorize'].includes(m.action)||typeof m.token!=='string'||m.token.length>200)throw Error('Invalid request');
  const raw=Array.isArray(m.url)?m.url:[m.url];
  if(!raw.length||raw.length>100||raw.some(u=>typeof u!=='string'))throw Error('Invalid URL');
  const urls=raw.map(u=>new URL(u)),target=urls[0];
  if(urls.some(u=>!['http:','https:'].includes(u.protocol)||u.username||u.password||['localhost','127.0.0.1','[::1]'].includes(u.hostname)))return {status:'unsupported',message:'此类网址不读取 Cookie。'};
  if(urls.some(u=>u.origin!==target.origin))throw Error('Mixed sites');
  const approval='collector-approved:'+target.origin;
  const pattern=target.protocol+'//'+target.hostname+'/*';
  const consent=(await chrome.storage.local.get(approval))[approval]===true;
  if(!consent||!(await chrome.permissions.contains({origins:[pattern]}))){
    const key='collector-pending:'+s.tab.id+':'+target.origin;
    let pending=(await chrome.storage.session.get(key))[key];
    if(!pending||pending.expires<Date.now()){
      pending={id:crypto.randomUUID(),origin:target.origin,pattern,approval,tabId:s.tab.id,expires:Date.now()+600000};
      await chrome.storage.session.set({[key]:pending,['collector-request:'+pending.id]:pending});
    }
    if(!pending.opened||m.action==='authorize'){
      let existing=false;
      if(pending.windowId){try{await chrome.windows.get(pending.windowId);existing=true}catch{}}
      if(existing)await chrome.windows.update(pending.windowId,{focused:true});
      else{const w=await chrome.windows.create({url:chrome.runtime.getURL('collector-authorize.html')+'?request='+pending.id,type:'popup',width:450,height:480,focused:true});pending.windowId=w.id}
      pending.opened=true;await chrome.storage.session.set({[key]:pending});
    }
    return {status:'permission',message:'请在 Cookie-Editor 本机授权窗口点击“允许本站连接”，完成后工具会自动获取 Cookie。'};
  }
  if(m.action==='authorize')return {status:'authorized',message:'本站已授权。'};
  const stores=await chrome.cookies.getAllCookieStores();
  const store=stores.find(x=>x.tabIds.includes(s.tab.id));if(!store)throw Error('No store');
  const selected=new Map();
  for(const u of urls)for(const c of await chrome.cookies.getAll({url:u.href,storeId:store.id}))if(!c.partitionKey)selected.set(JSON.stringify([c.domain,c.path,c.name]),c);
  if(!selected.size)return {status:'empty',message:'未获取到本站 Cookie。请确认当前浏览器已登录，或使用手动导入。'};
  const response=await fetch(page.origin+'/api/cookies/import',{method:'POST',credentials:'omit',redirect:'error',headers:{'Content-Type':'application/json','X-Token':m.token},body:JSON.stringify({url:target.href,data:[...selected.values()]}),signal:AbortSignal.timeout(5000)});
  const result=await response.json();
  if(!response.ok)return {status:'error',message:result.error||'本站 Cookie 保存失败。'};
  // Close only this request's extension-owned authorization window, after local save succeeds.
  const pendingKey='collector-pending:'+s.tab.id+':'+target.origin;
  const pending=(await chrome.storage.session.get(pendingKey))[pendingKey];
  if(pending?.windowId){
    try{
      const window=await chrome.windows.get(pending.windowId,{populate:true});
      const expected=chrome.runtime.getURL('collector-authorize.html')+'?request='+pending.id;
      if(window.type==='popup'&&window.tabs?.length===1&&window.tabs[0].url===expected){
        await chrome.windows.remove(pending.windowId);
        await chrome.storage.session.remove([pendingKey,'collector-request:'+pending.id]);
      }
    }catch{} // A user-closed window must not invalidate a successful import.
  }
  return {status:'saved',count:result.cookie_count,message:'Cookie-Editor 已获取并保存本站 '+result.cookie_count+' 条 Cookie；是否登录有效仍需网站确认。'};
}
