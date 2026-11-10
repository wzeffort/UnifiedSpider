"""Exercise shipped extension navigation against deterministic Chrome/network fakes."""
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright


class Prefetch(unittest.TestCase):
    def test_two_tabs_lease_pacing_and_verification(self):
        code=Path('app/browser-extension/author-batch.js').read_text(encoding='utf-8')
        self.assertEqual(code,Path('app/CookieEditor-Collector/author-batch.js').read_text(encoding='utf-8'))
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            for mode in ('normal','verification','busy','closed'):
                page=browser.new_page()
                page.evaluate('''() => {
                  globalThis.f={now:1000000,mode:'normal',created:0,nav:[],reports:[],reads:[],store:{},tabs:{9:{id:9,url:'https://xueqiu.com/123/1',status:'complete'}},batch:{id:'11111111-1111-1111-1111-111111111111',state:'running',phase:'capture',url:'https://xueqiu.com/123/1',revision:1,processed:0,not_before:0,article_retry:0,article_retry_supported:true,capture_claim_supported:true}};
                  Date.now=()=>f.now;
                  const position=()=>f.batch.id+':capture:'+f.batch.url+':retry0';
                  f.store['author-worker:1']=9;f.store['author-worker:1:position']=position();
                  f.store['author-worker-id:http://127.0.0.1:18765:1']='22222222-2222-2222-2222-222222222222';
                  globalThis.chrome={runtime:{getManifest:()=>({name:'fixture'})},permissions:{contains:async()=>true},storage:{session:{get:async k=>({[k]:f.store[k]}),set:async o=>Object.assign(f.store,o),remove:async k=>delete f.store[k]}},tabs:{get:async id=>{if(!f.tabs[id])throw Error('closed');return {...f.tabs[id]}},create:async o=>{const id=10+f.created++;return f.tabs[id]={id,...o,status:'complete'}},update:async(id,o)=>{f.nav.push({id,url:o.url,time:f.now});Object.assign(f.tabs[id],o);return f.tabs[id]}},scripting:{executeScript:async({target})=>{f.reads.push(target.tabId);return [{result:{url:f.tabs[target.tabId].url,html:'body',links:[]}}]}}};
                  globalThis.fetch=async(url,options)=>{
                    let data={...f.batch};
                    if(url.endsWith('/claim'))data=f.mode==='busy'?{status:'busy',retry_after_ms:3000}:{status:'claimed',lease:'fixture-lease',batch:{...f.batch}};
                    else if(url.endsWith('/report')){
                      const body=JSON.parse(options.body);f.reports.push(body);
                      if(body.capture_lease!=='fixture-lease')throw Error('unleased report');
                      if(f.mode==='verification'){f.batch.state='needs_user'}
                      else {f.batch.processed++;f.batch.revision++;f.batch.url='https://xueqiu.com/123/'+(f.batch.processed+1);f.batch.not_before=f.now/1000+3}
                      data={...f.batch};
                    }
                    return {ok:true,json:async()=>data};
                  };
                  globalThis.invoke=()=>runAuthorBatchStep({url:f.batch.id,token:'fixture'},{tab:{id:1}},'http://127.0.0.1:18765');
                }''')
                page.evaluate('() => {'+code+'\n}')
                result=page.evaluate('''async mode=>{
                  f.mode=mode==='verification'?'normal':mode;
                  const first=await invoke();
                  if(mode==='busy')return {status:first.status,reports:f.reports.length,nav:f.nav.length};
                  // Cooldown polling must not submit or open a third tab.
                  await invoke();
                  const cooldownReports=f.reports.length;
                  if(mode==='closed')delete f.tabs[10];
                  f.now+=3100;
                  if(mode==='verification')f.mode='verification';
                  await invoke();
                  if(mode==='closed'){await invoke();await invoke()}
                  if(mode==='normal'){f.now+=3100;await invoke()}
                  return {created:f.created,reads:f.reads,reports:f.reports.length,cooldownReports,nav:f.nav,state:f.batch.state};
                }''',mode)
                if mode=='busy':
                    self.assertEqual(result,dict(status='busy',reports=0,nav=0))
                else:
                    self.assertEqual(result['cooldownReports'],1)
                    self.assertLessEqual(result['created'],2)
                    if mode=='normal':
                        self.assertEqual(result['created'],1)
                        self.assertEqual(result['reads'],[9,10,9])
                        times=[n['time'] for n in result['nav'] if n['url']!='about:blank']
                        self.assertTrue(all(b-a>=3000 for a,b in zip(times,times[1:])))
                    elif mode=='verification':
                        self.assertEqual(result['state'],'needs_user')
                        self.assertEqual([n['url'] for n in result['nav'] if n.get('url')][-1],'about:blank')
                        self.assertEqual(result['reports'],2)
                    else:
                        self.assertEqual(result['reports'],2)
                page.close()
            browser.close()
