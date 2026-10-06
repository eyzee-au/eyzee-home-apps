import copy, io, json, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
import installer as m

HERE=Path(__file__).parent
CARD_BYTES=b'test dashboard resource'

class FakeAPI:
    def __init__(self,config):
        self.config=config;self.calls=[];self.apps={};self.entries=[];self.repos=[];self.fail_check=False;self.flows=[]
        self.gateway_slots={1:('AA:BB:CC:DD:EE:01','192.168.1.40'),2:('AA:BB:CC:DD:EE:02','192.168.1.41')};self.setup={}
    def call(self,path,method='GET',data=None,timeout=60,core=False):
        self.calls.append((path,method,copy.deepcopy(data)))
        if path in ['/supervisor/info','/os/info']:return {'healthy':True,'arch':'aarch64'}
        if path=='/addons':return {'addons':[{'slug':s} for s in self.apps]}
        if path=='/store/addons':return {'addons':[{'slug':'a0d7b954_vscode','name':'Studio Code Server'}]}
        if path=='/store/repositories':
            if method=='POST':self.repos.append({'source':data['repository']})
            return self.repos
        if path=='/store/reload':return {}
        if path=='/backups/new/full':return {'slug':'backup-confirmed'}
        if path=='/core/check':
            if self.fail_check:raise m.SetupError('check failed')
            return {}
        if path=='/core/restart':return {}
        if path=='/services/mqtt':return {'host':'core-mosquitto','port':1883,'username':'addons','password':'do-not-display'}
        if path.startswith('/store/addons/') and path.endswith('/install'):
            slug=path.split('/')[3];self.apps[slug]={'slug':slug,'state':'stopped','options':{'data_path':'/config/zigbee2mqtt'} if slug==m.Z2M_SLUG else {'logins':[]}};return {}
        if path.startswith('/addons/'):
            slug=path.split('/')[2];app=self.apps[slug]
            if path.endswith('/info'):return copy.deepcopy(app)
            if path.endswith('/options/validate'):return {'valid':True}
            if path.endswith('/options'):
                if 'options' in data:app['options']=data['options']
                return {}
            if path.endswith(('/start','/restart')):
                app['state']='started'
                if slug==m.Z2M_SLUG and not (self.config/'zigbee2mqtt/configuration.yaml').exists():
                    m.atomic(self.config/'zigbee2mqtt/configuration.yaml',b'version: 5\nmqtt:\n  server: mqtt://core-mosquitto:1883\n  user: addons\n  password: do-not-display\n  base_topic: zigbee2mqtt\nserial: {}\nadvanced:\n  channel: 11\n  network_key: GENERATE\n  enable_external_js: false\n')
                return {}
            if path.endswith('/stop'):app['state']='stopped';return {}
        raise AssertionError(('Unexpected Supervisor API',path,method,data))
    def ha(self,path,method='GET',data=None,timeout=60):
        self.calls.append(('HA'+path,method,copy.deepcopy(data)))
        if path=='/config':return {'version':'2026.9.4'}
        if path=='/config/config_entries/entry':return self.entries
        if path=='/config/config_entries/flow':
            if method=='GET':raise AssertionError('HA rejects flow enumeration over REST with HTTP 405')
            return {'flow_id':'flow1','type':'menu','menu_options':['addon','broker']}
        if path=='/config/config_entries/flow/flow1':
            if method=='GET':return {'flow_id':'flow1','type':'form','step_id':'hassio_confirm'}
            if data.get('next_step_id')=='broker':return {'flow_id':'flow1','type':'form','step_id':'broker'}
            self.entries=[{'domain':'mqtt','state':'loaded'}];return {'type':'create_entry'}
        if path=='/services':return [{'domain':'eyzee_dashboard','services':{s:{} for s in ['setup_zigbee_coordinator','build_room_views','refresh_device_inventory']}}]
        if path.startswith('/states/sensor.eyzee_zigbee_gateway_'):
            slot=int(path[-1]);g=self.gateway_slots.get(slot)
            return {'attributes':{'can_setup':bool(g),'mac_address':g[0] if g else None,'ip_address':g[1] if g else None}}
        if path=='/states/sensor.eyzee_zigbee_coordinator_setup':return self.setup
        raise AssertionError(('Unexpected HA API',path,method,data))
    def ws(self,command):
        self.calls.append(('WS','GET',copy.deepcopy(command)))
        if command=={'type':'config_entries/flow/progress'}:return copy.deepcopy(self.flows)
        raise AssertionError(command)
    def service(self,name,data=None):
        self.calls.append((name,'SERVICE',copy.deepcopy(data)))
        if name=='prepare_zigbee_coordinator':self.setup={'state':'ready','attributes':{'ready':True}}
        if name=='setup_zigbee_coordinator':
            ip=self.gateway_slots[data['slot']][1]
            p=self.config/'zigbee2mqtt/configuration.yaml';d=m.load(p.read_text());d['serial']={'port':'tcp://'+ip+':6638','adapter':'ember'};m.atomic(p,m.dump(d).encode())
            self.apps[m.Z2M_SLUG]['state']='started';self.setup={'state':'ready','attributes':{'ready':True,'rollback_performed':False}}
        return []

