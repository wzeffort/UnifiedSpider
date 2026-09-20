// SPDX-License-Identifier: GPL-3.0-only
let request;
const status=document.getElementById('status'),allow=document.getElementById('allow'),revoke=document.getElementById('revoke');
const id=new URL(location.href).searchParams.get('request');
chrome.storage.session.get('collector-request:'+id).then(data=>{
 request=data['collector-request:'+id];
 if(!request||request.expires<Date.now()){status.textContent='请求已过期，请回到工具重新授权。';return}
 document.getElementById('site').textContent='网站：'+request.origin;allow.disabled=false;revoke.disabled=false;
});
allow.onclick=async()=>{
 if(!request||request.expires<Date.now()){status.textContent='请求已过期，请重新授权。';return}
 try{
  const permitted=await chrome.permissions.request({origins:[request.pattern]});
  if(!permitted){status.textContent='尚未允许，未同步 Cookie。';return}
  await chrome.storage.local.set({[request.approval]:true});allow.disabled=true;
  status.textContent='已允许本站连接，正在保存 Cookie。保存成功后此窗口自动关闭；失败时会保留。';
  try{await chrome.tabs.sendMessage(request.tabId,{type:'collector-authorized',origin:request.origin})}catch{status.textContent='授权已保存，请返回工具刷新页面或重新输入网址。'}
 }catch{status.textContent='授权未完成，请检查浏览器的网站访问权限。'}
};
revoke.onclick=async()=>{if(request){await chrome.storage.local.remove(request.approval);allow.disabled=false;status.textContent='已撤销本站与本机工具的连接；不会删除浏览器 Cookie。'}};
