"""EyZEE HAOS commissioning. Secrets remain in Supervisor or local app data."""
from __future__ import annotations
import copy, hashlib, io, json, os, secrets, shutil, socket, ssl, struct, threading, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import yaml

VERSION = '0.1.0-beta.1'
Z2M_SLUG = '45df7312_zigbee2mqtt'  # Existing proven MG24 service expects this official repository.
REPOSITORIES = ['https://github.com/zigbee2mqtt/hassio-zigbee2mqtt', 'https://github.com/hassio-addons/repository']
CARD_URL = 'https://raw.githubusercontent.com/thomasloven/lovelace-card-mod/v4.2.0/card-mod.js'
CARD_HASH = 'aff7032826d0f68e83cac5fda3934443f054249a2651ec5b993fc875dd2b10c4'

class SetupError(Exception):
    """A message safe to display to the homeowner."""

class RetryableError(SetupError):
    pass

class Tagged:
    def __init__(self, tag, value): self.tag, self.value = tag, value
class Loader(yaml.SafeLoader): pass
class Dumper(yaml.SafeDumper): pass
def strict_mapping(loader,node,deep=False):
    pairs=loader.construct_pairs(node,deep=deep);out={}
    for key,value in pairs:
        if key in out:raise SetupError('The home configuration contains a duplicate setting. An installer review is required.')
        out[key]=value
    return out
Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,strict_mapping)
def load_tag(loader, tag, node):
    if not isinstance(node, yaml.ScalarNode): raise SetupError('This configuration needs an installer review before preparation.')
    return Tagged('!'+tag, loader.construct_scalar(node))
Loader.add_multi_constructor('!', load_tag)
Dumper.add_representer(Tagged, lambda d,v:d.represent_scalar(v.tag,v.value))
def load(text): return yaml.load(text, Loader=Loader) or {}
def dump(data): return yaml.dump(data,Dumper=Dumper,sort_keys=False,allow_unicode=True)
def inc(path,tag='!include'): return Tagged(tag,path)
def sha(data): return hashlib.sha256(data).hexdigest()
def atomic(path:Path, data:bytes, mode=0o600):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.eyzee.tmp')
    with tmp.open('wb') as f: f.write(data);f.flush();os.fsync(f.fileno())
    os.chmod(tmp,mode);os.replace(tmp,path)
def inside(base:Path,relative:str):
    p=(base/relative).resolve()
    if p==base.resolve() or base.resolve() not in p.parents: raise SetupError('A configuration path needs an installer review.')
    return p

