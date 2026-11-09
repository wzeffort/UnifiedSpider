(() => {
  const panel=document.getElementById('authorTasks');
  const monitor=new URLSearchParams(location.search).get('view')==='progress';
  let driving=false, stopped=false, resumeQueued=false, starting=false, pausing=false, connected=false;
  const overview=document.createElement('div');overview.id='authorOverview';overview.className='status';overview.setAttribute('role','status');
  panel.before(overview);
  const outputRunning=t=>t.enrichment?.state==='running'||['queued','recognizing','saving'].includes(t.auto_state);
  function controls(){
    const running=lastTasks.filter(t=>t.state==='running'), output=lastTasks.filter(outputRunning);
    const waiting=lastTasks.filter(t=>t.state==='needs_user');
    const locked=starting||pausing||!connected||running.length>0||waiting.length>0;
    const start=document.getElementById('authorStart');
    start.disabled=locked;
    start.textContent=starting?'正在启动任务…':!connected?'正在连接服务…':running.length?'正在跑任务…':waiting.length?'请先处理待继续任务':'开始批量收集';
    document.getElementById('authorPauseAll').disabled=pausing||!connected||!running.length;
    document.getElementById('authorPauseAll').textContent=pausing?'正在暂停…':'暂停正文采集';
    for(const id of ['authorUrls','authorScanMode','authorLimit','authorSaveMode','authorSaveFolder','authorChooseFolder','authorApplyFolder','authorAutoDownload'])document.getElementById(id).disabled=locked;
    overview.style.borderLeft='5px solid '+(!connected||waiting.length?'#c87b16':running.length||output.length?'#087f8c':'#708090');
    overview.textContent=!connected?'连接中或连接中断，无法确认任务状态；请勿重复启动。':
      starting?'正在创建任务，请稍候…':
      running.length?`正在跑任务：${running.length} 个采集任务${output.length?'，图片识别同时进行':''}。`+(driving?'请保持本页打开。':'本页没有驱动采集；若其他工具页正在采集请保留，否则在任务下点击“在本页继续采集”。'):
      output.length?`正文采集当前未运行，可以开始新作者。后台有 ${output.length} 个图片或导出任务，继续独立处理，不占用正文采集。`:
      waiting.length?`当前未运行采集：${waiting.length} 个任务等待人工处理。请点击任务的“继续”，或“停止发现，下载已发现文章”；不要重复创建任务。`:
      lastTasks.some(t=>t.state==='paused')?'当前没有任务运行。已暂停的任务可在历史记录中继续。':'当前没有任务运行。';
    if(waiting.length&&(running.length||output.length))overview.textContent+=` 另有 ${waiting.length} 个任务等待人工处理。`;
  }
  function taskProgress(task,host){
    host.replaceChildren();
    const heading=document.createElement('strong'),bar=document.createElement('progress'),detail=document.createElement('div');
    bar.max=100;bar.style.cssText='display:block;width:100%;height:18px;margin:8px 0;accent-color:#087f8c';
    const active=task.state==='running', output=outputRunning(task), counts=imageMetrics.get(task.id)?.counts;
    let label, note, value;
    if(task.state==='cancelled'){
      label=output?'已停止采集 · 正在自动保存已有资料':'已取消任务 · 已采集数据保留';if(!output)value=0;note=output?'等待当前图片处理收尾，再合并到作者目录。':'不会继续采集；新任务会跳过已入库文章。';
    }else if(task.state!=='finished'){
      const prefix=active?'正在采集':task.state==='needs_user'?'已暂停，等待人工处理':'已暂停';
      if(task.phase==='scan'){
        label=prefix+' · 查找文章';note=`已发现 ${task.discovered} 篇待采集，跳过 ${task.skipped_existing||0} 篇旧文。历史总量未知，不显示虚假百分比。`;
        if(!active)value=0;
      }else{
        label=prefix+' · 保存正文';value=task.discovered?Math.min(100,100*(task.processed||0)/task.discovered):0;
        note=`正文处理 ${task.processed||0} / ${task.discovered} 篇（含跳过），实际入库 ${task.saved} 篇。`;
      }
      if(output)note+=' 图片仍在后台处理。';
    }else if(output){
      label=task.auto_state==='saving'?'正在保存到目录':task.auto_state==='queued'?'等待图片处理队列':'正在识别图片';
      note='正文采集已结束，资料尚在处理。';
      if(counts&&task.auto_state!=='saving'&&task.auto_state!=='queued'){
        value=counts.total?100*counts.complete/counts.total:0;
        note=`图片已识别 ${counts.complete} / ${counts.total} 张，异常 ${counts.failed} 张；按最近一次统计，覆盖 ${counts.pages} 篇正文。`;
      }
    }else if(['failed','partial'].includes(task.auto_state)||['failed','interrupted'].includes(task.enrichment?.state)){
      label='处理未全部成功 · 当前未运行';value=0;note=task.auto_message||task.enrichment.message||'请查看错误并重试。';
    }else{
      label=task.last_export?'本轮已完成并导出':task.saved?'正文采集完成':'本轮检查完成，无新增正文';value=100;
      note=task.last_export?`本任务已导出 ${task.last_export.documents_count} 篇。`:task.saved?'请查看下方导出状态。':'没有启动图片识别或重复导出。';
    }
    heading.textContent=label;detail.textContent=note;detail.className='hint';bar.setAttribute('aria-label',label);
    if(value!==undefined)bar.value=value;
    host.append(heading,bar,detail);
  }
  const labels={paused:'已暂停',running:'进行中',needs_user:'等待人工处理',finished:'本轮结束',cancelled:'已取消（数据保留）'};
  const status=text=>document.getElementById('authorStatus').textContent=String(text||'').replace(/已保存 (\d+) 篇/g,'正文已入库 $1 篇');
  const saveStatus=text=>document.getElementById('authorSaveStatus').textContent=text;
  function renderSettings(config){
    document.getElementById('authorSaveMode').value=config.mode;
    document.getElementById('authorSaveFolder').value=config.folder;
    saveStatus(config.mode==='folder'?'已应用本机保存目录：'+config.folder:'浏览器下载位置由浏览器设置决定。选择文件夹并应用后，可直接保存到显示的本机路径。');
  }
  async function saveTask(id){
    const exported=await api('/api/authors/'+id+'/save',{});
    status('资料已保存到：'+exported.folder+'；RAG 数据文件：'+exported.documents_file);
    await list();
    return exported;
  }
  async function autoDownload(task){
    if(monitor)return;
    if(task.auto_after && !['done','partial'].includes(task.auto_state))return;
    if(task.auto_after && task.last_export)return;
    if(task.auto_after && task.output_mode==='folder')return;
    if(task.state!=='finished'||!task.saved||(!task.auto_after&&!document.getElementById('authorAutoDownload').checked))return;
    const config=task.auto_after?{mode:task.output_mode,folder:''}:await api('/api/download-settings');
    const key='author-exported:'+JSON.stringify([task.id,task.revision,config.mode,config.folder]);
    if(localStorage.getItem(key))return;
    if(config.mode==='folder'){
      await saveTask(task.id);localStorage.setItem(key,'saved');return;
    }
    const link=document.createElement('a');link.href='/api/authors/'+task.id+'/download';link.download='';document.body.append(link);link.click();link.remove();
    localStorage.setItem(key,'requested');
    status(task.message+' 已发起合集 ZIP 下载，可按 Ctrl+J 查看。');
  }
  const imageMetrics=new Map();
  function metricText(task){
    const metric=imageMetrics.get(task.id);
    const state=task.enrichment?.state;
    const running=state==='running';
    if(!metric?.counts)return '图片识别：'+(metric?.error?'统计暂不可用，将自动重试':task.saved?'正在读取累计进度…':'等待正文入库');
    const c=metric.counts;
    return `图片识别：已识别 ${c.complete} / ${c.total} 张，待处理 ${c.pending} 张，异常 ${c.failed} 张；已下载 ${c.downloaded} 张。有图文章已完成 ${c.pagesComplete} / ${c.pagesWithImages} 篇。`+
      (running?'后台正在处理。':'')+`（${metric.time} 统计，覆盖已入库 ${c.pages} 篇）`+(metric.error?' 最新统计暂不可用，保留上次结果。':'');
  }
  function renderMetrics(task,node){
    node.textContent=metricText(task);
    if(!task.saved)return;
    const previous=imageMetrics.get(task.id);
    if(previous?.loading||Date.now()-(previous?.at||0)<30000)return;
    imageMetrics.set(task.id,{...previous,loading:true,at:Date.now()});
    api('/api/result/'+task.id).then(result=>{
      const c={total:0,complete:0,pending:0,failed:0,downloaded:0,pages:result.pages.length,pagesWithImages:0,pagesComplete:0};
      for(const page of result.pages){const images=page.images||[];if(images.length)c.pagesWithImages++;
        if(images.length&&images.every(i=>i.ocr&&!i.error))c.pagesComplete++;
        for(const image of images){c.total++;if(image.file)c.downloaded++;if(image.error)c.failed++;else if(image.ocr)c.complete++;else c.pending++}
      }
      imageMetrics.set(task.id,{counts:c,at:Date.now(),time:new Date().toLocaleTimeString(),loading:false});
    }).catch(()=>imageMetrics.set(task.id,{...previous,at:Date.now(),loading:false,error:true})).finally(()=>{
      const current=panel.querySelector('[data-task-id="'+task.id+'"] [data-image-progress]');
      if(current)current.textContent=metricText(task);
      const progress=panel.querySelector('[data-task-id="'+task.id+'"] [data-stage-progress]');
      const latest=lastTasks.find(t=>t.id===task.id);if(progress&&latest)taskProgress(latest,progress);
    });
  }
  function exportText(task){
    if(task.state==='cancelled'&&!task.last_export)return task.saved?'任务已取消；已入库正文仍保留，可点击“保存资料”导出。':'任务已取消，没有待导出的正文。';
    if(task.state==='finished'&&!task.saved)return '本轮无新增正文，不重复识别或导出；已有作者资料保留在原目录。';
    if(!task.last_export)return '已导出：0 篇（本任务尚未写入所选目录）'+(task.auto_after?'；等待采集与识别完成后自动导出。':'。');
    const last=task.last_export;
    const count=last.documents_count??0;
    const time=last.exported_at?new Date(last.exported_at).toLocaleString():'';
    const changed=last.revision!==task.revision||count!==task.saved||['streaming','queued','recognizing','saving'].includes(task.auto_state);
    return `已导出：${count} 篇 · ${time}`+(last.author_documents_count!==undefined?`；该作者目录累计 ${last.author_documents_count} 篇（截至此次导出）`:'')+(changed?'（上次导出快照，当前新增正文或识别结果尚未全部导出）':'（与当前任务版本一致）')+'。浏览器下载不计入此目录确认数量。';
  }
  let historyLimit=20, listing=false, lastTasks=[];
  const opened=new Set();
  function details(id,title){
    const el=document.createElement('details');el.dataset.detailId=id;el.open=opened.has(id);
    const summary=document.createElement('summary');summary.textContent=title;el.append(summary);
    el.addEventListener('toggle',()=>{if(el.isConnected){if(el.open)opened.add(id);else opened.delete(id)}});
    return el;
  }
  async function list(){
    while(listing)await new Promise(resolve=>setTimeout(resolve,50));
    listing=true;
    try{
      const tasks=await api('/api/authors');lastTasks=tasks;connected=true;controls();
      for(const el of panel.querySelectorAll('details[data-detail-id]')){if(el.open)opened.add(el.dataset.detailId);else opened.delete(el.dataset.detailId)}
      panel.replaceChildren();
      const active=tasks.filter(t=>['running','needs_user'].includes(t.state)||t.enrichment?.state==='running'||['queued','recognizing','saving','failed','partial'].includes(t.auto_state));
      const capturing=active.filter(t=>['running','needs_user'].includes(t.state));
      const background=active.filter(t=>!capturing.includes(t));
      const past=tasks.filter(t=>!active.includes(t)).sort((a,b)=>b.created.localeCompare(a.created));
      function render(task,parent,compact){
        const label=`${task.source.platform==='wechat'?'微信公众号':'雪球作者 '+task.source.owner} · ${labels[task.state]||task.state} · 正文已入库 ${task.saved} 篇 · 跳过 ${task.skipped_existing||0} 篇已有文章`;
        const row=compact?details(task.id,label):document.createElement('div');row.className='job';row.dataset.taskId=task.id;
        if(!compact){const title=document.createElement('strong');title.textContent=label;row.append(title)}
        const body=document.createElement('div');row.append(body);
        const progress=document.createElement('div');progress.dataset.stageProgress='';taskProgress(task,progress);body.append(progress);
        const description=document.createElement('p');description.className='hint';description.textContent=String(task.message||'').replace(/已保存 (\d+) 篇/g,'正文已入库 $1 篇')+(task.discovery_reason?'（'+task.discovery_reason+'）':'');body.append(description);
        const stored=document.createElement('p');stored.className='hint';stored.textContent=`正文已入库：${task.saved} 篇 / 本轮发现 ${task.discovered} 篇；跳过 ${task.skipped_existing||0} 篇已有文章。入库位置是本机数据库。`;body.append(stored);
        const imageProgress=document.createElement('p');imageProgress.className='hint';imageProgress.dataset.imageProgress='';body.append(imageProgress);
        if(!compact||opened.has(task.id))renderMetrics(task,imageProgress);else imageProgress.textContent='图片识别：展开任务后读取累计进度。';
        const exported=document.createElement('p');exported.className='hint';exported.dataset.exportProgress='';exported.textContent=exportText(task);body.append(exported);
        if(compact)row.addEventListener('toggle',()=>{if(row.open)renderMetrics(task,imageProgress)});
        const more=details(task.id+':more','详情与其他操作');
        const source=document.createElement('p');source.className='hint';source.textContent=task.source.url+' · '+task.created+' · 发现 '+task.discovered+' 篇';more.append(source);
        const busy=(task.enrichment?.state==='running'&&task.auto_state!=='streaming')||['queued','recognizing','saving'].includes(task.auto_state);
        const action=(name,fn,target=body)=>{if(monitor)return;const button=document.createElement('button');button.textContent=name;button.disabled=busy;button.onclick=async()=>{button.disabled=true;try{await fn()}catch(e){status(e.message)}finally{button.disabled=busy}};target.append(button)};
        if(!['finished','cancelled'].includes(task.state)){
          action('取消任务（保留数据）',async()=>{
            const health=await api('/health');
            if(!health.author_cancel)throw Error('取消按钮需要重新启动后端后生效；不会删除任何已采集数据。');
            await api('/api/authors/'+task.id+'/control',{action:'cancel'});
            if(pendingAuthorization?.task.id===task.id)pendingAuthorization=null;
            status('任务已取消，正文、图片及查重记录保留。可以开始其他任务。');await list();
          });
          if(task.state==='running'){
            action('暂停',async()=>{await api('/api/authors/'+task.id+'/control',{action:'pause'});await list()});
            if(!driving)action('在本页继续采集',async()=>{stopped=false;drive()});
          }
          else action('继续',async()=>{stopped=false;await api('/api/authors/'+task.id+'/control',{action:'resume'});drive()});
          if(task.phase==='capture')action('跳过当前文章',async()=>{stopped=false;await api('/api/authors/'+task.id+'/control',{action:'skip'});drive()},more);
          action('授权本站',()=>authorizeTask(task,task.source.url),more);
          if(task.phase==='scan')action('停止发现，下载已发现文章',async()=>{stopped=false;await api('/api/authors/'+task.id+'/control',{action:'finish-scan'});drive()},more);
        }
        if(['failed','interrupted'].includes(task.enrichment?.state)){
          const issue=document.createElement('p');issue.className='hint';issue.textContent='图片处理提示：'+(task.enrichment.message||'处理未完成');body.append(issue);
        }
        if(task.auto_message){const message=document.createElement('p');message.className='hint';message.textContent=task.auto_message;body.append(message)}
        if(task.state!=='cancelled'&&['failed','partial'].includes(task.auto_state))action('重试识别并保存',async()=>{await api('/api/authors/'+task.id+'/control',{action:'retry-output'});await list()});
        if(task.state==='finished')action('继续发现历史',async()=>{stopped=false;await api('/api/authors/'+task.id+'/control',{action:'rescan'});drive()},more);
        if(task.saved && task.state!=='running' && task.auto_state!=='streaming'){
          action('识别图片（MinerU）',async()=>{await api('/api/authors/'+task.id+'/enrich',{ocr:true});await list()});
          action('仅下载图片',async()=>{await api('/api/authors/'+task.id+'/enrich',{ocr:false});await list()},more);
        }
        if(task.saved && task.auto_state!=='streaming'){
          action('保存资料',async()=>{const config=await api('/api/download-settings');if(config.mode==='folder')await saveTask(task.id);else{const a=document.createElement('a');a.href='/api/authors/'+task.id+'/download';a.download='';document.body.append(a);a.click();a.remove()} });
          action('保存到本机目录',()=>saveTask(task.id),more);
          if(!busy&&!monitor){const link=document.createElement('a');link.className='download';link.textContent='下载资料包（Markdown＋JSONL）';link.href='/api/authors/'+task.id+'/download';more.append(link)}
        }
        if(task.last_export){const location=document.createElement('p');location.className='hint';location.textContent='上次导出目录：'+task.last_export.folder;more.append(location);action('打开任务目录',()=>api('/api/authors/'+task.id+'/open-export',{}),more)}
        body.append(more);parent.append(row);
      }
      if(!capturing.length){const empty=document.createElement('p');empty.className='hint';empty.textContent='当前没有正文采集任务，可以开始采集新作者。历史任务与图片处理进度见下方。';panel.append(empty)}
      capturing.forEach(t=>render(t,panel,false));
      if(background.length){
        const queue=document.createElement('section');queue.id='authorOutputQueue';
        const title=document.createElement('h3');title.textContent='图片与导出队列（'+background.length+'）';
        const note=document.createElement('p');note.className='hint';note.textContent='后台按队列识别图片并自动保存，不阻塞新作者采集。无需反复点击识别；暂停正文采集也不会停止此队列。';
        queue.append(title,note);background.forEach(t=>render(t,queue,false));panel.append(queue);
      }
      if(past.length){const history=details('history','历史任务（'+past.length+'）');history.id='authorHistory';past.slice(0,historyLimit).forEach(t=>render(t,history,true));if(past.length>historyLimit){const button=document.createElement('button');button.className='secondary';button.textContent='显示更多';button.onclick=()=>{historyLimit+=20;list()};history.append(button)}panel.append(history)}
      for(const task of tasks)if(task.auto_after&&['done','partial'].includes(task.auto_state)&&!task.last_export)await autoDownload(task);
      return tasks;
    }catch(e){connected=false;controls();throw e}finally{listing=false}
  }
  let pendingAuthorization=null, finishingAuthorization=false;
  async function finishAuthorization(){
    if(!pendingAuthorization||finishingAuthorization||stopped)return;
    finishingAuthorization=true;
    const pending=pendingAuthorization;
    try{
      const captured=await browserCookieBridge('capture-quiet',pending.url,token);
      if(!['saved','empty','authorized'].includes(captured.status)){
        status(captured.message||'授权尚未完成，请重试。');showAuthorizationActions(pending);return;
      }
      if(stopped||pendingAuthorization!==pending)return;
      pendingAuthorization=null;
      await api('/api/authors/'+pending.task.id+'/control',{action:'resume'});
      status(captured.status==='saved'?'本站 Cookie 已同步，正在继续采集。':'本站已授权，正在使用浏览器当前登录状态继续采集。');
      drive();
    }catch(e){status(e.message);showAuthorizationActions(pending)}finally{finishingAuthorization=false}
  }
  function showAuthorizationActions(pending){
    const retry=document.createElement('button');retry.textContent='打开授权窗口';
    retry.onclick=()=>authorizeTask(pending.task,pending.url).catch(e=>status(e.message));
    const resume=document.createElement('button');resume.textContent='已允许，继续采集';
    resume.onclick=()=>finishAuthorization();
    document.getElementById('authorStatus').append(document.createElement('br'),retry,resume);
  }
  async function authorizeTask(task,url){
    stopped=false;
    const pending={task,url};pendingAuthorization=pending;
    const reply=await browserCookieBridge('authorize',url,token);
    if(pendingAuthorization!==pending)return;
    if(reply.status==='authorized'){await finishAuthorization();return}
    status(reply.message||'请在授权窗口允许本站连接；若未弹出，请点击下方按钮。');
    showAuthorizationActions(pending);
  }
  window.addEventListener('message',event=>{
    if(event.source!==window||event.origin!==location.origin||event.data?.source!=='collector-extension-permission'||!pendingAuthorization)return;
    try{if(new URL(pendingAuthorization.url).origin===event.data.origin)finishAuthorization()}catch{}
  });
  async function drive(){
    if(driving){resumeQueued=true;return}driving=true;
    try{
      const bridge=await browserCookieBridge('ping');
      while(!stopped){
        const tasks=await list(), next=tasks.find(t=>t.state==='running');
        if(!next)break;
        if(!bridge.capabilities?.includes('author-scan-v2')){await api('/api/authors/'+next.id+'/control',{action:'pause'});status('请更新并重新加载扩展（Cookie-Editor 1.14.3／独立版 1.5.3），再继续历史发现。');break;}
        const result=await browserCookieBridge('author-step',next.id,token);
        if(stopped)break;
        if(['permission','error','unavailable'].includes(result.status)){
          await api('/api/authors/'+next.id+'/control',{action:'pause'});
          status(result.message||'请更新扩展，在同一个浏览器打开工具后继续。');
          if(result.status==='permission')await authorizeTask(next,result.permissionUrl||next.source.url);
          await list();break;
        }
        status(result.batch?.message||result.message||'正在处理…');
        if(result.batch)await autoDownload(result.batch);
        // Preserve the single worker tab while a person handles verification.
        if(result.batch?.state==='needs_user')break;
        await new Promise(resolve=>setTimeout(resolve,3500));
      }
    }catch(e){status(e.message)}finally{driving=false;await list();if(resumeQueued&&!stopped){resumeQueued=false;drive()}}
  }
  document.getElementById('authorStart').onclick=async()=>{
    if(starting||!connected||lastTasks.some(t=>t.state==='running'||t.state==='needs_user'))return;
    starting=true;controls();
    try{
      const urls=[...new Set(document.getElementById('authorUrls').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean))];
      if(!urls.length||urls.length>20)throw Error('请输入 1–20 个作者／历史列表网址，每行一个。');
      const health=await api('/health');
      if(!health.author_scan_modes?.includes('incremental'))throw Error('当前后端尚未加载增量更新功能。请在任务结束后重新启动本机工具，再刷新页面；未创建新任务。');
      const ping=await browserCookieBridge('ping');
      if(ping.status!=='connected')throw Error('请在已安装新版扩展的 Edge／Chrome 中打开本机工具。');
      if(!ping.capabilities?.includes('author-scan-v2'))throw Error('当前扩展不支持按作者采集，请下载新版并重新加载扩展，再刷新工具。');
      const limit=Number(document.getElementById('authorLimit').value);
      if(!Number.isInteger(limit)||limit<1||limit>5000)throw Error('每个作者上限应为 1–5000 篇');
      for(const value of urls){
        let u;try{u=new URL(value)}catch{throw Error('网址格式不正确：'+value)}
        const supported=(['xueqiu.com','www.xueqiu.com'].includes(u.hostname)&&/^\/(?:u\/)?\d+\/?$/.test(u.pathname))||
          (u.hostname==='mp.weixin.qq.com'&&(['/mp/profile_ext','/mp/appmsgalbum','/s'].includes(u.pathname)||u.pathname.startsWith('/s/')));
        if(u.protocol!=='https:'||u.username||u.password||u.port||!supported)throw Error('请填写支持的 HTTPS 作者主页或微信历史列表网址：'+value);
      }
      for(const url of urls){const task=await api('/api/authors',{url,scan_mode:document.getElementById('authorScanMode').value,limit:Number(document.getElementById('authorLimit').value),auto_after:document.getElementById('authorAutoDownload').checked});await api('/api/authors/'+task.id+'/control',{action:'resume'})}
      stopped=false;drive();
    }catch(e){status(e.message);await list()}finally{starting=false;controls()}
  };
  document.getElementById('authorPauseAll').onclick=async()=>{
    if(pausing)return;pausing=true;controls();
    try{stopped=true;pendingAuthorization=null;for(const task of await list())if(task.state==='running')await api('/api/authors/'+task.id+'/control',{action:'pause'});await list();status('正文采集已暂停。已保存内容和进度保留；已入队的图片可继续后台识别。')}
    catch(e){status(e.message)}finally{pausing=false;controls()}
  };
  document.getElementById('authorChooseFolder').onclick=async()=>{
    const button=document.getElementById('authorChooseFolder');button.disabled=true;
    try{saveStatus('请在本机弹出的窗口中选择文件夹…');const config=await api('/api/download-settings/pick',{});renderSettings(config);if(config.cancelled)saveStatus('已取消选择，原保存位置保持不变。')}
    catch(e){saveStatus(e.message)}finally{button.disabled=false}
  };
  const applySettings=async()=>{const config=await api('/api/download-settings',{folder:document.getElementById('authorSaveFolder').value,mode:document.getElementById('authorSaveMode').value});renderSettings(config)};
  document.getElementById('authorApplyFolder').onclick=()=>{document.getElementById('authorSaveMode').value='folder';applySettings().catch(e=>saveStatus(e.message))};
  document.getElementById('authorSaveMode').onchange=()=>applySettings().catch(e=>saveStatus(e.message));
  document.getElementById('authorOpenFolder').onclick=()=>api('/api/download-settings/open',{}).catch(e=>saveStatus(e.message));
  if(monitor){
    const section=document.getElementById('authorBatch');
    for(const child of section.children)if(!['authorTasks','authorStatus','authorOverview'].includes(child.id)&&child.tagName!=='H2')child.hidden=true;
    section.querySelector('h2').textContent='采集与导出实时进度';
    status('只读进度页：不控制采集，不触发识别或下载。保留原采集标签页运行。图片累计统计每 30 秒更新。');
    document.getElementById('singleCollector').hidden=true;
    document.getElementById('moreTools').hidden=true;
  }
  // Reload never restarts remote browsing automatically. Resume is an explicit user action.
  controls();
  setInterval(()=>{if(!driving)list().catch(()=>{})},5000);
  list().catch(e=>status(e.message));
  api('/api/download-settings').then(renderSettings).catch(e=>saveStatus(e.message));
})();
