// Run with Playwright installed: node tests/test_subscription_ui.cjs
// No live store, payments, service credentials or HAOS host is contacted.
const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'eyzee_setup/index.html'),'utf8').replace('__CSRF__','test-csrf');
const admin=fs.readFileSync(path.join(root,'subscription_service/admin.html'),'utf8');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:1000}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  let state={phase:'idle',message:'Ready to prepare your home.',installed:false,busy:false,ready:false,events:[],csrf_token:'test-csrf',subscription:{configured:true,activated:false}};
  let posts=[];
  await page.route('http://eyzee.test/**',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.pathname==='/api/status')return route.fulfill({json:state});
   if(request.method()==='POST'){
    posts.push({path:url.pathname,body:request.postDataJSON(),token:request.headers()['x-eyzee-token']});
    if(url.pathname==='/api/activate')state={...state,subscription:{configured:true,activated:true,plan:'core',active:true,expires_at:'2027-11-13T00:00:00Z'}};
    return route.fulfill({status:202,json:{accepted:true}});
   }
   return route.fulfill({contentType:'text/html',body:html});
  });
  await page.goto('http://eyzee.test/');
  await page.locator('#activation-form').waitFor({state:'visible'});
  assert.equal(await page.locator('#prepare').isVisible(),false);
  await page.locator('#activation-code').fill('EYZ-TEST-ACTIVATION-CODE');
  await page.locator('#activate').click();
  await page.locator('#activation-form').waitFor({state:'hidden'});
  assert.equal(posts[0].token,'test-csrf');
  assert.equal(posts[0].path,'/api/activate');
  assert.equal(await page.locator('#activation-code').inputValue(),'');
  assert.equal(await page.locator('#prepare').isVisible(),true);
  console.log('PASS activation gates preparation and does not retain the typed code');
  state={...state,phase:'installed',installed:true,installed_release:'1.0.0',available_release:'1.1.0'};
  await page.evaluate(()=>refresh());
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#apply-update').click();
  await page.waitForFunction(()=>!busy);
  assert.equal(posts.at(-1).path,'/api/updates/apply');
  assert.equal(posts.at(-1).body.confirm,true);
  console.log('PASS update requires explicit confirmation and retains CSRF protection');
  state={...state,available_release:'1.0.0',subscription:{...state.subscription,active:false}};
  await page.evaluate(()=>refresh());
  assert.equal(await page.locator('#open-core').isVisible(),true);
  assert.match(await page.locator('#subscription-status').textContent(),/expired/);
  assert.equal(await page.locator('#apply-update').isVisible(),false);
  assert.equal(await page.locator('#prepare').isVisible(),false);
  console.log('PASS expired access leaves Open EyZEE Core available');
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>refresh());
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  if(process.env.EYZEE_QA_DIR)await page.screenshot({path:path.join(process.env.EYZEE_QA_DIR,'setup-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  await page.unrouteAll();
  await page.route('http://eyzee.test/**',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.pathname==='/admin/overview'){
    if(request.headers()['authorization']!=='Bearer test-admin-key')return route.fulfill({status:401,json:{error:'Unauthorized'}});
    return route.fulfill({json:{customers:[{email:'tester@example.test',plan:'home',status:'active',expires_at:'2027-11-13T00:00:00Z',entitlement_id:'test-id'}],review:[],pending_emails:0}});
   }
   return route.fulfill({contentType:'text/html',body:admin});
  });
  await page.setViewportSize({width:1280,height:1000});
  await page.goto('http://eyzee.test/admin');
  await page.locator('#key').fill('test-admin-key');
  await page.locator('#login button').click();
  await page.locator('#management').waitFor({state:'visible'});
  assert.match(await page.locator('#customers').textContent(),/tester@example.test/);
  assert.equal(await page.locator('#key').inputValue(),'');
  assert.equal(await page.evaluate(()=>localStorage.length),0);
  if(process.env.EYZEE_QA_DIR)await page.screenshot({path:path.join(process.env.EYZEE_QA_DIR,'admin-desktop.png'),fullPage:true});
  await page.locator('#signout').click();
  assert.equal(await page.locator('#management').isVisible(),false);
  console.log('PASS administrator key remains in memory and customer list clears on sign-out');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
