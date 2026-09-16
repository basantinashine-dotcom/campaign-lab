// All coefficients are fictional teaching assumptions, not Meta benchmarks.
export const SHOP=Object.freeze({name:'Ember & Earth',price:32,unitCost:12,days:7,maxBudget:300});
export const AUDIENCES={broad:{label:'Broad discovery',description:'Adults in the US; no interest suggestions.',cpm:1,ctr:1,cvr:1},decor:{label:'Home & interiors',description:'Adults in the US with home-decor interest suggestions.',cpm:1.18,ctr:1.25,cvr:1.2}};
export const PLACEMENTS={feed:{label:'Instagram Feed',description:'A square image in the feed.',cpm:12,ctr:.012},stories:{label:'Instagram Stories',description:'A full-screen vertical concept.',cpm:10.5,ctr:.009},reels:{label:'Instagram Reels',description:'A short-video concept, shown as a storyboard frame.',cpm:9,ctr:.0078}};
export const CREATIVES={mood:{label:'Lead with the feeling',description:'A beautiful product shot and a short, atmospheric message.',caption:'A quieter kind of evening. Discover your new everyday ritual with Ember & Earth.',ctr:1,cvr:1},benefits:{label:'Explain the product',description:'Keep the same image; explain scent, burn time, and price.',caption:'Cedar & citrus. 40 hours of slow-burning warmth. Small-batch candles, $32. Find your everyday ritual.',ctr:1.22,cvr:1.14}};
export const OFFERS={none:{label:'Full price · $32',description:'Keep the full $20 margin before advertising.',discount:0,cvr:1},save15:{label:'15% off · $27.20',description:'A stronger purchase incentive, but $15.20 margin before advertising.',discount:.15,cvr:1.28}};
export const DEFAULT_CONFIG=Object.freeze({name:'Ember & Earth · First campaign',budget:300,audience:'decor',placement:'feed',creative:'mood',offer:'none'});
export function validateConfig(c){
 if(!c||typeof c!=='object')throw new Error('Choose campaign settings first.');
 if(typeof c.name!=='string'||!c.name.trim()||c.name.length>70)throw new Error('Give your campaign a name of 1–70 characters.');
 if(!Number.isInteger(c.budget)||c.budget<50||c.budget>300)throw new Error('Choose a whole-dollar budget between $50 and $300.');
 for(const [key,opts] of Object.entries({audience:AUDIENCES,placement:PLACEMENTS,creative:CREATIVES,offer:OFFERS}))if(!Object.hasOwn(opts,c[key]))throw new Error(`Choose a valid ${key}.`);
 return {name:c.name.trim(),budget:c.budget,audience:c.audience,placement:c.placement,creative:c.creative,offer:c.offer};
}
export function assumptions(c){
 c=validateConfig(c);const a=AUDIENCES[c.audience],p=PLACEMENTS[c.placement],cr=CREATIVES[c.creative],o=OFFERS[c.offer];
 // Higher budgets cost slightly more per thousand impressions in this toy market.
 const saturation=1+Math.max(0,c.budget-150)/150*.12;
 return {baseCpm:p.cpm*a.cpm*saturation,clickProbability:p.ctr*a.ctr*cr.ctr,purchaseProbability:.04*a.cvr*cr.cvr*o.cvr,orderPrice:Math.round(SHOP.price*(1-o.discount)*100)/100,unitCost:SHOP.unitCost,saturation};
}
function rng(seed){let a=seed>>>0;return()=>{a+=0x6D2B79F5;let t=a;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296;};}
export function simulate(input){
 const config=validateConfig(input),model=assumptions(config);const daily=[];const cents=config.budget*100,base=Math.floor(cents/7),rest=cents%7;
 for(let d=0;d<7;d++){
  const dailyMarket=rng(29001+d),traffic=rng(53001+d),buyers=rng(91001+d);
  const spend=(base+(d<rest?1:0))/100,cpm=model.baseCpm*(.88+dailyMarket()*.24),impressions=Math.floor(spend/cpm*1000);
  let clicks=0,purchases=0;
  // Use a matched fictional market on every run. Consume both draws for each
  // impression, so a change in click probability does not reshuffle buyer draws.
  for(let i=0;i<impressions;i++){const click=traffic(),buy=buyers();if(click<model.clickProbability){clicks++;if(buy<model.purchaseProbability)purchases++;}}
  daily.push({day:d+1,spend,impressions,clicks,purchases,revenue:Math.round(purchases*model.orderPrice*100)/100});
 }
 const sum=k=>daily.reduce((n,d)=>n+d[k],0),impressions=sum('impressions'),clicks=sum('clicks'),purchases=sum('purchases'),revenue=Math.round(sum('revenue')*100)/100,productCost=purchases*SHOP.unitCost;
 const expectedClicks=impressions*model.clickProbability,expectedPurchases=expectedClicks*model.purchaseProbability;
 return {config,model,daily,spend:config.budget,impressions,clicks,purchases,revenue,productCost,expectedClicks,expectedPurchases,contribution:Math.round((revenue-productCost-config.budget)*100)/100,ctr:impressions?clicks/impressions:0,cvr:clicks?purchases/clicks:0,cpc:clicks?config.budget/clicks:null,cpa:purchases?config.budget/purchases:null,roas:revenue/config.budget,breakEvenOrders:Math.ceil(config.budget/(model.orderPrice-SHOP.unitCost))};
}
export function makeVariant(baseline,key,value){
 if(!['budget','audience','placement','creative','offer'].includes(key))throw new Error('Choose one campaign decision to change.');
 if(value===baseline[key])throw new Error('Choose a value different from your original campaign.');
 return validateConfig({...baseline,[key]:value});
}

