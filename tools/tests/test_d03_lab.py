"""Safety/negative-path selftests. Synthetic data, no Podman or production access."""
import copy
import contextlib
import datetime as dt
import http.client
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

TOOLS=Path(__file__).resolve().parents[1]/'regression'
sys.path.insert(0,str(TOOLS))
import d03_lab as lab
import d03_fixture as fixture

RUN='202610141600'
TX='12345678-1234-4234-8234-123456789012'


def evidence(case):
    before=dict(zip(lab.METRICS,(4,0,0)))
    skipped=case in ('READ','HTTP')
    delta=(0,1,0) if case=='DB' else (1,0,int(skipped))
    after={k:before[k]+v for k,v in zip(lab.METRICS,delta)}
    body={'transaction_id':TX,'fds_detected':None if skipped else False,
          'fds_evaluation_skipped':skipped,'fds_rules':None if skipped else
          [{'rule_id':key,'triggered':False} for key in ('R01','R02','R04','R07')]}
    rows=[copy.deepcopy(body)]
    if case=='DB': body={'detail':'transaction save failed'}; rows=[]
    response={'status':500 if case=='DB' else 201,'body':json.dumps(body),'elapsed':2.05}
    return response,before,after,rows


class D03Contracts(unittest.TestCase):
    def test_expected_seven_contracts(self):
        for case in lab.CASES:
            with self.subTest(case=case): lab.check_case(case,*evidence(case))

    def test_fail_open_null_fields_must_be_present(self):
        args=evidence('READ'); body=json.loads(args[0]['body']); del body['fds_rules']
        args[0]['body']=json.dumps(body)
        with self.assertRaises(ValueError): lab.check_case('READ',*args)

    def test_db_row_id_or_duplicate_rejected(self):
        for mutation in ('id','duplicate'):
            args=evidence('PRE')
            if mutation=='id': args[3][0]['transaction_id']='wrong'
            else: args[3].append(copy.deepcopy(args[3][0]))
            with self.assertRaises(ValueError): lab.check_case('PRE',*args)

    def test_bool_integer_not_accepted(self):
        args=evidence('READ'); body=json.loads(args[0]['body']); body['fds_evaluation_skipped']=1
        args[0]['body']=json.dumps(body)
        with self.assertRaises(ValueError): lab.check_case('READ',*args)

    def test_db_error_requires_no_row_and_failure_counter(self):
        for which in ('row','metric','body'):
            args=evidence('DB')
            if which=='row': args[3].append({'transaction_id':TX})
            elif which=='metric': args[2][lab.METRICS[1]]=0
            else: args[0]['body']='{"detail":"other failure"}'
            with self.assertRaises(ValueError): lab.check_case('DB',*args)

    def test_immediate_failure_not_read_timeout(self):
        args=evidence('READ'); args[0]['elapsed']=0.01
        with self.assertRaises(ValueError): lab.check_case('READ',*args)

    def test_counter_nan_missing_duplicate_rejected(self):
        text='\n'.join(k+' 0' for k in lab.METRICS)
        self.assertEqual(lab.counter_values(text),dict.fromkeys(lab.METRICS,0))
        for invalid in (text.replace(' 0',' NaN',1),text+'\n'+lab.METRICS[0]+' 0',text.split('\n',1)[1]):
            with self.assertRaises(ValueError): lab.counter_values(invalid)

    def test_real_engine_recovery_and_unrelated_accounts(self):
        self.assertEqual(fixture.mode_for(RUN,lab.payload(RUN,'READ_POST')),('READ_POST','real-engine'))
        for account in ('SIM_rg_'+RUN+'_READ','SIM_d03_'+RUN+'_READ_more','SIM_d03_202610141601_READ'):
            with self.assertRaises(ValueError): fixture.mode_for(RUN,{'account_id':account})

    def test_trigger_scope_and_remove(self):
        sql=lab.trigger_sql(RUN)
        self.assertIn("NEW.account_id = 'SIM_d03_202610141600_DB'",sql)
        self.assertIn("current_database() <> 'fds_lab'",sql)
        self.assertIn('DROP TRIGGER',lab.trigger_sql(RUN,True))
        with self.assertRaises(ValueError): lab.trigger_sql("1'; DROP TABLE x; --")

    def test_rollback_same_pid_after_injection_only(self):
        inject='D03 [123] LOG: D03_INJECT_'+RUN+'\n'
        correct='D03 [123] LOG: statement: ROLLBACK;\n'
        self.assertEqual(lab.rollback_pid(inject+correct,RUN),123)
        for invalid in (correct+inject,inject+correct.replace('[123]','[999]'),inject,
                        "D03 [123] LOG: statement: SELECT 'D03_INJECT_"+RUN+"';\n"+correct,
                        inject+correct+'D03 [888] LOG: D03_INJECT_'+RUN):
            with self.assertRaises(ValueError): lab.rollback_pid(invalid,RUN)

    def test_plan_tamper_or_changed_tool_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'plan.json'; plan=lab.make_plan(RUN); path.write_bytes(lab.encode(plan))
            self.assertEqual(lab.read_plan(path,lab.sha(path.read_bytes())),plan)
            plan['max_posts']=8; path.write_bytes(lab.encode(plan))
            with self.assertRaises(ValueError): lab.read_plan(path,lab.sha(path.read_bytes()))

    def test_expired_naive_missing_or_other_plan_authorization(self):
        plan=lab.make_plan(RUN); now=dt.datetime(2026,10,14,7,tzinfo=dt.timezone.utc)
        auth={'approved':True,'plan_sha256':lab.sha(lab.encode(plan)),
              'start_after':'2026-10-14T15:59:00+09:00','start_before':'2026-10-14T16:05:00+09:00',
              'finish_before':'2026-10-14T16:20:00+09:00','runner_exclusive':True,'lab_db_image_accepted':True,
              'user_authorization_reference':'https://github.com/321Team/example/issues/1',
              'independent_review_reference':'https://github.com/321Team/example/pull/1'}
        self.assertEqual(lab.authorize(plan,auth,now).hour,16)
        for key,value in (('start_before','2026-10-14T15:59:00+09:00'),('start_after','2026-10-14T15:59:00'),
                          ('plan_sha256','0'*64),('approved',False),('runner_exclusive',False),
                          ('independent_review_reference','')):
            changed=dict(auth); changed[key]=value
            with self.assertRaises(ValueError): lab.authorize(plan,changed,now)


