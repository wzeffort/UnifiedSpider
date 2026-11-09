"""Run shipped extension code with mock Chrome APIs, no live sites or jobs."""
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright


class Navigation(unittest.TestCase):
    def test_navigation_guards(self):
        code=Path('app/browser-extension/author-batch.js').read_text(encoding='utf-8')
        self.assertEqual(code,Path('app/CookieEditor-Collector/author-batch.js').read_text(encoding='utf-8'))
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page()
            for case in ['old','redirect','race','good','concurrent','pending','retry']:
                page.goto('about:blank')
                page.evaluate('''() => {
                  globalThis.fixture={batch:{id:'11111111-1111-1111-1111-111111111111',state:'running',phase:'capture',url:'https://www.xueqiu.com/123/2',revision:7,not_before:0,article_retry_supported:true,article_retry:0},posts:[],updates:[],tab:{id:9,url:'https://xueqiu.com/123/2',status:'complete'},extracts:0};
                  const f=fixture;f.storage={'author-worker:1':9,'author-worker:1:position':f.batch.id+':capture:'+f.batch.url+':retry0'};
                  globalThis.chrome={permissions:{contains:async()=>true},runtime:{getManifest:()=>({name:'fixture'})},storage:{session:{get:async k=>({[k]:f.storage[k]}),set:async o=>Object.assign(f.storage,o),remove:async k=>delete f.storage[k]}},tabs:{get:async()=>({...f.tab}),update:async(id,o)=>{f.updates.push(o);return f.tab}},scripting:{executeScript:async()=>{f.extracts++;if(f.wait)await f.wait;const url=f.docUrl||f.tab.url;if(f.afterUrl)f.tab.url=f.afterUrl;return [{result:{url,html:'正文',links:[]}}]}}};
                  globalThis.fetch=async(url,options)=>{if(options?.method==='POST')f.posts.push(JSON.parse(options.body));return {ok:true,json:async()=>f.batch}};
                  globalThis.invoke=()=>runAuthorBatchStep({url:f.batch.id,token:'fixture'},{tab:{id:1}},'http://127.0.0.1:18765');
                }''')
                page.evaluate('() => {'+code+'\n}')
                result=page.evaluate('''async name=>{
                  const f=fixture;
                  if(name==='old')f.tab.url='https://xueqiu.com/123/1';
                  if(name==='redirect')f.tab.url='https://xueqiu.com/account/login';
                  if(name==='race')f.afterUrl='https://xueqiu.com/123/3';
                  if(name==='pending')f.tab.pendingUrl=f.batch.url;
                  if(name==='retry')f.batch.article_retry=1;
                  if(name==='concurrent'){
                    let release;f.wait=new Promise(r=>release=r);const one=invoke();
                    while(!f.extracts)await new Promise(r=>setTimeout(r,0));
                    const two=await invoke();release();await one;
                    return {status:two.status,posts:f.posts.length,extracts:f.extracts};
                  }
                  const a=await invoke();const b=null;
                  return {status:a.status,second:b?.status,posts:f.posts.length,extracts:f.extracts,updates:f.updates.length,message:a.message};
                }''',case)
                if case in ('good','old','redirect'):
                    self.assertEqual(result['posts'],1)
                    self.assertEqual(result['status'],'batch')
                elif case=='concurrent':
                    self.assertEqual(result,{'status':'loading','posts':1,'extracts':1})
                else:
                    self.assertEqual(result['posts'],0,case)
                    if case=='old':
                        self.assertEqual(result['updates'],1)
                        self.assertEqual(result['second'],'error')
                    if case=='redirect':
                        self.assertEqual(result['updates'],0)
                        self.assertIn('预期',result['message'])
                    if case=='pending':self.assertEqual(result['extracts'],0)
                    if case=='retry':
                        self.assertEqual(result['updates'],1)
                        self.assertEqual(result['extracts'],0)
            browser.close()


if __name__=='__main__':unittest.main()
