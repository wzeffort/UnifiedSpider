"""MinerU 4 task API on a configured local/private server, no official API calls."""
import hashlib
import io
import os
import time
import zipfile
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from storage import DATA, read, save


def recognize(path, timeout=600):
    base=os.environ['MINERU_SELF_HOSTED_URL'].rstrip('/')
    endpoint=urlsplit(base)
    if endpoint.scheme not in ('http','https') or not endpoint.hostname or endpoint.username or endpoint.password:
        raise ValueError('自部署 MinerU 地址无效')
    tier=os.environ.get('MINERU_SELF_HOSTED_TIER','standard')
    body=path.read_bytes(); digest=hashlib.sha256(body).hexdigest()
    namespace=hashlib.sha256((base+'|'+tier+'|v4').encode()).hexdigest()[:16]
    folder=DATA/'mineru-cache';folder.mkdir(parents=True,exist_ok=True)
    cache_path=folder/(digest+'-selfhost-'+namespace+'.json')
    cached=read(cache_path,{})
    if cached.get('result'):return cached['result']
    with requests.Session() as client:
        client.trust_env=False
        def request(method, target, **kwargs):
            url=urljoin(base+'/',target)
            parsed=urlsplit(url)
            if (parsed.scheme,parsed.netloc)!=(endpoint.scheme,endpoint.netloc):
                raise ValueError('MinerU 返回了非本服务地址，停止传输')
            response=client.request(method,url,timeout=(10,60),allow_redirects=False,**kwargs)
            if not 200<=response.status_code<300:
                raise ValueError('自部署 MinerU HTTP '+str(response.status_code))
            return response
        if not cached.get('task_id'):
            created=request('POST','v1/tasks',json={'files':[{'file_name':'image'+path.suffix,'bytes':len(body),'sha256sum':digest}],
                           'tier':tier,'ocr_mode':'ocr','output_formats':['default']}).json()
            cached={'task_id':created['task_id']}
            save(cache_path,cached)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            detail=request('GET','v1/tasks/'+cached['task_id']).json()
            item=detail['files'][0]
            if item.get('upload'):
                upload=item['upload']
                request('PUT',upload['url'],data=body,headers=upload.get('headers',{}))
            elif item['status']=='completed':
                response=request('GET',item['result_url'],stream=True)
                payload=bytearray()
                with response:
                    for chunk in response.iter_content(65536):
                        payload.extend(chunk)
                        if len(payload)>50*1024*1024:raise ValueError('MinerU 结果超过 50 MB')
                result=decode(bytes(payload))
                result.update(image_sha256=digest,provider='self-hosted',model='mineru4-'+tier)
                cached['result']=result;save(cache_path,cached)
                return result
            elif item['status'] in ('failed','canceled'):
                save(cache_path,{'failed_task':cached['task_id']})
                raise ValueError('自部署 MinerU 解析失败：'+str(item.get('error',{}))[:250])
            time.sleep(2)
    raise ValueError('自部署 MinerU 仍在处理，稍后重试将继续查询原任务')


def decode(payload):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names=[i for i in archive.infolist() if i.filename.endswith('.md')]
        if len(names)!=1 or names[0].file_size>20*1024*1024:
            raise ValueError('MinerU 结果未包含唯一有效 Markdown')
        markdown=archive.read(names[0]).decode('utf-8')
    soup=BeautifulSoup(markdown,'html.parser')
    tables=[[[c.get_text(' ',strip=True) for c in r.find_all(['td','th'])] for r in t.find_all('tr')] for t in soup.find_all('table')]
    return {'engine':'mineru','text':soup.get_text(' ',strip=True),'markdown':markdown,'tables':tables,'verified':False}