class PodmanTmpfsContract(unittest.TestCase):
    def test_execute_db_mounts_use_podman_supported_options_and_group_write(self):
        # Exercise the argv assembled by execute, stopping before any create.
        # Podman v6.1.0 pkg/util/mount_opts.go accepts size/mode, not uid/gid.
        with tempfile.TemporaryDirectory() as temp:
            driver=lab.Lab(lab.make_plan(RUN),temp,dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=15))
            def cmd(*args,**kwargs):
                if args[0]=='info': output='true'
                elif args[0]=='ps': output=''
                elif args[:2]==('image','inspect'):
                    image=args[2]
                    output=json.dumps([{'Id':'a'*64 if image==lab.IMAGES['db'] else image,
                                       'RepoDigests':[image], 'Config':{'User':'26'}}])
                else: self.fail('Unexpected Podman command before DB create: '+str(args))
                return subprocess.CompletedProcess(args,0,output,'')
            def create(role,image,network,extra):
                self.assertEqual((role,image,network),('db',lab.IMAGES['db'],'none'))
                self.assertIn('--user=26:0',extra)
                mounts={}
                for arg in extra:
                    if not arg.startswith('--tmpfs='): continue
                    path,options=arg.removeprefix('--tmpfs=').split(':',1)
                    fields=dict((part.split('=',1)+[None])[:2] for part in options.split(','))
                    self.assertLessEqual(set(fields),{'rw','size','mode'})
                    mounts[path]=fields
                self.assertEqual(mounts['/var/lib/pgsql']['size'],'768m')
                self.assertEqual(mounts['/var/run/postgresql']['size'],'16m')
                for path in ('/var/lib/pgsql','/var/run/postgresql'):
                    mode=int(mounts[path]['mode'],8)
                    self.assertEqual(mode & 0o070,0o070)  # UID26:GID0 can write/search.
                    self.assertEqual(mode & 0o007,0)      # No world access added.
                raise RuntimeError('STOP_BEFORE_CONTAINER_CREATION')
            driver.cmd=cmd
            driver.create=Mock(side_effect=create)
            with patch.object(lab,'runner_worker_active',return_value=False):
                with self.assertRaisesRegex(RuntimeError,'STOP_BEFORE_CONTAINER_CREATION'):
                    driver.execute()
            driver.create.assert_called_once()


