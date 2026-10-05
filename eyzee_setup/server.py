"""HA ingress-only onboarding screen; no arbitrary command or URL endpoints."""
import hmac, json, os, secrets, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from installer import Installer, SetupError

APP = Installer(config=Path(os.environ.get('EYZEE_CONFIG','/config')),data=Path(os.environ.get('EYZEE_DATA','/data')),payload=Path(__file__).parent/'payload')
CSRF=secrets.token_urlsafe(32)
INGRESS_IP='172.30.32.2'
ADMIN_CACHE={}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def allowed(self):
        if os.environ.get('EYZEE_LOCAL_PREVIEW')=='1' and self.client_address[0]=='127.0.0.1':return True
        if self.client_address[0]!=INGRESS_IP:return False
        user=self.headers.get('X-Remote-User-Id','')
        cached=ADMIN_CACHE.get(user)
        if cached and time.monotonic()-cached[1]<60:return cached[0]
        allowed=APP.api.user_is_admin(user);ADMIN_CACHE[user]=(allowed,time.monotonic());return allowed
    def send(self,status,data,kind='application/json'):
        body=data.encode() if isinstance(data,str) else json.dumps(data).encode()
        self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if not self.allowed():return self.send(403,{'error':'Open EyZEE Setup through Home Assistant.'})
        path=urlsplit(self.path).path
        if path=='/':return self.send(200,(Path(__file__).parent/'index.html').read_text().replace('__CSRF__',CSRF),'text/html')
        if path in ['/api/status','/api/report']:return self.send(200,APP.status())
        self.send(404,{'error':'Page not found.'})
    def do_POST(self):
        if not self.allowed() or not hmac.compare_digest(self.headers.get('X-EyZEE-Token',''),CSRF):return self.send(403,{'error':'Reopen EyZEE Setup and try again.'})
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.send(415,{'error':'Unexpected request.'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<=length<=4096:raise ValueError()
            body=json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(body,dict):raise ValueError()
            path=urlsplit(self.path).path
            if path=='/api/prepare':APP.start(APP.prepare)
            elif path=='/api/discover':
                if not APP.has_service('setup_zigbee_coordinator'):raise SetupError('Prepare your home first.')
                APP.start(APP.discover)
            elif path=='/api/gateway':
                slot=body.get('slot');mac=body.get('mac')
                if type(slot)!=int or not 1<=slot<=4 or not isinstance(mac,str) or len(mac)>32:raise ValueError()
                if APP.status().get('phase')!='choose_gateway':raise SetupError('Find your gateway before connecting.')
                APP.start(APP.connect_gateway,slot,mac)
            elif path=='/api/check':
                if not APP.state.get('vscode_slug'):raise SetupError('Prepare your home first.')
                APP.start(APP.verify_ready)
            else:return self.send(404,{'error':'Action not found.'})
            self.send(202,{'accepted':True})
        except SetupError as err:self.send(409,{'error':str(err)})
        except (ValueError,TypeError):self.send(400,{'error':'The selection could not be read. Please try again.'})
        except Exception:self.send(500,{'error':'Setup could not continue. Please reopen this screen.'})

if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',8099),Handler).serve_forever()
