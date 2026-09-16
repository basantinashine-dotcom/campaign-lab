import test from 'node:test';
import assert from 'node:assert/strict';
import {simulate,makeVariant,validateConfig,DEFAULT_CONFIG,AUDIENCES,PLACEMENTS,CREATIVES,OFFERS} from '../dist/engine.mjs';
test('all supported choices reconcile spend, funnel, and margin',()=>{
 for(const budget of [50,149,150,151,300])for(const audience of Object.keys(AUDIENCES))for(const placement of Object.keys(PLACEMENTS))for(const creative of Object.keys(CREATIVES))for(const offer of Object.keys(OFFERS)){
  const r=simulate({...DEFAULT_CONFIG,budget,audience,placement,creative,offer});
  assert.equal(r.daily.length,7);assert.equal(Math.round(r.daily.reduce((s,d)=>s+d.spend,0)*100),budget*100);
  assert.ok(r.purchases<=r.clicks&&r.clicks<=r.impressions);assert.ok(r.purchases>=0);
  assert.equal(r.revenue,Math.round(r.purchases*r.model.orderPrice*100)/100);
  assert.equal(r.productCost,r.purchases*12);
  assert.equal(r.contribution,Math.round((r.revenue-r.productCost-r.spend)*100)/100);
  assert.equal(r.breakEvenOrders,Math.ceil(budget/(r.model.orderPrice-12)));
  for(const d of r.daily)assert.ok(d.purchases<=d.clicks&&d.clicks<=d.impressions);
 }
});
test('replaying same settings is deterministic and does not mutate inputs',()=>{
 const original=structuredClone(DEFAULT_CONFIG);const a=simulate(original);assert.deepEqual(a,simulate(original));assert.deepEqual(original,DEFAULT_CONFIG);
});
test('experiment changes exactly one decision and leaves original intact',()=>{
 const baseline=structuredClone(DEFAULT_CONFIG);const variant=makeVariant(baseline,'offer','save15');
 assert.deepEqual(Object.keys(baseline).filter(k=>baseline[k]!==variant[k]),['offer']);assert.deepEqual(baseline,DEFAULT_CONFIG);
 const a=simulate(baseline),b=simulate(variant);assert.equal(a.impressions,b.impressions);assert.equal(a.clicks,b.clicks);assert.equal(b.model.orderPrice,27.2);
});
test('reject invalid inputs and unchanged experiments before computation',()=>{
 for(const budget of [0,-1,49,301,Infinity,NaN,99.5,'300'])assert.throws(()=>validateConfig({...DEFAULT_CONFIG,budget}));
 for(const key of ['audience','placement','creative','offer'])assert.throws(()=>validateConfig({...DEFAULT_CONFIG,[key]:'__proto__'}));
 assert.throws(()=>validateConfig({...DEFAULT_CONFIG,name:' '}));assert.throws(()=>makeVariant(DEFAULT_CONFIG,'offer','none'));assert.throws(()=>makeVariant(DEFAULT_CONFIG,'name','something'));
});