class CleanupSafety(unittest.TestCase):
    def test_command_timeout_keeps_redacted_partial_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            driver=lab.Lab(lab.make_plan(RUN),temp,dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=15))
            error=subprocess.TimeoutExpired(['podman','logs'],1,output=driver.password.encode(),stderr=b'partial')
            with patch.object(lab.subprocess,'run',side_effect=error):
                with self.assertRaises(subprocess.TimeoutExpired): driver.cmd('logs','owned')
            receipt=json.loads((Path(temp)/'001-command.json').read_text())
            self.assertTrue(receipt['timed_out'])
            self.assertIsNone(receipt['rc'])
            self.assertEqual(receipt['stdout'],'<REDACTED>')
            self.assertEqual(receipt['stderr'],'partial')

    def test_log_timeout_does_not_skip_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            driver=lab.Lab(lab.make_plan(RUN),temp,dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=15))
            cid='a'*64; driver.created=[{'cid':cid,'name':'owned'}]
            driver.inspect=Mock(return_value={'Config':{'Labels':{'fds.d03.run':RUN}}})
            exists=iter((0,1)); calls=[]
            def cmd(*args,**kwargs):
                calls.append(args)
                if args[0]=='logs': raise subprocess.TimeoutExpired(args,1)
                rc=next(exists) if args[0]=='container' else 0
                return subprocess.CompletedProcess(args,rc,'','')
            driver.cmd=cmd
            self.assertTrue(driver.cleanup())
            self.assertTrue(any(args[0]=='rm' for args in calls))

    def test_other_run_label_never_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            driver=lab.Lab(lab.make_plan(RUN),temp,dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=15))
            driver.created=[{'cid':'b'*64,'name':'other'}]
            driver.inspect=Mock(return_value={'Config':{'Labels':{'fds.d03.run':'other'}}})
            driver.cmd=Mock(return_value=subprocess.CompletedProcess([],0,'',''))
            self.assertFalse(driver.cleanup())
            self.assertFalse(any(call.args[0]=='rm' for call in driver.cmd.call_args_list))

    def test_uncertain_create_absence_not_called_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            driver=lab.Lab(lab.make_plan(RUN),temp,dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=15))
            driver.created=[{'cid':None,'name':'uncertain'}]
            driver.cmd=Mock(return_value=subprocess.CompletedProcess([],1,'',''))
            self.assertFalse(driver.cleanup())


