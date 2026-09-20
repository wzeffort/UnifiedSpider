// SPDX-License-Identifier: GPL-3.0-only
// Modified distribution: local collector bridge, 2026-09-20.
if(['http://127.0.0.1:18765','http://localhost:18765'].includes(location.origin)&&location.pathname==='/'){
 window.addEventListener('message',async e=>{
  const m=e.data;
  if(e.source!==window||e.origin!==location.origin||m?.source!=='collector-page'||typeof m.id!=='string'||!['ping','capture','capture-quiet','authorize'].includes(m.action))return;
  let result;try{result=await chrome.runtime.sendMessage({source:'cookie-editor-collector',action:m.action,url:m.url,token:m.token})}catch{result={status:'error',message:'Cookie-Editor 连接失效，请刷新页面。'}}
  window.postMessage({source:'collector-extension',id:m.id,result},location.origin);
 });
 chrome.runtime.onMessage.addListener((m,s)=>{
  if(s.id===chrome.runtime.id&&m?.type==='collector-authorized')window.postMessage({source:'collector-extension-permission',origin:m.origin},location.origin);
 });
}
