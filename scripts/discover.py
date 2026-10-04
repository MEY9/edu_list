"""Explicit educational-topic discovery; raw output is imported separately."""
import json, time, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode

import argparse, os
parser=argparse.ArgumentParser(description='按教育用途查询 GitHub，保存可复核的原始检索结果')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
OUT=args.output
OUT.parent.mkdir(parents=True,exist_ok=True)
token=os.environ.get('GITHUB_TOKEN')
# Search only explicit educational signals; tools keep their own applicable category.
QUERIES = [
 ('topic:education','programming',6),
 ('topic:tutorial','courses',4),
 ('topic:learn-to-code','programming',3),
 ('topic:course','courses',2),
 ('topic:curriculum','courses',2),
 ('topic:learning-resources','courses',2),
 ('topic:educational','programming',2),
 ('topic:edtech','learning-platforms',2),
 ('topic:lms','learning-platforms',2),
 ('topic:learning-management-system','learning-platforms',1),
 ('topic:flashcards','self-learning',2),
 ('topic:spaced-repetition','self-learning',1),
 ('topic:online-judge','assessment',2),
 ('topic:quiz','assessment',2),
 ('topic:school-management','school-management',1),
 ('topic:physics','simulation',2),
 ('topic:mathematics','simulation',2),
 ('topic:manim','simulation',1),
 ('topic:presentation','courseware',2),
 ('topic:whiteboard','courseware',1),
 ('topic:anki','self-learning',1),
 ('topic:ai-tutor','ai-education',1),
 ('topic:language-learning','language-learning',2),
 ('topic:english-learning','language-learning',1),
 ('topic:computer-science','courses',3),
 ('topic:educational-game','programming',1),
 ('topic:knowledge-base','ai-education',2),
 ('topic:note-taking','self-learning',2),
 ('topic:markdown-editor','courseware',1),
 ('topic:video-conferencing','collaboration',1),
 ('topic:collaborative','collaboration',1),
 ('topic:pdf-editor','documents',1),
 ('topic:ocr','documents',1),
 ('topic:speech-to-text','media-tools',1),
 ('topic:screen-recorder','media-tools',1),
]
data=json.loads(OUT.read_text()) if OUT.exists() else {'repositories':{},'searches':[]}
done={(x['query'],x['page']) for x in data['searches']}
last=0
for term, category, pages in QUERIES:
 query=term+' stars:>=100 archived:false fork:false'
 for page in range(1,pages+1):
  if (query,page) in done: continue
  url='https://api.github.com/search/repositories?'+urlencode({'q':query,'sort':'stars','order':'desc','per_page':100,'page':page})
  for attempt in range(6):
   time.sleep(max(0,7-(time.monotonic()-last)))
   last=time.monotonic()
   try:
    with urllib.request.urlopen(urllib.request.Request(url,headers=dict({'User-Agent':'edu-list-discovery','Accept':'application/vnd.github+json'}, **({'Authorization':'Bearer '+token} if token else {}))),timeout=45) as response:
     payload=json.load(response)
    if payload.get('incomplete_results'): raise RuntimeError('Incomplete search results')
    break
   except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,RuntimeError) as exc:
    print('Retry',term,page,type(exc).__name__,'请求失败，等待后重试',flush=True)
    if attempt==5: raise
    time.sleep(20 if attempt<2 else 60)
  stamp=datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
  for repo in payload['items']:
   key=repo['full_name'].lower()
   if key not in data['repositories']:
    data['repositories'][key]={'repository':repo,'category':category,'query':query,'source':url,'fetched_at':stamp}
   elif repo['stargazers_count']>data['repositories'][key]['repository']['stargazers_count']:
    data['repositories'][key]['repository']=repo
    data['repositories'][key]['fetched_at']=stamp
  data['searches'].append({'query':query,'page':page,'total_count':payload['total_count'],'fetched_count':len(payload['items']),'source':url,'fetched_at':stamp})
  tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.replace(OUT)
  print(term,page,'total',payload['total_count'],'unique',len(data['repositories']),flush=True)
  if len(payload['items'])<100 or page*100>=payload['total_count']: break
print('DONE',len(data['repositories']),flush=True)
