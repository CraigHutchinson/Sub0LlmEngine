// No browser or GPU needed: test evidence boundaries with independent examples.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname,'../web/tune.html'),'utf8');
const script = html.match(/<script id="selection-core">([\s\S]*?)<\/script>/)[1];
const E = vm.runInNewContext(script+'; TuningEvidence');
const plain = x => JSON.parse(JSON.stringify(x));
const row = (changes={}) => ({machine:'host',backend:'llamacpp',model:'model',build:'build',ts:'2026-11-16T12:00:00',
  params:{nCpuMoe:32,ctx:65536,ubatch:512,batch:2048,threads:16,cacheTypeK:'q8_0',cacheTypeV:'q8_0',flashAttn:'on',kvUnified:true,mmap:false,gpuLayers:99},
  depth:2048,ntg:128,B:4,outcome:'ok',tgTps:100,...changes});
const pool = (rows, min=1) => E.points(rows,E.cohortKey(row()),128,min);
const rank = (rows, weights=[1,1,1], limits={depth:0,concurrency:1,speed:0})=>E.rank(pool(rows).accepted,weights,limits);

test('cohorts do not mix machines, models, backends, builds or output lengths',()=>{
  const variants = ['machine','model','backend','build'].map(k=>row({[k]:'other',tgTps:999}));
  const points=pool([row(),...variants,row({ntg:256,tgTps:999}),row({excluded:'contended',tgTps:999})]).accepted;
  assert.equal(points.length,1); assert.equal(points[0].speed,25); assert.equal(points[0].rows.length,1);
});
test('median of repeated exact points, never their best run',()=>{
  const p=pool([row({tgTps:80}),row({tgTps:120})]).accepted[0];
  assert.equal(p.speed,25); assert.equal(p.total,100); assert.equal(p.low,20); assert.equal(p.high,30);
});
test('all parameter axes, depth, and concurrency distinguish points',()=>{
  const a=row(), b=row({params:{...a.params,flashAttn:'off'}}), c=row({depth:4096}), d=row({B:8});
  assert.equal(pool([a,b,c,d]).accepted.length,4);
});
test('failure at exact point withholds it; exclusion of contaminated failure restores it',()=>{
  for(const outcome of ['oom','error','missing']) {
    const p=pool([row(),row({outcome})]); assert.equal(p.accepted.length,0); assert.equal(p.conflicts,1);
  }
  assert.equal(pool([row(),row({outcome:'oom',excluded:'known contention'})]).accepted.length,1);
});
test('incomplete, malformed, impossible, nonfinite and nonpositive rows never qualify',()=>{
  const rows=[row({params:{ctx:65536}}),row({depth:65536}),row({B:1.5}),row({tgTps:NaN}),row({tgTps:0}),row({tgTps:-2}),row({depth:0})];
  assert.equal(pool(rows).accepted.length,0);
  assert.equal(pool([row(),row({tgTps:NaN})]).accepted.length,0);
});
test('a larger allocation is not evidence for deeper prompt requirements',()=>{
  const rows=[row({params:{...row().params,ctx:262144}})];
  assert.equal(rank(rows,[1,1,1],{depth:8192,concurrency:1,speed:0}).length,0);
});
test('minima are simultaneous constraints, not independent maxima',()=>{
  const rows=[row({B:1,depth:8192,tgTps:60}),row({B:8,depth:2048,tgTps:120})];
  assert.equal(rank(rows,[1,1,1],{depth:8192,concurrency:8,speed:0}).length,0);
});
test('axis preferences choose observed points and remove dominated points from frontier',()=>{
  const rows=[row({B:1,depth:512,tgTps:60}),row({B:2,depth:8192,tgTps:80}),row({B:8,depth:2048,tgTps:120}),row({B:1,depth:512,tgTps:20,params:{...row().params,threads:8}})];
  assert.equal(rank(rows,[1,0,0])[0].speed,60);
  assert.equal(rank(rows,[0,1,0])[0].depth,8192);
  assert.equal(rank(rows,[0,0,1])[0].concurrency,8);
  assert.equal(rank(rows).filter(p=>p.frontier).length,3);
});
test('strict evidence policy, zero weights, single point and empty cohort stay finite',()=>{
  assert.equal(pool([row()],2).accepted.length,0);
  assert.equal(pool([row(),row()],2).accepted.length,1);
  assert.equal(rank([row()],[0,0,0])[0].score,1);
  assert.equal(rank([]).length,0);
});
test('profile preserves exact knobs, measured workload, identity and activation boundary',()=>{
  const p=rank([row()])[0], profile=plain(E.profile(p,[1,0,0]));
  assert.deepEqual(profile.identity,{machine:'host',backend:'llamacpp',model:'model',build:'build'});
  assert.deepEqual(profile.consumerBudget,{maxConcurrentRequests:4,maxPromptTokens:2048,maxOutputTokens:128,maxTotalTokens:2176});
  for(const [k,v] of Object.entries(row().params)) assert.equal(profile.engineConfig[k],v);
  assert.equal(profile.activation.automatic,false); assert.equal(profile.activation.requiresServerValidation,true);
});