class InstallerTests(unittest.TestCase):
    def test_mqtt_discovery_uses_websocket_and_confirms_existing_flow(self):
        self.api.flows=[{'handler':'mqtt','flow_id':'flow1','context':{'source':'hassio'}}]
        self.i.connect_mqtt({'host':'core-mosquitto','port':1883})
        self.assertTrue(any(e.get('state')=='loaded' for e in self.api.entries))
        self.assertIn(('WS','GET',{'type':'config_entries/flow/progress'}),self.api.calls)
        self.assertNotIn(('HA/config/config_entries/flow','GET',None),self.api.calls)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.config=self.root/'config';self.config.mkdir();self.data=self.root/'data'
        self.api=FakeAPI(self.config);self.i=m.Installer(self.config,self.data,HERE/'payload',self.api,sleeper=lambda n:None)
        (self.config/'configuration.yaml').write_text('default_config:\nhttp:\n  server_port: 8123\n')
    def snapshot(self,*args):
        p=self.config/'zigbee2mqtt/configuration.yaml';serial=m.load(p.read_text()).get('serial',{}) if p.exists() else {}
        return {'zigbee2mqtt/bridge/state':{'state':'online'},'zigbee2mqtt/bridge/info':{'config':{'serial':serial}},'zigbee2mqtt/bridge/converters':[{'name':p.name} for p in (HERE/'payload/device-support/zigbee2mqtt/external_converters').glob('*')]}
    def prepare(self):
        with patch.object(m,'mqtt_snapshot',self.snapshot),patch.object(m,'urlopen',lambda *a,**k:io.BytesIO(CARD_BYTES)),patch.object(m,'CARD_HASH',m.sha(CARD_BYTES)):self.i.prepare()
    def test_fresh_flow_uses_existing_services_and_preserves_generated_defaults(self):
        self.prepare();self.assertEqual('choose_gateway',self.i.status()['phase'])
        self.assertTrue((self.config/'custom_components/eyzee_dashboard/zigbee_coordinator.py').exists())
        d=m.load((self.config/'zigbee2mqtt/configuration.yaml').read_text())
        self.assertEqual(5,d['version']);self.assertEqual(11,d['advanced']['channel']);self.assertEqual('do-not-display',d['mqtt']['password']);self.assertTrue(d['advanced']['enable_external_js']);self.assertFalse(d['onboarding'])
        # Discovery slots changed between display and selection: selection remains pinned to MAC.
        self.api.gateway_slots={2:('AA:BB:CC:DD:EE:01','192.168.1.40')}
        with patch.object(m,'mqtt_snapshot',self.snapshot):self.i.connect_gateway(1,'AA:BB:CC:DD:EE:01')
        self.assertTrue(self.i.status()['ready']);self.assertIn(('setup_zigbee_coordinator','SERVICE',{'slot':2}),self.api.calls)
        self.assertNotIn('do-not-display',json.dumps(self.i.status()))
    def test_repeated_prepare_preserves_customer_state_and_no_duplicate_helpers(self):
        self.prepare();room=self.config/'eyzee/state/rooms.yaml';room.write_text('version: 1\nrooms:\n  kitchen:\n    label: Kitchen\n');original=room.read_bytes()
        self.prepare();self.assertEqual(original,room.read_bytes())
        c=m.load((self.config/'configuration.yaml').read_text());self.assertEqual(2,len(c['homeassistant']['packages']));self.assertEqual(8123,c['http']['server_port'])
        self.assertEqual(1,len([c for c in self.api.calls if c[0]=='/backups/new/full']))
    def test_failed_validation_restores_configuration_without_restart(self):
        original=(self.config/'configuration.yaml').read_bytes();self.api.fail_check=True
        with self.assertRaises(m.SetupError):self.prepare()
        self.assertEqual(original,(self.config/'configuration.yaml').read_bytes());self.assertFalse(any(c[0]=='/core/restart' for c in self.api.calls))
    def test_changed_existing_integration_is_refused_before_backup_or_app_mutation(self):
        p=self.config/'custom_components/eyzee_dashboard/__init__.py';m.atomic(p,b'# existing code')
        with self.assertRaises(m.SetupError):self.prepare()
        self.assertEqual(b'# existing code',p.read_bytes());self.assertFalse(self.api.apps);self.assertFalse(any(c[0]=='/backups/new/full' for c in self.api.calls))
    def test_duplicate_configuration_keys_are_rejected(self):
        (self.config/'configuration.yaml').write_text('http:\n  server_port: 8123\nhttp:\n  server_port: 9000\n')
        with self.assertRaises(m.SetupError):self.i.config_plan()
    def test_unknown_file_is_not_overwritten_and_edited_owned_file_is_preserved(self):
        p=self.config/'eyzee/test.yaml';m.atomic(p,b'existing')
        with self.assertRaises(m.SetupError):self.i.write_owned('eyzee/test.yaml',b'new',replace=True)
        self.i.write_owned('eyzee/owned.yaml',b'initial');q=self.config/'eyzee/owned.yaml';q.write_bytes(b'customer edit')
        with self.assertRaises(m.SetupError):self.i.write_owned('eyzee/owned.yaml',b'updated',replace=True)
        self.assertEqual(b'customer edit',q.read_bytes())
    def test_path_escape_is_rejected(self):
        with self.assertRaises(m.SetupError):self.i.write_owned('../outside',b'unsafe')
    def test_stale_gateway_selection_cannot_call_setup(self):
        self.i.state['gateways']=[{'slot':1,'mac':'a'}]
        with self.assertRaises(m.SetupError):self.i.connect_gateway(1,'different')
        self.assertFalse(any(c[0]=='setup_zigbee_coordinator' for c in self.api.calls))
    def test_payload_checksum_validation(self):
        self.i.verify_payload()
        bad=self.root/'payload';bad.mkdir();m.atomic(bad/'wrong',b'tampered');(bad.parent/'payload-hashes.json').write_text(json.dumps({'wrong':'incorrect'}));self.i.payload=bad
        with self.assertRaises(m.SetupError):self.i.verify_payload()
    def test_existing_package_directory_is_preserved(self):
        (self.config/'configuration.yaml').write_text('default_config:\nhomeassistant:\n  packages: !include_dir_named packages\n')
        self.prepare();c=m.load((self.config/'configuration.yaml').read_text());self.assertEqual('packages',c['homeassistant']['packages'].value)
        self.assertTrue((self.config/'packages/eyzee_setup_core.yaml').exists());self.assertTrue((self.config/'packages/eyzee_smart_behaviours.yaml').exists())
    def test_failed_coordinator_status_is_not_marked_ready(self):
        self.prepare();self.api.service=lambda name,data=None:None;self.api.setup={'state':'failed','attributes':{'ready':False}}
        with self.assertRaises(m.SetupError):self.i.connect_gateway(1,'AA:BB:CC:DD:EE:01')
        self.assertFalse(self.i.status().get('ready',False))

    def test_missing_converter_blocks_ready(self):
        self.prepare()
        def snapshot(*args):
            result=self.snapshot();result['zigbee2mqtt/bridge/converters']=[];return result
        with patch.object(m,'mqtt_snapshot',snapshot),self.assertRaises(m.SetupError):self.i.connect_gateway(1,'AA:BB:CC:DD:EE:01')
        self.assertFalse(self.i.status().get('ready',False))

    def test_different_reported_serial_blocks_ready(self):
        self.prepare()
        def snapshot(*args):
            result=self.snapshot();result['zigbee2mqtt/bridge/info']['config']['serial']={'port':'tcp://wrong-gateway:6638'};return result
        with patch.object(m,'mqtt_snapshot',snapshot),self.assertRaises(m.SetupError):self.i.connect_gateway(1,'AA:BB:CC:DD:EE:01')
        self.assertFalse(self.i.status().get('ready',False))

    def test_restart_does_not_reuse_cached_ready(self):
        self.i.state.update(ready=True,phase='ready');self.i.save()
        restarted=m.Installer(self.config,self.data,HERE/'payload',self.api)
        self.assertFalse(restarted.status()['ready']);self.assertEqual('interrupted',restarted.status()['phase'])

    def test_admin_identity_check_rejects_normal_and_system_users(self):
        import sys,types
        users=[{'id':'owner','is_active':True,'is_owner':True}, {'id':'admin','is_active':True,'group_ids':['system-admin']}, {'id':'normal','is_active':True,'group_ids':['system-users']}, {'id':'system','is_active':True,'is_owner':True,'system_generated':True}]
        class WS:
            def __init__(self):self.responses=iter([{'type':'auth_required'},{'type':'auth_ok'},{'success':True,'result':users}])
            def recv(self):return json.dumps(next(self.responses))
            def send(self,data):pass
            def close(self):pass
        with patch.dict(sys.modules,{'websocket':types.SimpleNamespace(create_connection=lambda *a,**k:WS())}):
            api=m.API(token='private-test-token')
            for user,expected in [('owner',True),('admin',True),('normal',False),('system',False),('absent',False)]:self.assertEqual(expected,api.user_is_admin(user))

