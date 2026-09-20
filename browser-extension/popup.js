let pending;
const status = document.getElementById('status'), grant = document.getElementById('grant');
chrome.storage.session.get('pending').then(data => {
  pending = data.pending;
  if (!pending || pending.expires < Date.now()) {status.textContent='请先在本机工具中填写网址并点击“开始收集网页”。';return;}
  status.textContent='请求授权的网站：'+pending.host;
  grant.disabled=false;
});
grant.onclick=async()=>{
  try {
    // Must remain inside this explicit user gesture, never request all sites.
    const allowed=await chrome.permissions.request({origins:[pending.pattern]});
    if (!allowed) {status.textContent='尚未授权，未读取 Cookie。';return;}
    grant.disabled=true;
    await chrome.storage.session.remove('pending');
    await chrome.action.setBadgeText({text:''});
    status.textContent='已授权本站。工具中正在等待的采集会自动继续；如果已取消或超时，请重新点击开始收集。以后无需重复导出或粘贴。';
  } catch {status.textContent='授权未完成，请回到工具重新点击收集后再试。';}
};
