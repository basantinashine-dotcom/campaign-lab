import test from 'node:test';
import assert from 'node:assert/strict';
import {simulate,makeVariant,explainChange,DEFAULT_CONFIG} from '../dist/engine.mjs';
test('every decision gets an explanation with a reconciled money breakdown',()=>{
 const a=simulate(DEFAULT_CONFIG);
 for(const [key,val] of Object.entries({placement:'stories',audience:'broad',creative:'benefits',offer:'save15',budget:150})){
  const b=simulate(makeVariant(a.config,key,val)),e=explainChange(a,b,key);
  assert.ok(e.reason.length>40);assert.equal(e.steps.length,3);assert.ok(e.takeaway);
  assert.equal(Math.round((e.contribution.volume+e.contribution.price+e.contribution.spend)*100),Math.round((b.contribution-a.contribution)*100));
  assert.equal(e.contribution.total,Math.round((b.contribution-a.contribution)*100)/100);
 }
});
test('the reported Reels versus Stories tie exposes changing upstream metrics',()=>{
 const a=simulate({...DEFAULT_CONFIG,budget:150,placement:'reels',offer:'save15'}),b=simulate({...a.config,placement:'stories'});
 assert.equal(a.purchases,9);assert.equal(b.purchases,9);assert.equal(a.clicks,148);assert.equal(b.clicks,137);
 assert.notEqual(a.impressions,b.impressions);assert.notEqual(a.expectedPurchases,b.expectedPurchases);
 const e=explainChange(a,b,'placement');assert.match(e.realized,/Both seeded runs produced 9 purchases/);
 assert.equal(a.model.purchaseProbability,b.model.purchaseProbability);
 assert.ok(b.model.baseCpm>a.model.baseCpm);assert.ok(b.model.clickProbability>a.model.clickProbability);
});
