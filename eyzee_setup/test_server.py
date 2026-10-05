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
    def request(self,path,token=None):
        headers={'Content-Type':'application/json'}
        if token is not None:headers['X-EyZEE-Token']=token
        req=Request('http://127.0.0.1:'+str(self.http.server_port)+path,data=b'{}' if token is not None else None,headers=headers)
        try:
            with urlopen(req) as response:return response.status,response.read()
        except HTTPError as err:return err.code,err.read()
    def test_direct_access_is_rejected(self):
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'0'}):self.assertEqual(403,self.request('/')[0])
    def test_post_requires_process_csrf_token(self):
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'1'}),patch.object(self.module.APP,'start') as start:
            self.assertEqual(403,self.request('/api/prepare','wrong')[0]);start.assert_not_called()
            self.assertEqual(202,self.request('/api/prepare',self.module.CSRF)[0]);start.assert_called_once()
    def test_ingress_user_must_be_an_admin(self):
        handler=object.__new__(self.module.Handler);handler.client_address=(self.module.INGRESS_IP,12345);handler.headers={'X-Remote-User-Id':'person'}
        with patch.dict(os.environ,{'EYZEE_LOCAL_PREVIEW':'0'}),patch.object(self.module.APP.api,'user_is_admin',return_value=False):self.assertFalse(handler.allowed())

if __name__=='__main__':unittest.main()
