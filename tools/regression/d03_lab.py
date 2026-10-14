"""Explicitly authorized, one-shot D-03 Podman lab. No production endpoint/pull/deploy.

plan is offline. run requires exact plan SHA + an external, reviewed window record.
The host driver creates only labeled containers; all share a network=none namespace.
"""
import argparse
import datetime as dt
import hashlib
import http.client as http_client
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import time

from d03_fixture import CASES, validate_run

KST = dt.timezone(dt.timedelta(hours=9))
HOST = 'cicd-runner01'
SOURCE = 'affbc69beef9967f7977d09a6fec14f7fb6c0e94'
IMAGES = {
    'api': 'sha256:ab34196baf2b878222857be47b200baed0151679a5b19fe15635ba50f77bffee',
    'engine': 'sha256:b82d35a60e7a7f4a30366a926699fa4b673e69610f64fa0e7f294673ed12f4fc',
    'db': 'quay.io/sclorg/postgresql-16-c9s@sha256:d33717fd33c1a4b11afef94568d0c20812a19d62fb8c633fadee1e491e2edd4a',
}
MANIFESTS = {'api': 'sha256:338b8a2871507ce8b42deedc916b26e350577ee6efd18df23d7ff2dd4b17dff0',
             'engine': 'sha256:8b257adb08b6d381f72b66d3386efea6112a8f072ecfafcbcd463bcd1c3be89d'}
FILES = ('tools/regression/d03_lab.py', 'tools/regression/d03_fixture.py',
         'deploy/components/lab-db/10-fds-schema.sh', 'deploy/components/lab-db/fds-schema.sql',
         'alembic/versions/0001_initial_schema.py', 'alembic/versions/0002_add_fds_evaluation_columns.py',
         'alembic/versions/0003_add_transactions_indexes.py')
METRICS = ('transaction_save_success_total', 'transaction_save_failure_total', 'fds_evaluation_error_total')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def save(path, value):
    with Path(path).open('xb') as stream:
        stream.write(encode(value))


def repository_root():
    # Container helpers run from /d03 with only two staged files, not a checkout.
    path = Path(__file__).resolve()
    if len(path.parents) < 3 or path.parent.name != 'regression' or path.parent.parent.name != 'tools':
        raise ValueError('HOST_REPOSITORY_REQUIRED')
    return path.parents[2]


def make_plan(run):
    validate_run(run)
    root = repository_root()
    return {'schema': 'P1-D03-ISOLATED-1', 'run': run, 'host': HOST, 'uid': 1000,
            'source': SOURCE, 'images': IMAGES, 'deployed_manifests': MANIFESTS,
            'files': {name: sha((root/name).read_bytes()) for name in FILES},
            'cases': list(CASES), 'max_posts': 7, 'max_lifetime_seconds': 900,
            'production_runtime_claim': False}


def read_plan(path, expected_sha):
    raw = Path(path).read_bytes()
    if sha(raw) != expected_sha:
        raise ValueError('PLAN_SHA_MISMATCH')
    plan = json.loads(raw)
    if plan != make_plan(plan['run']):
        raise ValueError('PLAN_SOURCE_OR_CRITERIA_MISMATCH')
    return plan


def authorize(plan, record, now):
    fields = ('start_after', 'start_before', 'finish_before')
    times = [dt.datetime.fromisoformat(record[key]) for key in fields]
    if any(t.tzinfo is None for t in times):
        raise ValueError('TIMEZONE_REQUIRED')
    start, last, end = times
    if not (start < last < end and start <= now <= last and
            dt.timedelta(minutes=12) <= end-now <= dt.timedelta(minutes=30)):
        raise ValueError('WINDOW_INVALID_OR_EXPIRED')
    if record.get('approved') is not True or record.get('plan_sha256') != sha(encode(plan)):
        raise ValueError('EXACT_PLAN_NOT_APPROVED')
    if not all(isinstance(record.get(k), str) and record[k].startswith('https://github.com/321Team/')
               for k in ('user_authorization_reference', 'independent_review_reference')):
        raise ValueError('APPROVAL_REFERENCES_REQUIRED')
    if record.get('runner_exclusive') is not True or record.get('lab_db_image_accepted') is not True:
        raise ValueError('EXCLUSIVE_RUNNER_AND_LAB_DB_ACCEPTANCE_REQUIRED')
    return end