class API:
    def __init__(self, token=None, base='http://supervisor'):
        self.token=token or os.environ.get('SUPERVISOR_TOKEN',''); self.base=base
    def call(self,path,method='GET',data=None,timeout=60,core=False):
        if not self.token: raise SetupError('Open EyZEE Setup from Home Assistant on HAOS.')
        url=self.base+('/core/api' if core else '')+path
        req=Request(url,data=json.dumps(data).encode() if data is not None else (b'{}' if method=='POST' else None),method=method,
                    headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        try:
            with urlopen(req,timeout=timeout) as response: result=json.load(response)
        except (HTTPError,URLError,TimeoutError,OSError,ValueError) as err:
            # Do not surface response bodies: app options may include passwords.
            raise RetryableError('A setup step could not connect. Try again; if it repeats, share the setup report.') from err
        if not core:
            if result.get('result')!='ok': raise SetupError('Home Assistant could not complete this setup step. Share the setup report if retrying does not help.')
            return result.get('data',{})
        return result
    def ha(self,path,method='GET',data=None,timeout=60):return self.call(path,method,data,timeout,True)
    def service(self,name,data=None):return self.ha('/services/eyzee_dashboard/'+name,'POST',data or {},timeout=180)
    def user_is_admin(self,user_id):
        # Verify the HA ingress identity rather than treat a hidden sidebar as authorization.
        import websocket
        if not user_id:return False
        ws=None
        try:
            ws=websocket.create_connection(self.base.replace('http://','ws://').replace('https://','wss://')+'/core/websocket',timeout=8)
            if json.loads(ws.recv()).get('type')!='auth_required':return False
            ws.send(json.dumps({'type':'auth','access_token':self.token}))
            if json.loads(ws.recv()).get('type')!='auth_ok':return False
            ws.send(json.dumps({'id':1,'type':'config/auth/list'}))
            result=json.loads(ws.recv())
            if not result.get('success'):return False
            for user in result.get('result',[]):
                if user.get('id')==user_id:return bool(user.get('is_active') and not user.get('system_generated') and (user.get('is_owner') or 'system-admin' in user.get('group_ids',[])))
            return False
        except Exception:return False
        finally:
            if ws is not None:ws.close()


def mqtt_snapshot(service:dict,timeout=12):
    """Read-only MQTT 3.1.1 probe: authenticated connection and retained bridge data."""
    def string(s):
        b=str(s).encode();return struct.pack('!H',len(b))+b
    def packet(first,body):
        n=len(body);length=bytearray()
        while True:
            b=n%128;n//=128;length.append(b|(128 if n else 0))
            if not n:break
        return bytes([first])+length+body
    def read_exact(sock,n):
        b=b''
        while len(b)<n:
            chunk=sock.recv(n-len(b))
            if not chunk:raise SetupError('The home connection closed unexpectedly. Try again.')
            b+=chunk
        return b
    def read_packet(sock):
        first=read_exact(sock,1)[0];size=0;mult=1
        for _ in range(4):
            b=read_exact(sock,1)[0];size+=(b&127)*mult;mult*=128
            if not b&128:break
        else:raise SetupError('The home connection returned an unexpected response.')
        if size>2_000_000:raise SetupError('The home connection returned an oversized response.')
        return first,read_exact(sock,size)
    flags=2;payload=string('eyzee-setup-'+secrets.token_hex(4))
    if service.get('username') is not None:flags|=128;payload+=string(service['username'])
    if service.get('password') is not None:flags|=64;payload+=string(service['password'])
    sock=socket.create_connection((service['host'],int(service.get('port',1883))),timeout=timeout)
    if service.get('ssl'):sock=ssl.create_default_context().wrap_socket(sock,server_hostname=service['host'])
    with sock:
        sock.settimeout(timeout);sock.sendall(packet(0x10,string('MQTT')+bytes([4,flags])+struct.pack('!H',30)+payload))
        first,body=read_packet(sock)
        if first!=0x20 or len(body)!=2 or body[1]!=0:raise SetupError('The home connection could not sign in. Retry preparation.')
        topics=['zigbee2mqtt/bridge/state','zigbee2mqtt/bridge/info','zigbee2mqtt/bridge/converters']
        sock.sendall(packet(0x82,b'\x00\x01'+b''.join(string(t)+b'\x00' for t in topics)))
        result={};end=time.monotonic()+timeout
        while time.monotonic()<end:
            sock.settimeout(max(.1,end-time.monotonic()))
            try:first,body=read_packet(sock)
            except socket.timeout:break
            if first>>4==3:
                n=struct.unpack('!H',body[:2])[0];topic=body[2:2+n].decode();offset=2+n
                if (first>>1)&3:offset+=2
                try: result[topic]=json.loads(body[offset:])
                except ValueError:result[topic]=body[offset:].decode(errors='replace')
                if len(result)==3:break
        sock.sendall(b'\xe0\x00');return result

class Installer:
    def __init__(self,config=Path('/config'),data=Path('/data'),payload=Path('/app/payload'),api=None,sleeper=time.sleep):
        self.config,self.data,self.payload=config,data,payload;self.api=api or API();self.sleep=sleeper
        self.lock=threading.Lock();self.busy=False;self.data.mkdir(parents=True,exist_ok=True)
        self.state=self.read_state();self.state.setdefault('events',[])
        if self.state.get('busy') or self.state.get('ready'):
            self.state.update(busy=False,ready=False,phase='interrupted',message='Press Prepare My Home to continue and check your connection safely.')
            self.save()
    def read_state(self):
        p=self.data/'progress.json'
        return json.loads(p.read_text()) if p.exists() else {'phase':'idle','message':'Ready to prepare your home.','owned_apps':[],'files':{},'events':[]}
    def save(self):atomic(self.data/'progress.json',json.dumps(self.state,indent=2).encode())
    def status(self):
        with self.lock:return {k:copy.deepcopy(v) for k,v in self.state.items() if k in {'phase','message','busy','events','gateways','release','backup','ready','support_code','checks','app_versions'}}
    def stage(self,phase,message):
        with self.lock:
            self.state.update(phase=phase,message=message,release=VERSION)
            self.state['events']=(self.state.get('events',[])+[{'stage':phase,'message':message,'time':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}])[-50:];self.save()
    def start(self,task,*args):
        with self.lock:
            if self.busy:raise SetupError('Preparation is already running.')
            self.busy=True;self.state['busy']=True;self.state['ready']=False;self.save()
        def run():
            try:task(*args)
            except Exception as err:
                failed=self.state.get('phase','unknown')
                self.stage('failed',str(err) if isinstance(err,SetupError) else 'Preparation stopped safely. Please share the setup report with support.')
                with self.lock:self.state['support_code']=failed;self.save()
            finally:
                with self.lock:self.busy=False;self.state['busy']=False;self.save()
        threading.Thread(target=run,daemon=True).start()
    def wait(self,fn,timeout=180):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:
                v=fn()
                if v:return v
            except RetryableError:pass
            self.sleep(3)
        raise SetupError('This step took longer than expected. Check power and network, then try again.')
    def write_owned(self,relative,content,replace=False):
        dest=inside(self.config,relative);b=content.encode() if isinstance(content,str) else content
        if dest.exists():
            old=dest.read_bytes()
            if old==b:return
            if not replace or self.state['files'].get(relative)!=sha(old):
                raise SetupError('Existing home files need an installer review. Your current files have been preserved.')
            backup=inside(self.data/'file-backups',relative);backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,backup)
        atomic(dest,b,0o600 if relative.endswith('configuration.yaml') else 0o644)
        self.state['files'][relative]=sha(b);self.save()
    def config_plan(self):
        self.pending_packages={};self.theme_target=None
        p=self.config/'configuration.yaml'
        text=p.read_text() if p.exists() else 'default_config:\n'
        c=load(text)
        if not isinstance(c,dict):raise SetupError('The existing home configuration needs an installer review.')
        existing='eyzee_dashboard' in c
        for key in ('homeassistant','frontend','lovelace'):
            if key in c and c[key] is not None and not isinstance(c[key],dict):
                raise SetupError('Your existing home uses a configuration layout that needs an installer review.')
        if not existing:
            ha=c.setdefault('homeassistant',{}) or {};c['homeassistant']=ha
            packages=ha.setdefault('packages',{})
            entries={'eyzee_setup_core':inc('eyzee/installation/core.yaml'),'eyzee_smart_behaviours':inc('eyzee/generated_smart_behaviours.yaml')}
            if isinstance(packages,dict):
                for key,value in entries.items():
                    if key in packages:
                        current=packages[key]
                        if not isinstance(current,Tagged) or current.tag!=value.tag or current.value!=value.value:
                            raise SetupError('EyZEE configuration already exists and needs an installer review.')
                    packages[key]=value
            elif isinstance(packages,Tagged) and packages.tag=='!include_dir_named':
                directory=inside(self.config,packages.value)
                for key,value in entries.items():
                    target=directory/(key+'.yaml')
                    if target.exists() and str(target.relative_to(self.config)) not in self.state['files']:raise SetupError('EyZEE configuration already exists and needs an installer review.')
                    self.pending_packages=getattr(self,'pending_packages',{})
                    self.pending_packages[str(target.relative_to(self.config))]=dump(self.core_package()) if key=='eyzee_setup_core' else '!include /config/eyzee/generated_smart_behaviours.yaml\n'
            else:raise SetupError('Your package configuration needs an installer review before adding EyZEE.')
        # Copy themes into the existing theme directory rather than replace its include.
        frontend=c.setdefault('frontend',{}) or {};c['frontend']=frontend
        themes=frontend.get('themes')
        if themes is None:frontend['themes']=inc('eyzee/themes','!include_dir_merge_named')
        elif isinstance(themes,dict):themes.setdefault('EyZEE Home',yaml.safe_load((self.payload/'config/eyzee/themes/eyzee_home.yaml').read_text())['EyZEE Home'])
        elif isinstance(themes,Tagged) and themes.tag=='!include_dir_merge_named':
            dest=inside(self.config,themes.value)/'eyzee_home.yaml'
            self.theme_target=str(dest.relative_to(self.config))
        else:raise SetupError('Your theme configuration needs an installer review.')
        modules=frontend.setdefault('extra_module_url',[])
        if not isinstance(modules,list):raise SetupError('Your dashboard resources need an installer review.')
        if '/local/eyzee/card-mod.js' not in modules:modules.append('/local/eyzee/card-mod.js')
        lovelace=c.setdefault('lovelace',{}) or {};c['lovelace']=lovelace
        dashboards=lovelace.setdefault('dashboards',{})
        supplied=yaml.safe_load((self.payload/'config/eyzee/dashboards.yaml').read_text())
        if isinstance(dashboards,dict):
            for key,value in supplied.items():
                if key in dashboards and dashboards[key]!=value:raise SetupError('An existing dashboard needs an installer review.')
                dashboards[key]=value
        elif isinstance(dashboards,Tagged) and dashboards.tag=='!include' and dashboards.value=='eyzee/dashboards.yaml':pass
        else:raise SetupError('Your dashboard configuration needs an installer review.')
        # Add custom quirks without redirecting an existing quirk path.
        zha=c.get('zha')
        if zha is None:c['zha']={'enable_quirks':True,'custom_quirks_path':'/config/custom_zha_quirks'}
        elif isinstance(zha,dict):
            custom=zha.get('custom_quirks_path','/config/custom_zha_quirks')
            if custom!='/config/custom_zha_quirks':raise SetupError('Your existing device-support directory needs an installer review.')
            zha['enable_quirks']=True;zha['custom_quirks_path']=custom
        else:raise SetupError('Your device-support configuration needs an installer review.')
        return text,dump(c)
    def core_package(self):
        d={domain:inc('/config/eyzee/helpers/'+filename+'.yaml') for domain,filename in [('input_number','input_numbers'),('input_boolean','input_booleans'),('input_select','input_selects'),('input_text','input_texts'),('input_datetime','input_datetimes')]}
        d.update(eyzee_dashboard={},script=inc('/config/eyzee/scripts','!include_dir_merge_named'));return d
    def inventory(self):return self.api.call('/addons').get('addons',[])
    def app_info(self,slug):return self.api.call('/addons/'+slug+'/info')
    def ensure_app(self,slug):
        installed={a['slug'] for a in self.inventory()}
        if slug not in installed:
            if slug not in self.state['owned_apps']:self.state['owned_apps'].append(slug);self.save()
            self.api.call('/store/addons/'+slug+'/install','POST',{},timeout=900)
        if slug in self.state['owned_apps']:
            self.api.call('/addons/'+slug+'/options','POST',{'boot':'auto','auto_update':False})
        info=self.app_info(slug)
        self.state.setdefault('app_versions',{})[slug]=info.get('version','unknown');self.save()
        return info
    def options(self,slug,changes):
        current=self.app_info(slug)['options'];current.update(changes)
        result=self.api.call('/addons/'+slug+'/options/validate','POST',current)
        if not result.get('valid',False):raise SetupError('An app requires updated setup settings. Please share the setup report.')
        self.api.call('/addons/'+slug+'/options','POST',{'options':current,'boot':'auto','auto_update':False})
    def start_app(self,slug):
        if self.app_info(slug).get('state')!='started':self.api.call('/addons/'+slug+'/start','POST',{},timeout=180)
        self.wait(lambda:self.app_info(slug).get('state')=='started')
    def mqtt_entries(self):return [e for e in self.api.ha('/config/config_entries/entry') if e.get('domain')=='mqtt' and e.get('source')!='ignore']
    def connect_mqtt(self,service):
        entries=self.mqtt_entries()
        if entries:
            if any(e.get('state')=='loaded' for e in entries):return
            raise SetupError('Your existing home connection is offline. Restore that connection before preparing EyZEE.')
        flows=self.api.ha('/config/config_entries/flow')
        discovered=next((f for f in flows if f.get('handler')=='mqtt' and f.get('context',{}).get('source')=='hassio'),None)
        if discovered:
            flow=self.api.ha('/config/config_entries/flow/'+discovered['flow_id'])
            if flow.get('step_id')=='hassio_confirm':flow=self.api.ha('/config/config_entries/flow/'+flow['flow_id'],'POST',{})
        else:
            flow=self.api.ha('/config/config_entries/flow','POST',{'handler':'mqtt'})
            if flow.get('type')=='menu' and 'broker' in flow.get('menu_options',[]):
                flow=self.api.ha('/config/config_entries/flow/'+flow['flow_id'],'POST',{'next_step_id':'broker'})
            if flow.get('step_id')=='broker':
                flow=self.api.ha('/config/config_entries/flow/'+flow['flow_id'],'POST',{'broker':service['host'],'port':int(service['port']),'username':service.get('username',''),'password':service.get('password','')})
        if flow.get('type')!='create_entry' and not self.mqtt_entries():raise SetupError('The home connection needs a setup update. Share the report; no manual technical settings are required.')
        self.wait(lambda:any(e.get('state')=='loaded' for e in self.mqtt_entries()),90)
    def prepare(self):
        self.stage('checking','Checking your home.')
        self.api.call('/supervisor/info');self.api.call('/os/info');self.api.ha('/config');self.verify_payload()
        if shutil.disk_usage(self.config).free<3*1024**3:raise SetupError('Your system needs at least 3 GB of free storage before preparation.')
        original,planned=self.config_plan()  # Refuse incompatible layouts before app or file writes.
        # Unknown prior EyZEE code is preserved. This is an installer, not an unreviewed upgrade.
        for src in (self.payload/'config/custom_components/eyzee_dashboard').glob('*'):
            dest=self.config/'custom_components/eyzee_dashboard'/src.name
            if dest.exists() and dest.read_bytes()!=src.read_bytes() and self.state['files'].get(str(dest.relative_to(self.config)))!=sha(dest.read_bytes()):
                raise SetupError('An earlier EyZEE version is installed. Please use a fresh test system or ask your installer to review the update.')
        zpath=self.config/'zigbee2mqtt/configuration.yaml'
        zdata=yaml.safe_load(zpath.read_text()) or {} if zpath.exists() else {}
        configured=bool((zdata.get('serial') or {}).get('port'))
        self.state['existing_network']=configured;self.save()
        self.stage('backup','Saving a recovery copy of your home.')
        if not self.state.get('backup'):
            backup=self.api.call('/backups/new/full','POST',{'name':'Before EyZEE Setup '+VERSION},timeout=1200)
            if not backup.get('slug'):raise SetupError('The recovery copy could not be confirmed. Preparation has stopped.')
            self.state['backup']=backup['slug'];self.save()
        self.stage('apps','Preparing the supporting apps. This can take several minutes.')
        existing={a['slug'] for a in self.inventory()}
        # Preserve an external MQTT integration; automated gateway setup here requires the HAOS broker.
        if self.mqtt_entries() and 'core_mosquitto' not in existing:
            raise SetupError('Your existing home uses another connection service. An installer should review it before adding EyZEE.')
        for url in REPOSITORIES:
            repos=self.api.call('/store/repositories')
            repos=repos.get('repositories',[]) if isinstance(repos,dict) else repos
            if not any(r.get('source')==url or r.get('url')==url for r in repos):self.api.call('/store/repositories','POST',{'repository':url})
        self.api.call('/store/reload','POST',{},timeout=180)
        store=self.api.call('/store/addons')
        apps=store.get('addons',[]) if isinstance(store,dict) else store
        vscode=next((a['slug'] for a in apps if a.get('name')=='Studio Code Server'),None)
        if not vscode:raise SetupError('The support app download is unavailable. Check internet access and retry.')
        self.state['vscode_slug']=vscode;self.save()
        for slug in ['core_mosquitto','core_ssh',Z2M_SLUG,vscode]:self.ensure_app(slug)
        if 'core_ssh' in self.state['owned_apps']:
            credentials=self.data/'support-credentials.json'
            creds=json.loads(credentials.read_text()) if credentials.exists() else {'terminal_password':secrets.token_urlsafe(32)}
            atomic(credentials,json.dumps(creds).encode())
            self.options('core_ssh',{'password':creds['terminal_password']})
            # Keep network SSH closed; support is available through authenticated HA ingress.
            self.api.call('/addons/core_ssh/options','POST',{'network':{'22/tcp':None}})
        self.start_app('core_mosquitto');self.start_app('core_ssh');self.start_app(vscode)
        self.stage('connection','Connecting the home services.')
        service=self.wait(lambda:self.api.call('/services/mqtt'),90)
        mqtt_snapshot(service,3)
        self.connect_mqtt(service)
        if not configured:
            # Do not overwrite any configured network, even if the app is stopped.
            if zpath.exists() and (zdata.get('serial') or {}).get('port'):raise SetupError('A Zigbee network already exists. Its settings have been preserved.')
            # Let the installed Zigbee2MQTT version generate its own schema/defaults.
            if not zpath.exists():
                self.options(Z2M_SLUG,{'data_path':'/config/zigbee2mqtt','force_onboarding':True})
                self.start_app(Z2M_SLUG)
                self.wait(lambda:zpath.exists(),90)
                self.api.call('/addons/'+Z2M_SLUG+'/stop','POST',{},timeout=180)
                self.wait(lambda:self.app_info(Z2M_SLUG).get('state')!='started',60)
                zdata=yaml.safe_load(zpath.read_text()) or {}
            zdata['onboarding']=False
            zdata.setdefault('homeassistant',{})['enabled']=True
            if not zdata.get('mqtt',{}).get('server'):
                zdata['mqtt']={'base_topic':'zigbee2mqtt','server':'mqtt://'+service['host']+':'+str(service['port']),'user':service.get('username'),'password':service.get('password')}
            if zdata.get('mqtt',{}).get('base_topic','zigbee2mqtt')!='zigbee2mqtt':
                raise SetupError('Your existing Zigbee connection uses custom settings. An installer review is required.')
            zdata.setdefault('serial',{})
            # Required by current Z2M versions for the user's trusted converters.
            zdata.setdefault('advanced',{})['enable_external_js']=True
            if zpath.exists():
                atomic(self.data/'zigbee2mqtt-before.yaml',zpath.read_bytes())
                self.state['files']['zigbee2mqtt/configuration.yaml']=sha(zpath.read_bytes());self.save()
            self.write_owned('zigbee2mqtt/configuration.yaml',yaml.safe_dump(zdata,sort_keys=False),replace=True)
            self.options(Z2M_SLUG,{'data_path':'/config/zigbee2mqtt','force_onboarding':False,'mqtt':{},'serial':{}})
        elif self.app_info(Z2M_SLUG).get('options',{}).get('data_path')!='/config/zigbee2mqtt':
            raise SetupError('Your existing Zigbee files use another location. Their settings have been preserved for installer review.')
        if configured:
            if zdata.get('mqtt',{}).get('base_topic','zigbee2mqtt')!='zigbee2mqtt':raise SetupError('Your existing Zigbee connection uses custom settings. An installer review is required.')
            if not zdata.get('advanced',{}).get('enable_external_js',False):
                atomic(self.data/'zigbee2mqtt-before.yaml',zpath.read_bytes())
                self.state['files']['zigbee2mqtt/configuration.yaml']=sha(zpath.read_bytes());self.save()
                zdata.setdefault('advanced',{})['enable_external_js']=True
                self.write_owned('zigbee2mqtt/configuration.yaml',yaml.safe_dump(zdata,sort_keys=False),replace=True)
                self.state['z2m_restart_needed']=True;self.save()
        self.stage('files','Preparing EyZEE Home and device support.')
        self.verify_payload()
        for src in sorted((self.payload/'config').rglob('*')):
            if not src.is_file():continue
            rel=str(src.relative_to(self.payload/'config'))
            # All mutable installation data and generated pages are create-only.
            preserve=rel.startswith('eyzee/state/') or rel in {'eyzee/generated_smart_behaviours.yaml','eyzee/templates/fans.yaml','eyzee/ui/eyzee-room.yaml','eyzee/ui/eyzee-master.yaml','eyzee/ui/setup/add_device.yaml','eyzee/ui/setup/device_setup.yaml'}
            if preserve and (self.config/rel).exists():continue
            self.write_owned(rel,src.read_bytes(),replace=True)
        if getattr(self,'theme_target',None):self.write_owned(self.theme_target,(self.payload/'config/eyzee/themes/eyzee_home.yaml').read_bytes())
        for src in (self.payload/'device-support/zigbee2mqtt/external_converters').glob('*'):
            self.write_owned('zigbee2mqtt/external_converters/'+src.name,src.read_bytes(),replace=True)
        with urlopen(CARD_URL,timeout=45) as response:card=response.read(1_000_001)
        if sha(card)!=CARD_HASH:raise SetupError('A dashboard download could not be verified. Preparation has stopped.')
        self.write_owned('www/eyzee/card-mod.js',card,replace=True)
        self.write_owned('eyzee/installation/core.yaml',dump(self.core_package()))
        for rel,content in getattr(self,'pending_packages',{}).items():self.write_owned(rel,content)
        # configuration.yaml has its own recovery copy; installation data never gets reset.
        atomic(self.data/'configuration-before.yaml',original.encode())
        config_path=self.config/'configuration.yaml';atomic(config_path,planned.encode())
        self.stage('checking_configuration','Checking EyZEE Home before restarting.')
        try:self.api.call('/core/check','POST',{},timeout=180)
        except Exception:
            atomic(config_path,original.encode());raise SetupError('The home configuration check failed. Your previous configuration has been restored. Share the setup report.')
        self.stage('restarting','Starting EyZEE Home. Please keep this screen open.')
        try:self.api.call('/core/restart','POST',{},timeout=180)
        except RetryableError:pass  # Core may close its connection once restart is accepted.
        self.wait(lambda:self.has_service('setup_zigbee_coordinator'),240)
        self.api.service('refresh_device_inventory');self.api.service('build_room_views')
        self.api.service('discover_eyzee_devices')
        if configured:
            self.start_app(Z2M_SLUG)
            if self.state.get('z2m_restart_needed'):
                self.api.call('/addons/'+Z2M_SLUG+'/restart','POST',{},timeout=180)
                self.wait(lambda:self.app_info(Z2M_SLUG).get('state')=='started',120)
                self.state['z2m_restart_needed']=False;self.save()
            self.verify_ready()
        else:self.discover()
    def verify_payload(self):
        manifest=json.loads((self.payload.parent/'payload-hashes.json').read_text())
        for rel,expected in manifest.items():
            p=inside(self.payload,rel)
            if not p.is_file() or sha(p.read_bytes())!=expected:raise SetupError('The EyZEE download could not be verified. Please reinstall the Setup app.')
    def has_service(self,name):
        return any(s.get('domain')=='eyzee_dashboard' and name in s.get('services',{}) for s in self.api.ha('/services'))
    def discover(self):
        self.stage('finding_gateway','Looking for your Zigbee gateway. Check its power and Ethernet cable.')
        self.api.service('identify_mg24')
        gateways=[]
        for slot in range(1,5):
            state=self.api.ha('/states/sensor.eyzee_zigbee_gateway_'+str(slot));a=state.get('attributes',{})
            if a.get('can_setup'):
                gateways.append({'slot':slot,'mac':a.get('mac_address'),'address':a.get('ip_address'),'name':'EyZEE Zigbee Gateway'})
        with self.lock:self.state['gateways']=gateways;self.save()
        self.stage('choose_gateway','Choose your Zigbee gateway.' if gateways else 'We could not find a ready gateway. Check its power and Ethernet cable, then press Find Again.')
    def connect_gateway(self,slot,mac):
        if not self.state.get('gateways'):raise SetupError('Find your gateway before connecting.')
        candidate=next((g for g in self.state['gateways'] if g['slot']==slot and g['mac']==mac),None)
        if not candidate:raise SetupError('The gateway list changed. Find your gateway again.')
        self.stage('connecting_gateway','Connecting your Zigbee gateway.')
        # Re-discover and pin the user's selection to MAC, not a stale slot.
        self.api.service('identify_mg24');found=None
        for index in range(1,5):
            a=self.api.ha('/states/sensor.eyzee_zigbee_gateway_'+str(index)).get('attributes',{})
            if a.get('mac_address')==mac and a.get('can_setup'):found=index;break
        if not found:raise SetupError('The selected gateway is no longer ready. Check its connection and find it again.')
        self.api.service('prepare_zigbee_coordinator',{'slot':found})
        preflight=self.api.ha('/states/sensor.eyzee_zigbee_coordinator_setup')
        if not preflight.get('attributes',{}).get('ready'):raise SetupError('The gateway cannot be set up safely. Your existing network has been preserved.')
        self.api.service('setup_zigbee_coordinator',{'slot':found})
        def connected():
            s=self.api.ha('/states/sensor.eyzee_zigbee_coordinator_setup')
            if s['state']=='failed':raise SetupError('The gateway did not connect. Its previous settings were restored; please retry.')
            return s.get('attributes',{}).get('ready') and s['state']=='ready'
        self.wait(connected,240);self.verify_ready()
    def verify_ready(self):
        self.stage('verifying','Checking that your home is ready.')
        if not any(e.get('state')=='loaded' for e in self.mqtt_entries()):raise SetupError('The home connection is not ready yet. Retry preparation.')
        service=self.api.call('/services/mqtt')
        def online_snapshot():
            snapshot=mqtt_snapshot(service,5);bridge=snapshot.get('zigbee2mqtt/bridge/state',{})
            online=bridge.get('state')=='online' if isinstance(bridge,dict) else bridge=='online'
            return snapshot if online and snapshot.get('zigbee2mqtt/bridge/info') and 'zigbee2mqtt/bridge/converters' in snapshot else None
        snapshot=self.wait(online_snapshot,90)
        bridge=snapshot.get('zigbee2mqtt/bridge/state',{})
        online=bridge.get('state')=='online' if isinstance(bridge,dict) else bridge=='online'
        serial=(snapshot.get('zigbee2mqtt/bridge/info',{}).get('config',{}).get('serial',{}) or {}).get('port')
        configured=(yaml.safe_load((self.config/'zigbee2mqtt/configuration.yaml').read_text()).get('serial',{}) or {}).get('port')
        if not online or not serial or serial!=configured:raise SetupError('The Zigbee gateway is not connected yet. Check its power and network, then retry.')
        converters=snapshot.get('zigbee2mqtt/bridge/converters',[])
        loaded={c.get('name') for c in converters if isinstance(c,dict)} if isinstance(converters,list) else set()
        expected={p.name for p in (self.payload/'device-support/zigbee2mqtt/external_converters').glob('*')}
        if not expected<=loaded:raise SetupError('Some device support files did not load. Share the setup report so we can match them to this Zigbee version.')
        for slug in ['core_mosquitto','core_ssh',Z2M_SLUG,self.state['vscode_slug']]:
            if self.app_info(slug).get('state')!='started':raise SetupError('A supporting app has stopped. Please retry preparation.')
        for service_name in ['setup_zigbee_coordinator','build_room_views','refresh_device_inventory']:
            if not self.has_service(service_name):raise SetupError('EyZEE Home did not finish starting. Retry preparation.')
        with self.lock:self.state.update(ready=True,checks={'home':True,'connection':True,'gateway':True,'device_support':True,'support_apps':True});self.save()
        self.stage('ready','Your home is ready. Open EyZEE Home to add your rooms and devices.')