// Explanations are derived from the same coefficients and outcomes, not generated
// independently. Distinguish a model mechanism from evidence about real campaigns.
export function explainChange(a,b,key){
 const round=n=>Math.round(n*100)/100;
 const dollars=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n);
 const percent=n=>(n*100).toFixed(2)+'%';
 const count=n=>new Intl.NumberFormat('en-US').format(n);
 const direction=(before,after)=>after>before?'higher':after<before?'lower':'unchanged';
 const catalog={audience:AUDIENCES,placement:PLACEMENTS,creative:CREATIVES,offer:OFFERS};
 const from=key==='budget'?dollars(a.spend):catalog[key][a.config[key]].label;
 const to=key==='budget'?dollars(b.spend):catalog[key][b.config[key]].label;
 const reasons={
  placement:`Switching from ${from} to ${to} changes the assumed cost of reaching people and their probability of clicking. Purchase probability after a click stays fixed; this model does not assume a placement alone makes your product more convincing.`,
  audience:`Switching from ${from} to ${to} changes assumed audience fit and impression cost. In this fictional market, the home-interiors audience costs more to reach but is more likely to click and buy. Real interest targeting does not guarantee this advantage.`,
  creative:`Switching from ${from} to ${to} changes the message. In this exercise, the product-focused message answers scent, burn time, and price questions, so we assign it a higher probability of clicks and purchases. Impression cost stays fixed. We are not analyzing an uploaded ad or measuring real creative quality.`,
  offer:`Switching from ${from} to ${to} changes the purchase incentive and the money earned per order. Our discount assumption increases purchase probability, but reduces the price by 15%. It does not change impressions or click probability.`,
  budget:`Changing the budget from ${from} to ${to} changes how many impressions you can buy. Above $150, this model also raises impression cost slightly to represent diminishing returns. The message and purchase probability stay fixed.`
 };
 const steps=[
  {label:'Cost of reaching people',before:dollars(a.model.baseCpm),after:dollars(b.model.baseCpm),detail:`Base cost per 1,000 impressions is ${direction(a.model.baseCpm,b.model.baseCpm)}. ${a.spend===b.spend?'With the same budget, higher cost buys fewer impressions; lower cost buys more.':'Both spending and impression cost determine how much exposure the campaign buys.'} Impressions: ${count(a.impressions)} → ${count(b.impressions)}.`},
  {label:'Chance of a click',before:percent(a.model.clickProbability),after:percent(b.model.clickProbability),detail:`This probability is ${direction(a.model.clickProbability,b.model.clickProbability)}. Combined with the impression count, expected clicks move from ${a.expectedClicks.toFixed(1)} to ${b.expectedClicks.toFixed(1)}. More likely clicks can offset some of the effect of fewer impressions.`},
  {label:'Chance of a purchase after clicking',before:percent(a.model.purchaseProbability),after:percent(b.model.purchaseProbability),detail:`This probability is ${direction(a.model.purchaseProbability,b.model.purchaseProbability)}. Expected clicks × purchase probability gives ${a.expectedPurchases.toFixed(2)} → ${b.expectedPurchases.toFixed(2)} expected orders. This is a model average, not a guaranteed order count.`}
 ];
 const realized=a.purchases===b.purchases?`Both seeded runs produced ${a.purchases} purchases. Their underlying expected outcomes can differ while the whole-number purchase totals tie. A tie does not mean the placement or other decision had no effect.`:`The seeded runs produced ${a.purchases} → ${b.purchases} purchases. That realized difference includes random variation as well as the changed probabilities; one run cannot establish a real-world winner.`;
 const volume=round((b.purchases-a.purchases)*(a.model.orderPrice-SHOP.unitCost));
 const price=round(b.purchases*(b.model.orderPrice-a.model.orderPrice));
 const spend=round(a.spend-b.spend);
 const takeaways={placement:'Compare the full funnel: cheaper impressions do not necessarily mean cheaper purchases. In a real test, adapt the creative to each placement and compare enough results before choosing.',audience:'Weigh the cost of reaching a more relevant audience against its purchase rate. A higher click rate alone is not enough to justify a more expensive audience.',creative:'A message should help the right person understand the offer. Test creative hypotheses with real evidence; a product-focused message is not automatically the winner outside this exercise.',offer:'Evaluate margin as well as order volume. A discount can increase sales while leaving less money after costs.',budget:'Evaluate contribution and acquisition cost alongside sales volume. Spending less may reduce losses without improving the ad; spending more does not guarantee efficiency.'};
 return {title:`Why ${to} changed the result`,reason:reasons[key],steps,realized,takeaway:takeaways[key],contribution:{volume,price,spend,total:round(b.contribution-a.contribution)}};
}