def payload(run, case):
    validate_run(run)
    if case not in CASES:
        raise ValueError('CASE')
    return {'account_id': 'SIM_d03_'+run+'_'+case, 'amount': 10000, 'currency': 'KRW',
            'transaction_type': 'deposit', 'source_ip': '198.51.100.10',
            'occurred_at': dt.datetime.strptime(run, '%Y%m%d%H%M').strftime('%Y-%m-%dT12:00:00+09:00')}


def http(port, path, body=None):
    conn = http_client.HTTPConnection('127.0.0.1', port, timeout=8)
    start = time.monotonic()
    try:
        conn.request('POST' if body is not None else 'GET', path,
                     json.dumps(body) if body is not None else None,
                     {'Content-Type': 'application/json'})
        response = conn.getresponse()
        text = response.read(65537).decode()
        if len(text) > 65536:
            raise ValueError('RESPONSE_TOO_LARGE')
        return {'status': response.status, 'body': text, 'elapsed': time.monotonic()-start}
    finally:
        conn.close()


def counter_values(text):
    values = {}
    for key in METRICS:
        found = re.findall(r'^'+key+r' ([0-9.eE+-]+)$', text, re.M)
        if len(found) != 1:
            raise ValueError('MISSING_OR_DUPLICATE_METRIC '+key)
        value = float(found[0])
        if not (0 <= value < float('inf')):
            raise ValueError('INVALID_COUNTER')
        values[key] = value
    return values


def check_case(case, response, before, after, rows):
    body = json.loads(response['body'])
    skipped = case in ('READ', 'HTTP')
    expected = dict(zip(METRICS, (0, 1, 0) if case == 'DB' else (1, 0, int(skipped))))
    if {k: after[k]-before[k] for k in METRICS} != expected:
        raise ValueError('METRIC_DELTA '+case)
    if case == 'DB':
        if response['status'] != 500 or body != {'detail': 'transaction save failed'} or rows:
            raise ValueError('DB_FAILURE_CONTRACT')
        return
    if response['status'] != 201 or len(rows) != 1:
        raise ValueError('HTTP_DB_CARDINALITY '+case)
    row = rows[0]
    if (not {'transaction_id','fds_detected','fds_rules','fds_evaluation_skipped'} <= body.keys() or
            not re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',str(body.get('transaction_id'))) or
            body['transaction_id'] != row['transaction_id'] or
            body.get('fds_evaluation_skipped') is not skipped or
            row['fds_evaluation_skipped'] is not skipped or
            row['fds_detected'] != body.get('fds_detected') or row['fds_rules'] != body.get('fds_rules')):
        raise ValueError('RESPONSE_DB_CONTRACT '+case)
    if skipped:
        if body.get('fds_detected') is not None or body.get('fds_rules') is not None:
            raise ValueError('FAIL_OPEN_NULLS '+case)
        if case == 'READ' and not 1.8 <= response['elapsed'] < 8:
            raise ValueError('NOT_READ_TIMEOUT')
    else:
        rules = body.get('fds_rules')
        if (body.get('fds_detected') is not False or not isinstance(rules, list) or len(rules) != 4 or
                {r.get('rule_id') for r in rules} != {'R01','R02','R04','R07'} or
                any(r.get('triggered') is not False for r in rules)):
            raise ValueError('NORMAL_RULE_CONTRACT '+case)


