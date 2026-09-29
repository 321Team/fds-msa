import sys,json,urllib.request,urllib.parse
Q={}
for l in open('promql.txt',encoding='utf-8'):
    if l[:3] in ('Q1_','Q2_','Q3_'):
        k,v=l.rstrip('\n').split('=',1); Q[k[:2]]=v
B='http://127.0.0.1:19091/api/v1/'
def get(p,a,t): return urllib.request.urlopen(B+p+'?'+urllib.parse.urlencode(a),timeout=t).read()
if sys.argv[1]=='check':
    for k in sorted(Q):
        r=json.loads(get('query',{'query':Q[k]},10))['data']['result']
        print(k,len(r),'series',' '.join(f"{x['metric'].get('pod','-')}={x['value'][1]}" for x in sorted(r,key=lambda x:x['metric'].get('pod',''))))
else:
    s,e=sys.argv[1],sys.argv[2]
    for k in sorted(Q):
        raw=get('query_range',{'query':Q[k],'start':s,'end':e,'step':'15'},30)
        open(k.lower()+'.json','wb').write(raw)
        d=json.loads(raw); print(k,d['status'],len(d['data']['result']),'series',sum(len(x['values']) for x in d['data']['result']),'points')