class StagedInvocation(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.stage=Path(temp.name)/'d03'; self.stage.mkdir()
        for name in ('d03_lab.py','d03_fixture.py'):
            shutil.copyfile(TOOLS/name,self.stage/name)

    def test_shallow_container_path_import_needs_no_checkout(self):
        # A deep tempfile alone misses the original parents[2] failure. Execute
        # staged bytes with the exact container __file__, in a fresh interpreter.
        script="""import pathlib,sys
sys.path.insert(0,sys.argv[1])
source=pathlib.Path(sys.argv[1],'d03_lab.py').read_bytes()
scope={'__file__':'/d03/d03_lab.py','__name__':'staged_lab'}
exec(compile(source,'/d03/d03_lab.py','exec'),scope)
assert scope['payload']('202610141600','PRE')['amount']==10000
try: scope['make_plan']('202610141600')
except ValueError as error: assert str(error)=='HOST_REPOSITORY_REQUIRED'
else: raise AssertionError('Host plan must reject the container layout')
"""
        result=subprocess.run([sys.executable,'-I','-S','-B','-c',script,str(self.stage)],
                              capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_staged_probe_reaches_loopback_fixture(self):
        # Exercise the real CLI and its HTTP helper, with no checkout in stage.
        # Port occupancy is a preflight failure; never reuse someone else's server.
        server=fixture.make_server(RUN,18081)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join,2)
        self.addCleanup(server.shutdown)
        result=subprocess.run([sys.executable,'-B',str(self.stage/'d03_lab.py'),
                               '_probe','18081','/readyz'],cwd=self.stage,
                              capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        response=json.loads(result.stdout)
        self.assertEqual(response['status'],200)
        self.assertEqual(json.loads(response['body']),{})

    @unittest.skipUnless(sys.platform=='linux','Linux /proc and /sys readback')
    def test_staged_isolation_subprocess_without_checkout(self):
        result=subprocess.run([sys.executable,'-B',str(self.stage/'d03_lab.py'),'_isolation'],
                              cwd=self.stage,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout)
        self.assertIn('lo',data['interfaces'])
        self.assertIsInstance(data['ipv4_routes'],list)
        self.assertTrue(data['namespace'].startswith('net:['))


class HostPreflight(unittest.TestCase):
    def test_podman_and_docker_config_id_formats_preserve_raw(self):
        for role in ('api','engine'):
            image=lab.IMAGES[role]
            for raw in (image,image.removeprefix('sha256:')):
                obj={'Id':raw,'Config':{'User':'1000'},'RepoDigests':[]}
                record=lab.image_record(role,image,obj)
                self.assertEqual(record['id'],raw)
                self.assertEqual(record['canonical_config_id'],image)

    def test_malformed_or_wrong_config_id_cannot_be_replaced_by_digest(self):
        image=lab.IMAGES['api']
        for raw in ('a'*64,'sha256:'+'a'*64,'','abc','sha512:'+'a'*64,None,123,'g'*64,'sha256:'+image):
            obj={'Id':raw,'Digest':image,'RepoDigests':[image],'Config':{'User':'1000'}}
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                lab.image_record('api',image,obj)

    def test_db_requires_exact_repo_digest_not_config_id(self):
        image=lab.IMAGES['db']
        obj={'Id':'a'*64,'RepoDigests':[image],'Config':{'User':'26'}}
        self.assertEqual(lab.image_record('db',image,obj)['canonical_config_id'],'sha256:'+'a'*64)
        obj['RepoDigests']=[]; obj['Digest']=image.split('@')[1]
        with self.assertRaisesRegex(ValueError,'DB_DIGEST_MISMATCH'): lab.image_record('db',image,obj)

    def test_process_exit_race_still_checks_remaining_workers(self):
        with tempfile.TemporaryDirectory() as temp:
            proc=Path(temp)
            for pid in ('123','456'): (proc/pid).mkdir()
            with patch.object(Path,'iterdir',return_value=iter([proc/'123',proc/'456'])):
                with patch.object(Path,'read_text',side_effect=[FileNotFoundError(), 'Runner.Worker\n']):
                    self.assertTrue(lab.runner_worker_active(proc))
            with patch.object(Path,'iterdir',return_value=iter([proc/'123',proc/'456'])):
                with patch.object(Path,'read_text',side_effect=[ProcessLookupError(), 'python3\n']):
                    self.assertFalse(lab.runner_worker_active(proc))

    def test_process_permission_failure_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            proc=Path(temp); (proc/'123').mkdir()
            with patch.object(Path,'read_text',side_effect=PermissionError()):
                with self.assertRaises(PermissionError): lab.runner_worker_active(proc)


class CaseEvidence(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.out=Path(temp.name)
        self.driver=lab.Lab(lab.make_plan(RUN),self.out,dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=15))

    def prepare(self,case):
        response,before,after,rows=evidence(case)
        for row in rows: row.update(lab.payload(RUN,case))
        self.driver.metrics=Mock(side_effect=[before,after])
        self.driver.inside=Mock(return_value=subprocess.CompletedProcess([],0,json.dumps(response),''))
        return response,rows

    def test_invalid_db_fields_keep_response_and_rows_before_rejection(self):
        response,rows=self.prepare('PRE'); rows[0]['amount']=999
        self.driver.sql=Mock(return_value=json.dumps(rows))
        with self.assertRaisesRegex(ValueError,'DB_REQUEST_FIELDS'): self.driver.run_case('PRE','api','db')
        result=json.loads((self.out/'PRE-result.json').read_text())
        self.assertEqual(result['response'],response)
        self.assertEqual(result['rows'],rows)
        self.driver.inside.assert_called_once()

    def test_primary_and_trigger_cleanup_errors_both_preserved(self):
        response,_=self.prepare('DB'); response['status']=201
        self.driver.inside.return_value.stdout=json.dumps(response)
        cleanup=RuntimeError('drop failed '+self.driver.password)
        self.driver.sql=Mock(side_effect=['','[]',cleanup])
        with self.assertRaisesRegex(ValueError,'DB_FAILURE_CONTRACT') as caught:
            self.driver.run_case('DB','api','db')
        self.assertIs(caught.exception.__cause__,cleanup)
        errors=json.loads((self.out/'DB-errors.json').read_text())
        self.assertEqual(errors['primary']['message'],'DB_FAILURE_CONTRACT')
        self.assertEqual(errors['trigger_cleanup']['message'],'drop failed <REDACTED>')
        self.assertTrue((self.out/'DB-result.json').exists())
        self.assertIn('DROP TRIGGER',self.driver.sql.call_args.args[1])
        self.driver.inside.assert_called_once()

    def test_cleanup_failure_alone_still_stops_after_one_post(self):
        self.prepare('DB'); self.driver.sql=Mock(side_effect=['','[]','','1'])
        with self.assertRaisesRegex(ValueError,'TRIGGER_NOT_REMOVED'): self.driver.run_case('DB','api','db')
        errors=json.loads((self.out/'DB-errors.json').read_text())
        self.assertIsNone(errors['primary'])
        self.assertEqual(errors['trigger_cleanup']['message'],'TRIGGER_NOT_REMOVED')
        self.driver.inside.assert_called_once()

    def test_interrupt_still_removes_trigger_and_is_not_hidden(self):
        self.prepare('DB'); self.driver.inside.side_effect=KeyboardInterrupt()
        self.driver.sql=Mock(side_effect=['','','0'])
        with self.assertRaises(KeyboardInterrupt): self.driver.run_case('DB','api','db')
        self.assertIn('DROP TRIGGER',self.driver.sql.call_args_list[1].args[1])
        self.driver.inside.assert_called_once()


class FixtureWireBehavior(unittest.TestCase):
    def setUp(self):
        self.server=fixture.make_server(RUN,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_lab_helper_get_and_post_reach_actual_fixture(self):
        result=lab.http(self.server.server_port,'/readyz')
        self.assertEqual(result['status'],200)
        body=lab.payload(RUN,'HTTP'); body['transaction_id']=TX
        capture=io.StringIO()
        with contextlib.redirect_stdout(capture):
            result=lab.http(self.server.server_port,'/evaluate',body)
        self.assertEqual(result['status'],500)
        self.assertEqual(json.loads(result['body']),{'fixture':'D03_EXPECTED_ENGINE_HTTP500'})
        self.assertIn(TX,capture.getvalue())

    def test_actual_http500_and_inbound_transaction_logging(self):
        body=lab.payload(RUN,'HTTP'); body['transaction_id']=TX
        capture=io.StringIO()
        with contextlib.redirect_stdout(capture):
            conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=2)
            conn.request('POST','/evaluate',json.dumps(body),{'Content-Type':'application/json'})
            response=conn.getresponse()
            self.assertEqual(response.status,500)
            self.assertIn('D03_EXPECTED_ENGINE_HTTP500',response.read().decode())
            conn.close()
        self.assertIn(TX,capture.getvalue())

    def test_read_case_accepts_body_but_withholds_headers(self):
        body=lab.payload(RUN,'READ'); body['transaction_id']=TX
        capture=io.StringIO()
        with contextlib.redirect_stdout(capture):
            conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=0.1)
            conn.request('POST','/evaluate',json.dumps(body),{'Content-Type':'application/json'})
            with self.assertRaises(TimeoutError): conn.getresponse()
            conn.close()
        self.assertIn('request_received',capture.getvalue())
        self.assertIn('read-timeout',capture.getvalue())


if __name__=='__main__':
    unittest.main()