def rollback_pid(log, run):
    found = list(re.finditer(r'D03 \[(\d+)\]\s+LOG:\s+D03_INJECT_'+validate_run(run)+r'\s*$',log,re.M))
    pids = {m.group(1) for m in found}
    if len(pids) != 1:
        raise ValueError('INJECTION_PID_NOT_UNIQUE')
    pid = next(iter(pids))
    tail = log[found[-1].end():]
    if not re.search(r'D03 \['+pid+r'\].*(?:statement:|execute [^:]+:)\s*ROLLBACK\s*;', tail):
        raise ValueError('ROLLBACK_NOT_OBSERVED_ON_INJECTION_SESSION')
    return int(pid)


def trigger_sql(run, remove=False):
    validate_run(run)
    guard = "DO $$ BEGIN IF current_database() <> 'fds_lab' THEN RAISE EXCEPTION 'NOT_LAB_DB'; END IF; END $$;\n"
    drop = 'DROP TRIGGER d03_insert_fail ON public.transactions; DROP FUNCTION public.d03_insert_fail();\n'
    if remove:
        return guard + drop
    return guard + """CREATE FUNCTION public.d03_insert_fail() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.account_id = 'SIM_d03_RUN_DB' THEN
  RAISE LOG 'D03_INJECT_RUN';
  RAISE EXCEPTION 'D03_EXPECTED_INSERT_FAILURE_RUN';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER d03_insert_fail BEFORE INSERT ON public.transactions
FOR EACH ROW EXECUTE FUNCTION public.d03_insert_fail();
""".replace('RUN',run)


def canonical_image_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}', value):
        raise ValueError('INVALID_IMAGE_CONFIG_ID')
    return 'sha256:' + value.removeprefix('sha256:')


def image_record(role, image, obj):
    raw = obj.get('Id', obj.get('ID', ''))
    canonical = canonical_image_id(raw)
    if role != 'db' and canonical != canonical_image_id(image):
        raise ValueError('IMAGE_CONFIG_MISMATCH')
    if role == 'db' and image not in obj.get('RepoDigests', []):
        raise ValueError('DB_DIGEST_MISMATCH')
    return {'id': raw, 'canonical_config_id': canonical,
            'repo_digests': obj.get('RepoDigests', []), 'user': obj['Config']['User']}


def runner_worker_active(proc=Path('/proc')):
    for directory in proc.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            name = (directory/'comm').read_text().strip()
        except (FileNotFoundError, ProcessLookupError):
            continue  # The process exited between enumeration and reading comm.
        if name == 'Runner.Worker':
            return True
    return False


