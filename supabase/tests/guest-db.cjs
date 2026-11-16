/* Offline executable PostgreSQL regression tests. Set PGLITE_MODULE to a local @electric-sql/pglite installation. */
const { PGlite } = require(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
(async () => {
 const db = new PGlite();
 try {
 await db.exec('create schema auth; create table auth.users(id uuid primary key); create role anon; create role authenticated; create role service_role;');
 const base=process.argv[2] || path.join(__dirname,'../migrations/202611150001_guest_trial.sql');
 await db.exec(fs.readFileSync(base,'utf8').replace(/^\uFEFF/,''));
 const call=async(op,a)=>(await db.query('select public.waveguide_trial($1,$2::jsonb) v',[op,JSON.stringify(a)])).rows[0].v;
 const g={token_hash:'a'.repeat(64),ip:'test1'}, b={token_hash:'b'.repeat(64),ip:'test1'};
 assert.equal((await call('create',g)).messages_remaining,5);
 assert.equal((await call('status',b)).error,'INVALID_GUEST_SESSION');
 await call('create',b);
 assert.equal((await call('create',{...g,token_hash:'c'.repeat(64),create_limit:2})).error,'TOO_MANY_GUEST_SESSIONS');
 const req=(extra={})=>({...g,rid:randomUUID(),digest:'hash',attempt_limit:100,hour_limit:100,...extra});
 const first=req(), admitted=await call('admit',first);
 assert.ok(admitted.fence);
 assert.equal((await call('admit',first)).error,'REQUEST_IN_PROGRESS');
 assert.equal((await call('admit',{...first,digest:'changed'})).error,'IDEMPOTENCY_CONFLICT');
 await call('release',admitted);
 assert.equal((await call('status',g)).messages_used,0);
 const retry=await call('admit',first);
 assert.notEqual(retry.fence,admitted.fence);
 assert.equal((await call('finish',{...first,...admitted})).error,'LEASE_LOST');
 await db.query('update wg_trial.leases set expires_at=now()-interval \'1 minute\'');
 assert.equal((await call('renew',retry)).renewed,false);
 let session;
 for(let i=1;i<=5;i++){
   const request=i===1?first:req({session_id:session});
   const lease=await call('admit',request);
   const response=await call('finish',{...request,...lease,message:'question',answer:'response',charge:true,context:{structured:{type:'example'}}});
   assert.equal(response.guest.messages_used,i);
   assert.equal(response.guest.signup_required,i===5);
   assert.equal((await call('admit',request)).replay.answer,'response');
   session=response.session_id;
 }
 assert.equal((await call('admit',req())).error,'GUEST_LIMIT_REACHED');
 assert.equal((await call('messages',{...g,session_id:session})).messages.length,10);
 assert.equal((await call('messages',{...b,session_id:session})).error,'NOT_FOUND');
 assert.equal((await call('admit',req({...b,session_id:session}))).error,'NOT_FOUND');
 assert.equal((await call('admit',req({...b,success_limit:5}))).error,'IP_RATE_LIMITED');
 assert.equal((await call('admit',req({...b,minute_budget:1}))).error,'GLOBAL_AI_BUDGET_EXCEEDED');
 assert.equal((await call('admit',req({...b,hour_limit:1}))).error,'IP_RATE_LIMITED');
 assert.equal((await call('admit',req({...b,attempt_limit:1}))).error,'GUEST_RATE_LIMITED');
 const results=await Promise.all([call('admit',req(b)),call('admit',req(b))]);
 assert.equal(results.filter(x=>x.fence).length,1);
 assert.equal((await call('account_admit',{concurrent:1})).error,'GLOBAL_AI_BUDGET_EXCEEDED');
 for(const role of ['anon','authenticated']) {
   assert.equal((await db.query("select has_function_privilege($1,'public.waveguide_trial(text,jsonb)','execute') p",[role])).rows[0].p,false);
   assert.equal((await db.query("select has_schema_privilege($1,'wg_trial','usage') p",[role])).rows[0].p,false);
 }
 console.log('PASS: real SQL admission, leases, quota, replay, ownership, rate windows and grants.');
 } finally {await db.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