test('failures heal after two later passes or a superseded mark; one later pass is not enough',()=>{
  const t=n=>`2026-11-16T12:0${n}:00`;
  let p=pool([row({outcome:'oom',ts:t(1)}),row({ts:t(2)})]); assert.equal(p.accepted.length,0); assert.equal(p.mixed,1);
  p=pool([row({outcome:'oom',ts:t(1)}),row({ts:t(2)}),row({ts:t(3)})]); assert.equal(p.accepted.length,1); assert.equal(p.healed,1);
  p=pool([row({ts:t(1)}),row({ts:t(2)}),row({outcome:'oom',ts:t(3)})]); assert.equal(p.accepted.length,0);
  p=pool([row({outcome:'oom',ts:t(1),superseded:true}),row({ts:t(2)})]); assert.equal(p.accepted.length,1);
  p=pool([row({outcome:'oom',ts:t(1)}),row({outcome:'oom',ts:t(2)})]); assert.equal(p.failed,1); assert.equal(p.mixed,0);
});
test('best per concurrency removes near-duplicates and coverage names single-depth concurrencies',()=>{
  const a=row({B:1,tgTps:60}), b=row({B:1,tgTps:59,params:{...row().params,nCpuMoe:33}}), c=row({B:4,tgTps:100}), d=row({B:4,depth:8192,tgTps:90});
  const ranked=rank([a,b,c,d]);
  assert.deepEqual(plain(E.bestPer(ranked,'concurrency').map(p=>p.concurrency)).sort(),[1,4]);
  assert.equal(E.bestPer(ranked,'workload').length,3);
  assert.equal(E.bestPer(ranked,'all').length,4);
  const cov=E.coverage(pool([a,c,d]).accepted);
  assert.deepEqual(plain(cov.thin),[{concurrency:1,depth:2048}]);
  assert.deepEqual(plain(cov.missing),[{concurrency:1,depths:[8192]}]);
});
test('misses names each unmet requirement and agrees with rank',()=>{
  const shallow=row({depth:2048}), deep=row({depth:32768,B:1,params:{...row().params,ctx:65536}}), crowded=row({B:8,depth:4096,params:{...row().params,ctx:65536}});
  const limits={depth:0,concurrency:1,speed:0,minSlotContext:16384};
  const pts=pool([shallow,deep,crowded]).accepted, ranked=E.rank(pts,[1,1,1],limits);
  for (const p of pts) assert.equal(E.misses(p,limits).length===0, ranked.some(q=>q.key===p.key));
  assert.deepEqual(plain(E.misses(pts.find(p=>p.concurrency===8),limits)),['allocation per slot below the slot minimum','measured at a shallower prompt than the slot minimum']);
});
test('auto slot minimum keeps every measured concurrency; filters are extensible',()=>{
  const deep=row({B:1,depth:32768,params:{...row().params,ctx:65536}}), shallow8=row({B:8,depth:2048,params:{...row().params,ctx:65536}});
  const pts=pool([deep,shallow8]).accepted, limits={depth:0,concurrency:1,speed:0};
  assert.equal(E.autoSlot(pts,limits),2048);  // B=8 was measured at 2048+128 tokens with 8192 per slot
  assert.equal(E.rank(pts,[1,1,1],{...limits,minSlotContext:E.autoSlot(pts,limits)}).length,2);
  assert.equal(E.rank(pts,[1,1,1],{...limits,minSlotContext:16384}).length,1);
  assert.equal(E.autoSlot([],limits),0);
  const n=E.FILTERS.length;
  E.addFilter({id:'maxVram',label:'VRAM ceiling',miss:(p,c)=>c.maxVram && (p.record.peakVramMiB||0)>c.maxVram ? ['VRAM above the ceiling'] : []});
  const v=pool([row({peakVramMiB:7000}),row({B:8,peakVramMiB:5000})]).accepted;
  assert.equal(E.rank(v,[1,1,1],{...limits,maxVram:6000}).length,1);
  assert.deepEqual(plain(E.misses(v.find(p=>p.concurrency===4),{...limits,maxVram:6000})),['VRAM above the ceiling']);
  E.FILTERS.splice(n);  // leave the registry as other tests expect it
  assert.throws(()=>E.addFilter({id:'x'}));
});
test('moving weight from speed to concurrency steps through every frontier concurrency, not only the ends',()=>{
  // per-sequence decode falls like 1/B while total saturates: a curved frontier a weighted sum only meets at B=1 and B=16
  const totals={1:58,2:80,3:92,4:100,6:106,8:110,12:113,16:115};
  const rows=Object.entries(totals).map(([b,t])=>row({B:+b,tgTps:t,params:{...row().params,ctx:262144}}));
  const seen=new Set();
  for (let a=0;a<=100;a+=2) seen.add(rank(rows,[100-a,0,a])[0].concurrency);
  assert.deepEqual(plain([...seen]).sort((x,y)=>x-y),[1,2,3,4,6,8,12,16]);
});
test('speed metric: prefill and whole-request rate rank, and the prefill floor filters',()=>{
  const fast=row({B:1,tgTps:60,ppTps:800}), wide=row({B:8,tgTps:110,ppTps:1300});
  const pts=pool([fast,wide]).accepted, w=[1,0,0], l={depth:0,concurrency:1,speed:0};
  assert.equal(E.rank(pts,w,{...l,speedMetric:'prefill'})[0].concurrency,8);
  assert.equal(E.rank(pts,w,{...l,speedMetric:'decode'})[0].concurrency,1);
  const r=E.rank(pts,w,{...l,speedMetric:'requestRate'});
  assert.equal(r[0].concurrency,1);  // one request alone: 2048/800 + 128/60 s, against 8 sharing the GPU
  assert.ok(Math.abs(pts.find(p=>p.concurrency===1).requestSeconds-(2048/800+128/60))<1e-9);
  assert.equal(E.rank(pts,w,{...l,prefill:1000}).length,1);
});
test('prefill is a fourth axis: weighting it picks the faster prefill; three weights mean prefill 0',()=>{
  const lean=row({B:4,tgTps:104,ppTps:900}), wide=row({B:4,tgTps:100,ppTps:1500,params:{...row().params,ubatch:2048}});
  const pts=pool([lean,wide]).accepted, l={depth:0,concurrency:1,speed:0};
  assert.equal(E.rank(pts,[1,0,0,0],l)[0].record.params.ubatch,512);
  assert.equal(E.rank(pts,[0,0,0,1],l)[0].record.params.ubatch,2048);
  assert.equal(E.rank(pts,[1,0,0],l)[0].record.params.ubatch,512);
  assert.equal(E.rank(pts,[1,0,0],l).filter(p=>p.frontier).length,2);  // each wins one axis: both on the 4-axis frontier
  assert.equal(E.best(E.prepare(pts,l),[0,0,0,1]).record.params.ubatch,2048);
});
test('all inline scripts parse',()=>{
  for(const m of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(m[1]);
});
