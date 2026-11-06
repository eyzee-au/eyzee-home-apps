// npm install jsdom; node test_reconnect_ui.cjs
// Exercises the real page scripts and DOM with simulated HA responses.
const {JSDOM, VirtualConsole} = require('jsdom');
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const main = fs.readFileSync(path.join(__dirname,'index.html'),'utf8').replace('__CSRF__','initial-token');
const recovery = fs.readFileSync(path.join(__dirname,'reconnect.html'),'utf8');
const url = 'http://homeassistant.local:8123/api/hassio_ingress/test-session/';
const state = () => ({phase:'choose_gateway',message:'Choose your gateway.',installed:false,busy:false,ready:false,
  can_check_connection:true,csrf_token:'current-token',gateways:[{name:'MG24',mac:'AA:BB:CC:DD:EE:FF',address:'192.0.2.10',slot:1}],events:[]});
const json = (data,status=200) => new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
const tick = () => new Promise(resolve=>setImmediate(resolve));
function page(html,fetcher) {
  const errors=[],timers=[];
  const virtualConsole=new VirtualConsole();
  virtualConsole.on('jsdomError',error=>errors.push(error.message));
  const dom=new JSDOM(html,{url,runScripts:'dangerously',virtualConsole,beforeParse(window){
    window.fetch=fetcher;
    window.AbortController=global.AbortController;
    window.setInterval=()=>0;
    window.setTimeout=(fn,ms)=>{timers.push({fn,ms});return timers.length;};
    window.clearTimeout=()=>{};
  }});
  return {dom,w:dom.window,q:selector=>dom.window.document.querySelector(selector),errors,timers};
}
(async()=>{
  let current=state(),mode='json',postStatus=202,posted=[],statusCalls=0,slowRelease;
  const p=page(main,async (request,options={})=>{
    if(request==='api/status'){
      statusCalls++;
      if(mode==='slow')await new Promise(resolve=>{slowRelease=resolve;});
      if(mode==='error')return json({error:'Temporary identity failure'},503);
      if(mode==='html')return new Response('<html>Home Assistant sign in</html>',{headers:{'Content-Type':'text/html'}});
      return json(current);
    }
    posted.push({request,body:JSON.parse(options.body),token:options.headers['X-EyZEE-Token']});
    return json(postStatus===202?{accepted:true}:{error:'Reopen EyZEE Setup and try again.'},postStatus);
  });
  try {
    await tick();
    assert.equal(p.q('#use-core-address').checked,true);
    assert.ok(p.q('#gateways button'));
    console.log('PASS fresh setup retains checked hostname choice');
    current={...state(),phase:'ready',installed:true,ready:true,home_hostname:'eyzee-core'};
    await p.w.refresh();
    assert.equal(p.q('#open-core').href,'http://eyzee-core.local:8123/eyzee-main-menu/home');
    assert.equal(p.q('#completion-address').textContent,'Opens '+p.q('#open-core').href);
    current={...current,home_hostname:null,use_core_address:false};
    await p.w.refresh();
    assert.equal(p.q('#open-core').href,'http://homeassistant.local:8123/eyzee-main-menu/home');
    assert.equal(p.q('#completion-address').textContent,'Opens '+p.q('#open-core').href);
    console.log('PASS completion button and address agree for both hostname choices');

    current=state();await p.w.refresh();mode='error';await p.w.refresh();
    assert.equal(p.q('#reconnecting').hidden,false);
    assert.equal(p.q('#gateways button').disabled,true);
    assert.equal(p.q('#prepare').hidden,true);
    assert.match(p.q('#message').textContent,/getting things ready/);
    const before=posted.length;await p.w.action('gateway',{slot:1});assert.equal(posted.length,before);
    console.log('PASS outage shows friendly screen and blocks setup actions');

    mode='json';await p.w.refresh();
    assert.equal(p.q('#reconnecting').hidden,true);
    assert.equal(p.q('#gateways button').disabled,false);
    console.log('PASS same-stage recovery restores gateway controls');

    mode='html';await p.w.refresh();assert.equal(p.q('#reconnecting').hidden,false);
    mode='json';await p.w.refresh();
    console.log('PASS HTML sign-in response triggers reconnection without a JSON error');

    postStatus=403;await p.w.action('gateway',{slot:1});
    assert.equal(p.q('#reconnecting').hidden,false);
    assert.equal(posted.at(-1).token,'current-token');
    current.csrf_token='renewed-token';postStatus=202;await p.w.refresh();
    const count=posted.length;await p.w.action('check');
    assert.equal(posted.length,count+1);assert.equal(posted.at(-1).token,'renewed-token');
    console.log('PASS denied action is not replayed; next user action uses renewed CSRF token');

    mode='slow';const beforeSlow=statusCalls;
    const pending=Promise.all([p.w.refresh(),p.w.refresh(),p.w.refresh()]);
    await tick();assert.equal(statusCalls,beforeSlow+1);
    mode='json';slowRelease();await pending;
    console.log('PASS slow status fetch cannot create overlapping polls');
    assert.deepEqual(p.errors,[]);
  } finally {p.dom.window.close();}

  const optedOut=page(main,async()=>json({...state(),use_core_address:false}));
  try {
    await tick();assert.equal(optedOut.q('#use-core-address').checked,false);
    optedOut.w.showReconnect();assert.equal(optedOut.q('#reconnect-new-address').hidden,true);
    assert.deepEqual(optedOut.errors,[]);
    console.log('PASS saved hostname opt-out stays unticked and hides new-address recovery link');
  } finally {optedOut.dom.window.close();}

  let recovered=false;
  const shell=page(recovery,async()=>recovered?json(state()):json({error:'restarting'},503));
  try {
    assert.equal(shell.q('#retry').textContent,'Try Again');
    assert.equal(shell.q('#new-address').href,'http://eyzee-core.local:8123/');
    assert.equal(shell.q('#prepare'),null);
    await shell.w.reconnect();
    assert.equal(shell.errors.length,0);
    assert.ok(shell.timers.some(t=>t.ms===5000));
    recovered=true;await shell.w.reconnect();
    // jsdom reports attempted reload as unimplemented navigation; this proves
    // the shell requests a fresh authenticated page only after valid status.
    assert.equal(shell.errors.length,1);
    assert.match(shell.errors[0],/navigation/);
    console.log('PASS recovery shell retries denial and reloads only after authenticated status returns');
  } finally {shell.dom.window.close();}
})().catch(error=>{console.error(error);process.exit(1);});
