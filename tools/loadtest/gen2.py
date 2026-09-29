import json,time,sys,random,threading,http.client
from concurrent.futures import ThreadPoolExecutor
RUN,OUT=sys.argv[1],sys.argv[2]; random.seed(RUN)
W=['10.1.93.105','10.1.93.107','10.1.93.108']; ST=[('B',20,600),('P',50,180)]; IDLE=120
lk=threading.Lock(); f=open(OUT+'/requests.log','a'); cnt={}
def log(*a): print(time.strftime('%H:%M:%S'),*a,flush=True)
def send(i,st,tp):
    w=W[i%3]; b=json.dumps({"account_id":f"SIM_load_{RUN}_{i}","amount":10000,"currency":"KRW","transaction_type":tp,"source_ip":"198.51.100.10"})
    t0=time.time()
    try:
        c=http.client.HTTPConnection(w,30080,timeout=10); c.request('POST','/api/v1/transactions',b,{'Content-Type':'application/json'}); r=c.getresponse(); r.read(); code=r.status; c.close()
    except Exception: code=-1
    with lk:
        f.write(f"{t0:.3f} {st} {w} {tp} {code} {(time.time()-t0)*1000:.1f}\n"); cnt[code]=cnt.get(code,0)+1
with ThreadPoolExecutor(max_workers=64) as ex:
    i=0
    for st,rps,dur in ST:
        s=time.time(); log('START',st,rps,'rps',dur,'s',f'{s:.3f}'); k=0; nxt=s+30
        while time.time()-s<dur:
            if time.time()>=nxt:
                with lk: f.flush(); c=dict(cnt)
                log('..',st,'sent',k,'codes',c); nxt+=30
            d=s+k/rps-time.time()
            if d>0: time.sleep(min(d,0.05)); continue
            x=random.random(); ex.submit(send,i,st,'deposit' if x<0.6 else ('withdrawal' if x<0.8 else 'transfer')); i+=1; k+=1
        log('END',st,'sent',k,f'{time.time():.3f}')
    t=time.time(); log('IDLE START',f'{t:.3f}'); time.sleep(IDLE)
    with lk: f.flush(); c=dict(cnt)
    log('IDLE END',f'{time.time():.3f}','codes',c)
f.close()