class ConnectionAPITests(unittest.TestCase):
    def test_websocket_authenticates_reads_matching_result_and_closes(self):
        import sys,types
        class WS:
            def __init__(self):
                self.messages=iter([{'type':'auth_required'},{'type':'auth_ok'},{'id':2,'success':True},{'id':1,'success':True,'result':[{'handler':'mqtt'}]}]);self.sent=[];self.closed=False
            def recv(self):return json.dumps(next(self.messages))
            def send(self,data):self.sent.append(json.loads(data))
            def close(self):self.closed=True
        ws=WS()
        with patch.dict(sys.modules,{'websocket':types.SimpleNamespace(create_connection=lambda *a,**k:ws)}):
            self.assertEqual([{'handler':'mqtt'}],m.API(token='secret').ws({'type':'config_entries/flow/progress'}))
        self.assertEqual({'type':'auth','access_token':'secret'},ws.sent[0])
        self.assertEqual({'type':'config_entries/flow/progress','id':1},ws.sent[1]);self.assertTrue(ws.closed)
    def test_http_failure_diagnostic_excludes_secrets_and_body(self):
        error=m.HTTPError('http://supervisor/core/api/config/config_entries/flow',405,'secret body',{},None)
        with patch.object(m,'urlopen',side_effect=error),self.assertRaises(m.RetryableError) as caught:
            m.API(token='private-token').ha('/config/config_entries/flow')
        self.assertEqual({'method':'GET','path':'/core/api/config/config_entries/flow','error_type':'HTTPError','http_status':405},caught.exception.diagnostic)
        self.assertNotIn('secret',json.dumps(caught.exception.diagnostic))

if __name__=='__main__':unittest.main()
