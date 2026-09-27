// Real headless browser, loopback-only fixture. Never opens the user's profile.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto');
const adapter=process.env.IR_SYSTEM_TEST_ADAPTER_ROOT||path.resolve(__dirname,'../adapters/zsxq_web');
const {browserOptions,launchContext}=require(path.join(adapter,'browser'));
const {defaultChromePath}=require(path.join(adapter,'core'));
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'ir-headless-smoke-')),profileDir=path.join(root,'profile');
 const bytes=Buffer.from('%PDF-1.4\nIR System synthetic headless download\n%%EOF\n'),hash=b=>crypto.createHash('sha256').update(b).digest('hex');
 const server=http.createServer((req,res)=>{
  if(req.url==='/file.pdf'){res.writeHead(200,{'content-type':'application/pdf','content-disposition':'attachment; filename="fixture.pdf"','content-length':bytes.length});res.end(bytes);return;}
  if(req.url==='/seed')res.setHeader('set-cookie','fixture_session=localonly; Max-Age=3600; Path=/; HttpOnly');
  res.setHeader('content-type','text/html; charset=utf-8');res.end('<title>IR test</title><p id="session">'+(req.headers.cookie?.includes('fixture_session=localonly')?'retained':'missing')+'</p><a href="/file.pdf" download>Download fixture</a>'+Array.from({length:100},(_,i)=>`<article>record ${i}</article>`).join(''));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const url=`http://127.0.0.1:${server.address().port}`;let downloads=0,context;
 try{
  // Synthetic session created in the full-browser profile; no real credentials.
  context=await launchContext(browserOptions({profileDir,chromePath:defaultChromePath(),headless:true}));
  await context.pages()[0].goto(url+'/seed');await context.close();context=null;
  for(let batch=0;batch<3;batch++){
   const settings=browserOptions({profileDir,headless:true});assert.equal(settings.launch.headless,true);
   context=await launchContext(settings);const page=context.pages()[0]||await context.newPage();
   await context.route('**/*',route=>route.request().url().startsWith(url+'/')?route.continue():route.abort());
   for(let p=0;p<3;p++){
    await page.goto(url+'/page/'+p);assert.equal(await page.locator('article').count(),100);
    assert.equal(await page.locator('#session').innerText(),'retained');
    assert.equal(await page.evaluate(()=>Number(localStorage.getItem('fixtureBatch')||0)),batch);
   }
   for(let i=0;i<2;i++){
    const pending=page.waitForEvent('download');await page.getByText('Download fixture',{exact:true}).click();
    const download=await pending,file=path.join(root,`fixture-${batch}-${i}.pdf`);await download.saveAs(file);
    assert.equal(hash(fs.readFileSync(file)),hash(bytes));downloads++;
   }
   await page.evaluate(n=>localStorage.setItem('fixtureBatch',String(n)),batch+1);
   await context.close();context=null;
  }
  console.log(JSON.stringify({status:'passed',browser:'real headless Chromium',browserStarts:3,fixturePages:9,fixtureDownloads:downloads,profilePersistence:true,sourceCalls:0,modelCalls:0,root}));
 }finally{if(context)await context.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
