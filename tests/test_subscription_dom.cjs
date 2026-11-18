// Exercises the real customer/admin scripts without a browser or live account.
// npm install jsdom; node tests/test_subscription_dom.cjs
const {JSDOM,VirtualConsole}=require('jsdom');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
function page(file,fetcher){const errors=[];const console=new VirtualConsole();console.on('jsdomError',e=>errors.push(e.message));const dom=new JSDOM(fs.readFileSync(file,'utf8').replace('__CSRF__','test-csrf'),{url:'https://eyzee.test/',runScripts:'dangerously',virtualConsole:console,beforeParse(window){window.fetch=fetcher;window.AbortController=global.AbortController;window.setInterval=()=>0;window.confirm=()=>true;}});return{dom,w:dom.window,q:s=>dom.window.document.querySelector(s),errors};}
(async()=>{
 let state={phase:'idle',message:'Ready.',installed:false,busy:false,events:[],csrf_token:'test-csrf',subscription:{configured:true,activated:false}},posts=[];
 const p=page(path.join(root,'eyzee_setup/index.html'),async(url,options={})=>{
  if(url==='api/status')return json(state);
  posts.push({url,body:JSON.parse(options.body),token:options.headers['X-EyZEE-Token']});
  if(url==='api/activate')state={...state,subscription:{configured:true,activated:true,plan:'core',active:true,expires_at:'2027-11-13T00:00:00Z'}};
  return json({accepted:true},202);
 });
 try{
  await tick();assert.equal(p.q('#activation-form').hidden,false);assert.equal(p.q('#message').closest('.card').hidden,true);
  p.q('#activation-code').value='EYZ-TEST-ACTIVATION-CODE';await p.q('#activation-form').onsubmit({preventDefault(){}});
  assert.equal(posts[0].token,'test-csrf');assert.equal(posts[0].url,'api/activate');assert.equal(p.q('#activation-code').value,'');assert.equal(p.q('#activation-form').hidden,true);assert.equal(p.q('#message').closest('.card').hidden,false);
  console.log('PASS activation is first, uses CSRF and clears the code');
  state={...state,phase:'installed',installed:true,installed_release:'1.0.0',available_release:'1.1.0'};await p.w.refresh();
  let confirmed=false;p.w.confirm=()=>{confirmed=true;return false;};p.q('#apply-update').onclick();assert.equal(confirmed,true);assert.equal(posts.length,1);
  p.w.confirm=()=>true;p.q('#apply-update').onclick();await tick();assert.equal(posts.at(-1).url,'api/updates/apply');assert.equal(posts.at(-1).body.confirm,true);
  console.log('PASS update requires explicit restart confirmation');
  state={...state,available_release:'1.0.0',subscription:{...state.subscription,active:false}};await p.w.refresh();
  assert.equal(p.q('#ready').style.display,'block');assert.equal(p.q('#prepare').hidden,true);assert.equal(p.q('#apply-update').hidden,true);assert.match(p.q('#subscription-status').textContent,/expired/);
  assert.deepEqual(p.errors,[]);console.log('PASS expiry keeps Open EyZEE Core available');
 }finally{p.dom.window.close();}
 let authorised=false;
 const admin=page(path.join(root,'subscription_service/admin.html'),async(url,options)=>{
  authorised=options.headers.Authorization==='Bearer test-admin-key';return authorised?json({customers:[{email:'tester@example.test',plan:'home',status:'active',expires_at:'2027-11-13T00:00:00Z',entitlement_id:'test-id'}],review:[],pending_emails:0}):json({},401);
 });
 try{
  admin.q('#key').value='test-admin-key';admin.q('#login').onsubmit({preventDefault(){}});await tick();assert.equal(authorised,true);assert.equal(admin.q('#key').value,'');assert.equal(admin.q('#management').hidden,false);assert.match(admin.q('#customers').textContent,/tester@example.test/);assert.equal(admin.w.localStorage.length,0);
  admin.q('#signout').onclick();assert.equal(admin.q('#management').hidden,true);assert.equal(admin.q('#customers').textContent,'');assert.deepEqual(admin.errors,[]);console.log('PASS admin login, in-memory credential and sign-out clearing');
 }finally{admin.dom.window.close();}
})().catch(error=>{console.error(error);process.exit(1);});