class Lab:
    def __init__(self, plan, out, end):
        self.plan, self.out, self.end = plan, Path(out), end
        self.password = secrets.token_hex(24)
        self.created, self.seq = [], 0
        self.label = 'fds.d03.run='+plan['run']
        self.cleaning = False
        self.work_deadline = time.monotonic()+min(660,(end-dt.datetime.now(dt.timezone.utc)).total_seconds()-120)

    def cmd(self, *args, stdin=None, timeout=30, private=False, check=True):
        remaining = (self.end-dt.datetime.now(dt.timezone.utc)).total_seconds()
        if not self.cleaning:
            remaining = min(remaining-120,self.work_deadline-time.monotonic())
        else:
            remaining = max(1,min(remaining,15))  # Cleanup is still attempted if a command crossed the window.
        if remaining <= 0:
            raise TimeoutError('EXECUTION_DEADLINE')
        self.seq += 1
        started=dt.datetime.now(dt.timezone.utc).isoformat()
        failure=None
        try:
            p = subprocess.run(['/usr/bin/podman',*args], input=stdin, capture_output=True,
                               text=True, timeout=min(timeout,remaining))
        except subprocess.TimeoutExpired as error:
            failure=error
            def text(value):
                return value.decode('utf-8',errors='replace') if isinstance(value,bytes) else value or ''
            p=subprocess.CompletedProcess(args,None,text(error.stdout),text(error.stderr))
        record = {'argv':list(args),'rc':p.returncode,'started_at_utc':started,
                  'finished_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'timed_out':failure is not None}
        if stdin is not None:
            record['stdin']=stdin.replace(self.password,'<REDACTED>')
        if not private:
            record.update(stdout=p.stdout.replace(self.password,'<REDACTED>'),stderr=p.stderr.replace(self.password,'<REDACTED>'))
        save(self.out/('%03d-command.json'%self.seq),record)
        if failure is not None:
            raise failure
        if check and p.returncode:
            raise RuntimeError('COMMAND_FAILED '+str(self.seq))
        return p

    def inspect(self, cid):
        return json.loads(self.cmd('inspect',cid,private=True).stdout)[0]

    def create(self, role, image, network, extra, command=()):
        name = 'fds-d03-'+self.plan['run']+'-'+role
        self.created.append({'name':name,'cid':None})
        cid = self.cmd('create','--pull=never','--name',name,'--label',self.label,
                       '--network',network,'--read-only','--cap-drop=ALL',
                       '--security-opt=no-new-privileges','--pids-limit=128',
                       '--timeout=900','--stop-timeout=5','--log-driver=k8s-file',
                       *extra,image,*command).stdout.strip()
        if not re.fullmatch('[0-9a-f]{64}',cid):
            raise ValueError('CONTAINER_ID')
        self.created[-1]['cid']=cid
        save(self.out/(role+'-identity.json'),{'name':name,'cid':cid,'label':self.label,'image':image})
        info = self.inspect(cid)
        if info['HostConfig']['NetworkMode'] != network or info['HostConfig'].get('PortBindings'):
            raise ValueError('NETWORK_ISOLATION')
        save(self.out/(role+'-isolation.json'),{'cid':cid,'network_mode':info['HostConfig']['NetworkMode'],
                                             'port_bindings':info['HostConfig'].get('PortBindings'),
                                             'privileged':info['HostConfig'].get('Privileged'),
                                             'read_only':info['HostConfig'].get('ReadonlyRootfs')})
        if info['HostConfig'].get('Privileged') or not info['HostConfig'].get('ReadonlyRootfs'):
            raise ValueError('CONTAINER_SECURITY_MISMATCH')
        self.cmd('start',cid)
        return cid

    def sql(self, db, query):
        return self.cmd('exec','-i',db,'psql','-X','-q','-At','-v','ON_ERROR_STOP=1',
                        '-d','fds_lab',stdin="SET statement_timeout='5s';\n"+query,timeout=15).stdout.strip()

    def inside(self, api, *args, check=True):
        return self.cmd('exec',api,'/venv/bin/python3','-B','/d03/d03_lab.py',*args,check=check,timeout=15)

    def cleanup(self):
        self.cleaning=True
        results=[]
        for obj in reversed(self.created):
            # Exact name fallback is only for uncertain create responses; a label mismatch never deletes.
            target=obj['cid'] or obj['name']
            try:
                found=self.cmd('container','exists',target,check=False)
                if found.returncode==1:
                    results.append({'name':obj['name'],'absent':obj['cid'] is not None,
                                    'note':'No object observed; uncertain create needs operator readback' if obj['cid'] is None else 'absent'}); continue
                if found.returncode!=0:
                    raise ValueError('EXISTENCE_UNKNOWN')
                info=self.inspect(target)
                if info['Config']['Labels'].get('fds.d03.run')!=self.plan['run']:
                    raise ValueError('CLEANUP_LABEL_MISMATCH')
                try:
                    self.cmd('logs',target,check=False)
                except Exception:
                    # Log collection failure must not suppress owned-container cleanup.
                    pass
                self.cmd('rm','--force','--time=5',target)
                absent=self.cmd('container','exists',target,check=False).returncode==1
                if not absent: raise ValueError('CLEANUP_NOT_CONFIRMED')
                results.append({'name':obj['name'],'absent':True})
            except Exception as error:
                results.append({'name':obj['name'],'absent':False,'error':type(error).__name__})
        for env in ('db.env','api.env'):
            path=self.out/env
            try:
                if path.exists(): path.unlink()
            except OSError:
                results.append({'name':env,'absent':False,'error':'CREDENTIAL_FILE_CLEANUP_FAILED'})
        save(self.out/'cleanup.json',results)
        return all(r['absent'] for r in results)

    def execute(self):
        p=self.plan
        root=repository_root()
        if self.cmd('info','--format','{{.Host.Security.Rootless}}').stdout.strip()!='true':
            raise ValueError('ROOTLESS_REQUIRED')
        if self.cmd('ps','-aq').stdout.strip():
            raise ValueError('EXCLUSIVE_EMPTY_CONTAINER_STORE_REQUIRED')
        if runner_worker_active():
            raise ValueError('RUNNER_WORKER_ACTIVE')
        for role, image in IMAGES.items():
            obj=json.loads(self.cmd('image','inspect',image,private=True).stdout)[0]
            save(self.out/(role+'-image.json'),image_record(role,image,obj))
        stage=self.out/'stage'; stage.mkdir(mode=0o700)
        code=stage/'code'; code.mkdir(mode=0o700)
        hooks=stage/'hooks'; hooks.mkdir(mode=0o700)
        # The host supervisor uses umask077. mkdir(mode=0755) alone becomes
        # 0700, which the non-root container UIDs cannot traverse. Only these
        # nonsecret, read-only bind roots need cross-UID read/search access.
        for directory in (code,hooks): directory.chmod(0o755)
        for file in ('d03_lab.py','d03_fixture.py'):
            source='tools/regression/'+file; raw=(root/source).read_bytes()
            if sha(raw)!=p['files'][source]: raise ValueError('STAGING_SOURCE_CHANGED')
            (code/file).write_bytes(raw); (code/file).chmod(0o644)
        for file in ('10-fds-schema.sh','fds-schema.sql'):
            source='deploy/components/lab-db/'+file; raw=(root/source).read_bytes()
            if sha(raw)!=p['files'][source]: raise ValueError('STAGING_SCHEMA_CHANGED')
            (hooks/file).write_bytes(raw); (hooks/file).chmod(0o644)
        (hooks/'20-d03-logging.sh').write_text("psql -X -v ON_ERROR_STOP=1 -d fds_lab <<'SQL' || exit 1\nALTER SYSTEM SET log_statement='all';\nALTER SYSTEM SET log_line_prefix='D03 [%p] ';\nALTER SYSTEM SET lc_messages='C';\nALTER SYSTEM SET logging_collector='off';\nALTER SYSTEM SET log_destination='stderr';\nSQL\n",encoding='utf-8')
        (hooks/'20-d03-logging.sh').chmod(0o644)
        for name,text in [('db.env','POSTGRESQL_USER=fds_lab\nPOSTGRESQL_DATABASE=fds_lab\nPOSTGRESQL_PASSWORD='+self.password+'\n'),
                          ('api.env','DATABASE_URL=postgresql+asyncpg://fds_lab:'+self.password+'@127.0.0.1:5432/fds_lab\nFDS_ENGINE_URL=http://127.0.0.1:18081/evaluate\nFDS_D03_RUN='+p['run']+'\n')]:
            fd=os.open(self.out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f: f.write(text)
        db=self.create('db',IMAGES['db'],'none',['--user=26:0','--memory=768m','--cpus=1',
            # Podman 6.1 rejects tmpfs uid=/gid=. The DB keeps UID26:GID0;
            # mode0770 permits its group to write without world-writable mounts.
            '--tmpfs=/var/lib/pgsql:rw,size=768m,mode=0770',
            '--tmpfs=/var/run/postgresql:rw,size=16m,mode=0770',
            '--tmpfs=/tmp:rw,size=64m,mode=1777','--env-file',str(self.out/'db.env'),
            '-v',str(hooks)+':/opt/app-root/src/postgresql-start:ro,z'])
        for _ in range(45):
            if self.cmd('exec',db,'/usr/libexec/check-container',check=False,timeout=5).returncode==0: break
            time.sleep(2)
        else: raise ValueError('DB_NOT_READY')
        identity=self.sql(db,"SELECT current_database()||'|'||current_user||'|'||version_num FROM alembic_version;")
        if identity!='fds_lab|postgres|0003': raise ValueError('DB_IDENTITY_SCHEMA')
        version=self.sql(db,'SELECT version();')
        if not version.startswith('PostgreSQL 16.'): raise ValueError('POSTGRES_MAJOR_VERSION')
        net='container:'+db
        mount=['-v',str(code)+':/d03:ro,z','--tmpfs=/tmp:rw,size=32m,mode=1777']
        engine=self.create('engine',IMAGES['engine'],net,['--memory=256m','--cpus=0.5',*mount])
        fixture=self.create('fixture',IMAGES['api'],net,['--memory=128m','--cpus=0.25',*mount,
            '--entrypoint=/venv/bin/python3'],['-B','/d03/d03_fixture.py','--run',p['run']])
        api=self.create('api',IMAGES['api'],net,['--memory=256m','--cpus=1',*mount,
            '--env-file',str(self.out/'api.env')])
        for port in (8000,8001,18081):
            for _ in range(20):
                probe=self.inside(api,'_probe',str(port),'/readyz',check=False)
                if probe.returncode==0 and json.loads(probe.stdout)['status']==200: break
                time.sleep(1)
            else: raise ValueError('NOT_READY '+str(port))
        isolation=json.loads(self.inside(api,'_isolation').stdout)
        save(self.out/'loopback-namespace.json',isolation)
        if isolation['interfaces']!=['lo'] or isolation['ipv4_routes']:
            raise ValueError('NON_LOOPBACK_NETWORK')
        for port,expected in ((8000,404),(8001,404),(9090,200),(9091,200)):
            if json.loads(self.inside(api,'_probe',str(port),'/metrics').stdout)['status']!=expected:
                raise ValueError('LISTENER_CONTRACT')
        if self.sql(db,'SELECT count(*) FROM public.transactions;')!='0':
            raise ValueError('LAB_DB_NOT_EMPTY')
        before_all=self.metrics(api)
        results=[]
        for case in CASES:
            results.append(self.run_case(case,api,db))
            if case=='DB':
                logs=self.cmd('logs',db)
                rollback_pid(logs.stdout+logs.stderr,p['run'])
        all_rows=json.loads(self.sql(db,"SELECT coalesce(json_agg(t),'[]'::json) FROM (SELECT * FROM public.transactions ORDER BY account_id) t;"))
        if len(all_rows)!=6 or len({r['transaction_id'] for r in all_rows})!=6:
            raise ValueError('FINAL_DB_CARDINALITY')
        after_all=self.metrics(api)
        if {k:after_all[k]-before_all[k] for k in METRICS}!=dict(zip(METRICS,(6,1,2))):
            raise ValueError('FINAL_METRIC_DELTA')
        flog=self.cmd('logs',fixture)
        events=[json.loads(line) for line in (flog.stdout+flog.stderr).splitlines() if line.startswith('{')]
        received=[event for event in events if event.get('event')=='request_received']
        if [event['case'] for event in received]!=list(CASES):
            raise ValueError('FIXTURE_MISSING_DUPLICATE_OR_REORDERED_REQUEST')
        for event,result in zip(received,results):
            expected_mode={'READ':'read-timeout','HTTP':'http-500'}.get(result['case'],'real-engine')
            if event['run']!=p['run'] or event['mode']!=expected_mode:
                raise ValueError('FIXTURE_MODE_MISMATCH')
            if result['case']!='DB' and event['transaction_id']!=result['rows'][0]['transaction_id']:
                raise ValueError('FIXTURE_TRANSACTION_ID_MISMATCH')
        if len([e for e in events if e.get('event')=='http500_sent' and e.get('case')=='HTTP'])!=1:
            raise ValueError('ENGINE_HTTP500_NOT_OBSERVED')
        db_logs=self.cmd('logs',db)
        pid=rollback_pid(db_logs.stdout+db_logs.stderr,p['run'])
        for port in (8000,8001,18081):
            if json.loads(self.inside(api,'_probe',str(port),'/readyz').stdout)['status']!=200:
                raise ValueError('RECOVERY_NOT_READY')
        save(self.out/'verified-cases.json',{'cases':list(CASES),'posts':7,'stored':6,
             'response_db_transactions':all_rows,'rollback_pid':pid,'result':'LAB_RUNTIME_PASS',
             'production_runtime_claim':False})

    def run_case(self,case,api,db):
        run=self.plan['run']
        installed=False
        primary=cleanup_error=None
        try:
            before=self.metrics(api)
            if case=='DB':
                self.sql(db,trigger_sql(run)); installed=True
            # Intent precedes POST; failures and uncertain responses are never retried.
            save(self.out/(case+'-post-intent.json'),{'case':case,'payload':payload(run,case),
                 'at_utc':dt.datetime.now(dt.timezone.utc).isoformat()})
            response=json.loads(self.inside(api,'_request',run,case).stdout)
            after=self.metrics(api)
            account=payload(run,case)['account_id']
            rows=json.loads(self.sql(db,"SELECT coalesce(json_agg(t),'[]'::json) FROM (SELECT * FROM public.transactions WHERE account_id='"+account+"') t;"))
            result={'case':case,'response':response,'before':before,'after':after,'rows':rows}
            save(self.out/(case+'-result.json'),result)
            for row in rows:
                if (row['account_id']!=account or row['amount']!=10000 or row['transaction_type']!='deposit' or
                        row['currency']!='KRW' or row['source_ip']!='198.51.100.10' or
                        dt.datetime.fromisoformat(row['occurred_at']) != dt.datetime.fromisoformat(payload(run,case)['occurred_at'])):
                    raise ValueError('DB_REQUEST_FIELDS')
            check_case(case,response,before,after,rows)
        except BaseException as error:
            primary=error
        finally:
            if installed:
                try:
                    self.sql(db,trigger_sql(run,remove=True))
                    if self.sql(db,"SELECT count(*) FROM pg_trigger WHERE tgname='d03_insert_fail';")!='0':
                        raise ValueError('TRIGGER_NOT_REMOVED')
                except BaseException as error:
                    cleanup_error=error
        if primary is not None or cleanup_error is not None:
            def describe(error):
                return None if error is None else {'type':type(error).__name__,
                    'message':str(error).replace(self.password,'<REDACTED>')}
            save(self.out/(case+'-errors.json'),{'primary':describe(primary),'trigger_cleanup':describe(cleanup_error)})
            if primary is not None:
                raise primary from cleanup_error
            raise cleanup_error
        return result

    def metrics(self,api):
        result=json.loads(self.inside(api,'_probe','9091','/metrics').stdout)
        if result['status']!=200: raise ValueError('METRICS_HTTP')
        return counter_values(result['body'])


def run_lab(plan_path, plan_sha, auth_path, output):
    plan=read_plan(plan_path,plan_sha)
    auth=json.loads(Path(auth_path).read_bytes())
    end=authorize(plan,auth,dt.datetime.now(dt.timezone.utc))
    if sys.platform!='linux' or socket.gethostname()!=HOST or os.getuid()!=1000:
        raise ValueError('FIXED_RUNNER_HOST_USER_REQUIRED')
    home=Path('/home/server01_cicd-runner')
    out=Path(output).absolute()
    if out.parent!=home or out.name!='FDS_D03_'+plan['run'] or out.exists():
        raise ValueError('NEW_FIXED_OUTPUT_REQUIRED')
    if home.resolve()!=home:
        raise ValueError('SYMLINK_HOME')
    # Permanent one-shot claim; never remove to retry a failed/uncertain run.
    claims=home/'FDS_D03_Claims'
    claims.mkdir(mode=0o700,exist_ok=True)
    if claims.is_symlink() or claims.stat().st_uid!=1000 or claims.stat().st_mode&0o077:
        raise ValueError('PRIVATE_CLAIM_DIRECTORY_REQUIRED')
    save(claims/(plan['run']+'.json'),{'plan_sha256':plan_sha,'auth':auth,'created_at':dt.datetime.now(dt.timezone.utc).isoformat()})
    out.mkdir(mode=0o700)
    save(out/'plan.json',plan); save(out/'authorization.json',auth)
    lab=Lab(plan,out,end)
    status='FAILED'; failure=None
    def interrupt(*_):
        raise KeyboardInterrupt()
    prior=signal.signal(signal.SIGTERM,interrupt)
    try:
        lab.execute(); status='LAB_RUNTIME_PASS'
    except BaseException as error:
        failure={'type':type(error).__name__,'message':str(error).replace(lab.password,'<REDACTED>')}
    finally:
        signal.signal(signal.SIGTERM,prior)
        clean=lab.cleanup()
        if not clean: status='CLEANUP_FAILED'
        if dt.datetime.now(dt.timezone.utc)>end: status='WINDOW_EXCEEDED'
        save(out/'result.json',{'result':status,'failure':failure,'cleanup_confirmed':clean,
             'finished_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'production_runtime_claim':False})
        # Never enumerate credential env files into an evidence manifest, even if unlink failed.
        files=sorted(path for path in out.rglob('*') if path.is_file() and path.name not in ('db.env','api.env'))
        (out/'SHA256SUMS').write_text(''.join(sha(path.read_bytes())+'  '+path.relative_to(out).as_posix()+'\n' for path in files),encoding='utf-8')
    print(json.dumps({'result':status,'output':str(out)}))
    return 0 if status=='LAB_RUNTIME_PASS' else 1


def main():
    parser=argparse.ArgumentParser()
    commands=parser.add_subparsers(dest='command',required=True)
    plan=commands.add_parser('plan'); plan.add_argument('output'); plan.add_argument('--run',required=True)
    probe=commands.add_parser('_probe'); probe.add_argument('port',type=int); probe.add_argument('path')
    request=commands.add_parser('_request'); request.add_argument('run'); request.add_argument('case',choices=CASES)
    commands.add_parser('_isolation')
    run=commands.add_parser('run'); run.add_argument('plan'); run.add_argument('output')
    run.add_argument('--plan-sha',required=True); run.add_argument('--authorization',required=True)
    args=parser.parse_args()
    if args.command=='plan':
        save(args.output,make_plan(args.run)); print(sha(Path(args.output).read_bytes()))
    elif args.command=='_probe':
        if args.port not in (8000,8001,9090,9091,18081) or args.path not in ('/readyz','/metrics'):
            raise ValueError('FIXED_LOOPBACK_PROBE_ONLY')
        print(json.dumps(http(args.port,args.path)))
    elif args.command=='_request':
        if os.environ.get('FDS_D03_RUN')!=args.run or sorted(p.name for p in Path('/sys/class/net').iterdir())!=['lo']:
            raise ValueError('REQUEST_REQUIRES_BOUND_ISOLATED_CONTAINER')
        print(json.dumps(http(8000,'/api/v1/transactions',payload(args.run,args.case))))
    elif args.command=='_isolation':
        print(json.dumps({'interfaces':sorted(p.name for p in Path('/sys/class/net').iterdir()),
                          'ipv4_routes':Path('/proc/net/route').read_text().splitlines()[1:],
                          'namespace':os.readlink('/proc/self/ns/net')}))
    elif args.command=='run':
        return run_lab(args.plan,args.plan_sha,args.authorization,args.output)
    return 0


if __name__=='__main__':
    sys.exit(main())
