"""HTTP tests verify ingress access and CSRF without exposing a HAOS listener."""
import importlib, json, os, tempfile, threading, unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from http.server import ThreadingHTTPServer

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        with patch.dict(os.environ,{'EYZEE_DATA':self.tmp.name,'EYZEE_CONFIG':self.tmp.name}):
            import server
            self.module=importlib.reload(server)
        self.http=ThreadingHTTPServer(('127.0.0.1',0),self.module.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)
    def stop(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
    def request(self,path,token=None,body=None,user=None):
        headers={'Content-Type':'application/json'}
        if user is not None:headers['X-Remote-User-Id']=user
        if token is not None:headers['X-EyZEE-Token']=token
        req=Request('http://127.0.0.1:'+str(self.http.server_port)+path,data=json.dumps(body or {}).encode() if token is not None else None,headers=headers)
        try:
            with urlopen(req) as response:return response.status,response.read()
        except HTTPError as err:return err.code,err.read()
    def test_hostname_endpoint_requires_ready_and_fixed_choice(self):
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'1'}),patch.object(self.module.APP,'start') as start:
            token=self.module.CSRF
            self.assertEqual(409,self.request('/api/hostname',token,{'hostname':'eyzee-core'})[0])
            start.assert_not_called()
            self.module.APP.state['ready']=True
            self.assertEqual(400,self.request('/api/hostname',token,{'hostname':'other'})[0])
            self.assertEqual(403,self.request('/api/hostname','wrong',{'hostname':'eyzee-core'})[0])
            start.assert_not_called()
            self.assertEqual(202,self.request('/api/hostname',token,{'hostname':'eyzee-core'})[0])
            start.assert_called_once_with(self.module.APP.use_home_hostname)

    def test_prepare_requires_boolean_address_choice(self):
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'1'}),patch.object(self.module.APP,'start') as start:
            self.assertEqual(400,self.request('/api/prepare',self.module.CSRF,{'use_core_address':'yes'})[0])
            start.assert_not_called()
            self.assertEqual(202,self.request('/api/prepare',self.module.CSRF,{'use_core_address':True})[0])
            start.assert_called_once_with(self.module.APP.prepare,True)

    def test_direct_access_is_rejected(self):
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'0'}):self.assertEqual(403,self.request('/')[0])
    def test_post_requires_process_csrf_token(self):
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'1'}),patch.object(self.module.APP,'start') as start:
            self.assertEqual(403,self.request('/api/prepare','wrong')[0]);start.assert_not_called()
            self.assertEqual(202,self.request('/api/prepare',self.module.CSRF)[0]);start.assert_called_once()
    def test_ingress_user_must_be_an_admin(self):
        handler=object.__new__(self.module.Handler);handler.client_address=(self.module.INGRESS_IP,12345);handler.headers={'X-Remote-User-Id':'person'}
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'0'}),patch.object(self.module.APP.api,'user_is_admin',return_value=False):self.assertFalse(handler.allowed())

    def test_transient_identity_failure_recovers_without_cached_denial(self):
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'0'}),patch.object(self.module,'INGRESS_IP','127.0.0.1'),patch.object(self.module.APP.api,'user_is_admin',side_effect=[self.module.RetryableError('restarting'),True]) as verify:
            status,body=self.request('/api/status',user='owner')
            self.assertEqual(503,status)
            self.assertNotIn('phase',json.loads(body))
            self.assertNotIn('owner',self.module.ADMIN_CACHE)
            status,body=self.request('/api/status',user='owner')
            self.assertEqual(200,status)
            self.assertEqual('idle',json.loads(body)['phase'])
            self.assertEqual(2,verify.call_count)

    def test_denied_identity_is_rechecked_on_next_request(self):
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'0'}),patch.object(self.module,'INGRESS_IP','127.0.0.1'),patch.object(self.module.APP.api,'user_is_admin',side_effect=[False,True]):
            self.assertEqual(403,self.request('/api/status',user='owner')[0])
            self.assertEqual(200,self.request('/api/status',user='owner')[0])

    def test_recovery_screen_does_not_expose_setup_or_token(self):
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'0'}),patch.object(self.module,'INGRESS_IP','127.0.0.1'),patch.object(self.module.APP.api,'user_is_admin',side_effect=self.module.RetryableError('restarting')):
            status,body=self.request('/',user='owner')
            self.assertEqual(503,status)
            self.assertIn(b'EyZEE is getting things ready',body)
            self.assertNotIn(self.module.CSRF.encode(),body)
            self.assertNotIn(b'id="prepare"',body)
            self.assertIn(b"fetch('api/status'",body)

    def test_direct_request_cannot_use_spoofed_user_header(self):
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'0'}),patch.object(self.module.APP.api,'user_is_admin') as verify:
            self.assertEqual(403,self.request('/api/status',user='owner')[0])
            self.assertEqual(403,self.request('/api/prepare',self.module.CSRF,user='owner')[0])
            verify.assert_not_called()

    def test_missing_identity_cannot_use_another_users_cached_access(self):
        self.module.ADMIN_CACHE['owner']=(True,self.module.time.monotonic())
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'0'}),patch.object(self.module,'INGRESS_IP','127.0.0.1'),patch.object(self.module.APP.api,'user_is_admin') as verify:
            self.assertEqual(403,self.request('/api/status')[0])
            self.assertEqual(403,self.request('/api/report')[0])
            verify.assert_not_called()

    def test_reconnecting_requests_cannot_start_tasks(self):
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'0'}),patch.object(self.module,'INGRESS_IP','127.0.0.1'),patch.object(self.module.APP.api,'user_is_admin',side_effect=self.module.RetryableError('restarting')),patch.object(self.module.APP,'start') as start:
            self.assertEqual(503,self.request('/api/prepare',self.module.CSRF,user='owner')[0])
            start.assert_not_called()

    def test_new_csrf_token_is_available_only_to_authorized_status_not_report(self):
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'1'}):
            self.assertEqual(self.module.CSRF,json.loads(self.request('/api/status')[1])['csrf_token'])
            self.assertNotIn('csrf_token',json.loads(self.request('/api/report')[1]))
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'0'}):
            self.assertNotIn(self.module.CSRF.encode(),self.request('/api/status')[1])

if __name__=='__main__':unittest.main()
