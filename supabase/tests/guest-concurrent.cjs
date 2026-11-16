/* Start a new local PostgreSQL cluster; never accepts a URL for an existing database. */
const path=require('node:path'),os=require('node:os'),fs=require('node:fs');
const {createRequire}=require('node:module'),assert=require('node:assert/strict');
const {randomUUID,randomBytes}=require('node:crypto'),{pathToFileURL}=require('node:url');
const load=process.env.WG_TEST_NODE_MODULES?createRequire(path.join(process.env.WG_TEST_NODE_MODULES,'../package.json')):require;
(async()=>{
 const Embedded=(await import(pathToFileURL(load.resolve('embedded-postgres')).href)).default;
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'wg-guest-pg-'));
 const port=Number(process.env.WG_TEST_PORT || 55439),password=randomBytes(32).toString('hex');
 const db=new Embedded({databaseDir:folder,port,user:'postgres',password,persistent:false,postgresFlags:['-h','127.0.0.1'],onLog:()=>{}});
 const clients=[];
 const windows=process.platform==='win32';
 const ctl=windows?path.resolve(path.dirname(load.resolve('@embedded-postgres/windows-x64')),'../native/bin/pg_ctl.exe'):null;
 const control=(...args)=>require('node:child_process').execFileSync(ctl,args,{windowsHide:true,stdio:'ignore',timeout:30000});
 let started=false;
 try{
 await db.initialise();
 if(windows) control('start','-D',folder,'-l',path.join(folder,'test-server.log'),'-o','-h 127.0.0.1 -p '+port,'-w','-t','20');
 else await db.start();
 started=true;
 for(let i=0;i<8;i++){
   const c=new (load('pg').Client)({host:'127.0.0.1',port,user:'postgres',password,database:'postgres'});await c.connect();clients.push(c);
 }
 const c=clients[0],g={token_hash:'1'.repeat(64),ip:'ip',digest:'message'};
 await c.query('create schema auth;create table auth.users(id uuid primary key);create role anon;create role authenticated;create role service_role;');
 const dir=process.argv[2]||path.join(__dirname,'../migrations');
 await c.query(fs.readFileSync(path.join(dir,'202611150001_guest_trial.sql'),'utf8').replace(/^\uFEFF/,''));
 const call=async(c,op,a)=>(await c.query('select public.waveguide_trial($1,$2) v',[op,a])).rows[0].v;
 await call(c,'create',g);
 const requests=clients.map(()=>({...g,rid:randomUUID(),attempt_limit:200,hour_limit:200}));
 for(let used=1;used<=5;used++){
   requests.forEach(x=>x.rid=randomUUID());
   const admissions=await Promise.all(clients.map((cl,i)=>call(cl,'admit',requests[i])));
   const idx=admissions.findIndex(x=>x.fence);
   assert.equal(admissions.filter(x=>x.fence).length,1);assert.equal(admissions.filter(x=>x.error==='REQUEST_IN_PROGRESS').length,7);
   const args={...requests[idx],...admissions[idx],message:'same',answer:'answer',charge:true};
   const finalized=await Promise.all(clients.map(cl=>call(cl,'finish',args)));
   assert.equal(finalized.filter(x=>x.guest?.messages_used===used).length,1);
   assert.equal((await call(c,'admit',requests[idx])).replay.answer,'answer');
 }
 const exhausted=await Promise.all(clients.map(cl=>call(cl,'admit',{...g,rid:randomUUID(),hour_limit:200,attempt_limit:200})));
 assert.ok(exhausted.every(x=>x.error==='GUEST_LIMIT_REACHED'));
 console.log('PASS: eight independent database connections, one execution per round, duplicate finalization fenced, fifth succeeds, sixth rejected.');
 }finally{await Promise.all(clients.map(c=>c.end()));if(started && windows){
   control('stop','-D',folder,'-m','fast','-w','-t','20');
   const owned=fs.realpathSync(folder);
   if(path.dirname(owned)!==fs.realpathSync(os.tmpdir()) || !path.basename(owned).startsWith('wg-guest-pg-'))throw Error('Unexpected temporary directory');
   fs.rmSync(owned,{recursive:true});
 } else await db.stop();}
})().catch(e=>{console.error(e.message);process.exitCode=1});

