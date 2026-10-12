const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const growth=require('../deskrawl_assistant/web/managed-growth.js');
const managed=require('../deskrawl_assistant/web/managed-mode.js');
const data=require('../data/progression-catalog.json');

test('merchant defaults are 85 percent return and zero reserve while saved values survive',()=>{
  const defaults=managed.normalizeSettings();
  assert.equal(defaults.merchant.trigger_percent,85);assert.equal(defaults.merchant.spend_to_percent,0);
  const restored=managed.normalizeSettings({merchant:{trigger_percent:94,spend_to_percent:13}});
  assert.equal(restored.merchant.trigger_percent,94);assert.equal(restored.merchant.spend_to_percent,13);
});

test('icon selection retains numeric budgets and does not overwrite other class plans',()=>{
  const vm=require('node:vm'),elements=new Map(),rows={};
  const checks=new Set(['managed-merchant','managed-talents','managed-skills','managed-life']);
  const numbers=new Set(['managed-shard-trigger','managed-shard-reserve','managed-life-gold']);
  const node=id=>{
    if(!elements.has(id))elements.set(id,{id,type:checks.has(id)?'checkbox':numbers.has(id)?'number':'div',
      value:'',checked:false,dataset:{},style:{},listeners:{},contains:()=>false,classList:{toggle:()=>{}},
      querySelector:selector=>node(id+selector),querySelectorAll:selector=>{
        // The production CSP discards style attributes parsed from HTML.
        // Only property assignments to these elements affect their style.
        const attribute=selector.slice(1,-1),key=attribute.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
        return [...(node(id).innerHTML||'').matchAll(new RegExp(attribute+'="([^"]+)"','g'))].map(match=>{
          const child=node(id+selector+match[1]);child.dataset[key]=match[1];return child;
        });
      },
      addEventListener(type,fn){(this.listeners[type]||=[]).push(fn);}});
    return elements.get(id);
  };
  const document={getElementById:node,querySelectorAll:selector=>rows[selector]||[],activeElement:null};
  const window={document};vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../deskrawl_assistant/web/managed-growth.js'),'utf8'),{window});
  const ui=window.ManagedGrowthUI;ui.init();let saved=growth.normalize();
  let shopBuilds=0,shopHtml='';Object.defineProperty(node('managed-shop-weights'),'innerHTML',{
    get:()=>shopHtml,set:value=>{shopHtml=value;shopBuilds++;}});
  saved.progression.skill_stages['8']=[{level:20,slots:[null,null,null,null]}];
  saved.progression.skill_stages['4']=[{level:20,slots:['HunterBasicAttack2',null,null,null]}];
  const snapshot=mask=>({available:true,class_mask:mask,level:70,gold:100000,
    soul_shards:{current:1000,maximum:2000},talents:{ranks:{},unspent:10},
    life_skills:{ranks:{}},merchant:{unlock_known:true,unlocked:true},skills:{equipped:[null,null,null,null],available:data.heroes[String(mask)].abilities.map(s=>s.id)}});
  let current=snapshot(4);
  const changed=(value,renderNow)=>{saved=value;if(renderNow)ui.render(saved,data,current,false,changed,true);};
  // A bundled catalog and even stale available data must not imply connection.
  ui.render(saved,data,current,false,changed,false);
  assert.match(node('managed-talent-tree').innerHTML,/请先连接游戏/);
  assert.match(node('managed-skill-stages').innerHTML,/请先连接游戏/);
  assert.equal(node('managed-talents').disabled,true);assert.equal(node('managed-skills').disabled,true);
  assert.ok(!node('managed-talent-tree').innerHTML.includes('data-talent-node'));
  assert.ok(!node('managed-skill-stages').innerHTML.includes('data-skill-id'));
  ui.render(saved,data,{available:false},false,changed,true);
  assert.match(node('managed-talent-tree').innerHTML,/正在读取当前角色职业/);
  ui.render(saved,data,current,false,changed,true);
  // Routine polls, price changes and readonly mode retain images and focused
  // inputs; only a changed catalog may rebuild this menu.
  const helm=node('managed-shop-weights').querySelectorAll('[data-shop-slot]').find(n=>n.dataset.shopSlot==='2');
  const helmInput=helm.querySelector('[data-shop-weight]'),helmValue=helm.querySelector('.growth-shop-price').querySelector('.growth-shop-price-value');
  current.merchant={unlock_known:true,unlocked:true,preview:[{slot:2,price:21,price_reference:true}]};
  ui.render(saved,data,current,false,changed,true);assert.equal(helmValue.textContent,'21');
  document.activeElement=helmInput;helmInput.value='123';
  current.merchant.preview[0]={slot:2,price:25,price_reference:false};
  ui.render(saved,data,current,false,changed,true);assert.equal(helmValue.textContent,'25');assert.equal(helmInput.value,'123');
  ui.render(saved,data,current,true,changed,true);assert.equal(helmInput.disabled,true);assert.equal(shopBuilds,1);
  document.activeElement=null;ui.render(saved,data,current,false,changed,true);
  assert.equal(helmInput.disabled,false);assert.equal(helmInput.value,0);assert.equal(shopBuilds,1);
  current.merchant.unlocked=false;ui.render(saved,data,current,false,changed,true);
  assert.equal(node('managed-merchant').disabled,true);assert.match(node('managed-merchant-unlock').textContent,/未解锁/);
  saved.merchant.enabled=true;ui.render(saved,data,current,false,changed,true);
  assert.equal(node('managed-merchant').disabled,false); // Legacy enabled setting can be switched off.
  saved.merchant.enabled=false;current.merchant.unlocked=true;ui.render(saved,data,current,false,changed,true);
  assert.equal(node('managed-merchant').disabled,false);
  const talentNodes=node('managed-talent-tree').querySelectorAll('[data-talent-node]');
  assert.equal(talentNodes.length,40);
  assert.equal(node('managed-talent-tree.growth-tree-canvas').style.height,'899px');
  assert.equal(new Set(talentNodes.map(n=>n.style.left+','+n.style.top)).size,40);
  const lifeNodes=node('managed-life-nodes').querySelectorAll('[data-life-node]');
  assert.equal(lifeNodes.length,85);
  assert.equal(new Set(lifeNodes.map(n=>n.style.left+','+n.style.top)).size,85);
  assert.ok(parseFloat(node('managed-life-nodes.growth-life-canvas').style.width)>1000);
  assert.equal(node('managed-life-nodes.growth-life-canvas').style.transform,'scale(0.42)');
  // Only a new actual character snapshot can select another class.
  current=snapshot(8);ui.render(saved,data,current,false,changed,true);
  assert.equal(node('managed-growth-class').textContent,'武僧 · 当前职业');
  node('managed-life-gold').value='12345';rows['[data-shop-weight]']=[{value:'20',dataset:{shopWeight:'1'}}];
  const skill={dataset:{skillId:'MonkBasicAttack2'}};
  node('managed-skill-stages').listeners.click[0]({target:{closest:selector=>selector==='[data-skill-id]'?skill:null}});
  assert.equal(saved.progression.skill_stages['8'][0].level,1);
  assert.equal(saved.progression.skill_stages['8'][0].slots[0],'MonkBasicAttack2');
  assert.equal(saved.progression.skill_stages['4'][0].level,20);
  const read=ui.read();assert.equal(read.life_skills.gold_reserve,12345);assert.equal(read.merchant.weights['1'],20);
  // Input events update the draft without tearing down the focused control.
  let immediate;ui.render(saved,data,current,false,(value,renderNow)=>{saved=value;immediate=renderNow;},true);
  node('managed-life-gold').value='54321';node('managed-life-gold').listeners.input[0]({target:node('managed-life-gold')});
  assert.equal(saved.life_skills.gold_reserve,54321);assert.equal(immediate,false);
  const before=JSON.stringify(saved);
  ui.render(saved,data,current,false,changed,false);
  assert.equal(node('managed-growth-class').textContent,'连接后识别职业');
  assert.ok(!node('managed-talent-tree').innerHTML.includes('data-talent-node'));
  assert.ok(!node('managed-skill-stages').innerHTML.includes('data-skill-id'));
  node('managed-talent-clear').listeners.click[0]();node('growth-skills-clear').listeners.click[0]();
  assert.equal(JSON.stringify(saved),before);
});

test('career discovery requires a connected complete snapshot with one supported class',()=>{
  assert.equal(growth.activeHero(data,{available:true,class_mask:4},false),null);
  assert.equal(growth.activeHero(data,{available:false,class_mask:4},true),null);
  for(const class_mask of [0,3,16,'4',null])assert.equal(growth.activeHero(data,{available:true,class_mask},true),null);
  for(const class_mask of [1,2,4,8])assert.equal(growth.activeHero(data,{available:true,class_mask},true),String(class_mask));
});

test('talent progress interpolates between actual point gates and retreats when points are removed',()=>{
  const nodes=data.heroes['4'].talents;
  assert.equal(growth.talentProgress(nodes,0),0);
  assert.equal(growth.talentProgress(nodes,5),1/8);
  assert.equal(growth.talentProgress(nodes,10),2/8);
  assert.equal(growth.talentProgress(nodes,20),4/8);
  assert.equal(growth.talentProgress(nodes,25),4.5/8);
  assert.equal(growth.talentProgress(nodes,60),1);
  assert.equal(growth.talentProgress(nodes,70),1);
  assert.equal(growth.talentProgress(nodes,NaN),0);
  assert.ok(growth.talentProgress(nodes,19)<growth.talentProgress(nodes,20));
});

test('life tree highlights the entire real prerequisite path and removes dependent priorities',()=>{
  const priorities=['LifeSkill 66','LifeSkill 13'],path=growth.lifePath(data.life_skills,priorities);
  for(const id of ['LifeSkill','LifeSkill 2','LifeSkill 8','LifeSkill 31','LifeSkill 44','LifeSkill 66'])assert.ok(path.includes(id));
  assert.ok(path.includes('LifeSkill 13'));
  assert.deepEqual(growth.lifeRemove(data.life_skills,priorities,'LifeSkill 8'),['LifeSkill 13']);
  assert.deepEqual(growth.lifeRemove(data.life_skills,priorities,'LifeSkill'),[]);
});

test('skill icon targets use native unlock levels and never duplicate special slots',()=>{
  const stages=[{level:30,slots:['HunterBasicAttack2',null,'HunterSpecial1','HunterSpecial2']}];
  assert.deepEqual(growth.skillChoice(stages,2,'HunterSpecial2'),[{level:1,slots:['HunterBasicAttack2',null,'HunterSpecial2','HunterSpecial1']}]);
  assert.deepEqual(growth.skillChoice(stages,3,'HunterSpecial2'),[{level:1,slots:['HunterBasicAttack2',null,'HunterSpecial1',null]}]);
  assert.deepEqual(growth.skillTargets(stages),stages[0].slots);
  assert.equal(stages[0].level,30);
});

test('reducing early talents trims targets that no longer satisfy the spend gate',()=>{
  const nodes=[{id:'base',max_points:5,point_requirement:0},{id:'late',max_points:3,point_requirement:5}];
  assert.deepEqual(growth.talentChange(nodes,{base:5,late:3},'base',-1),{base:4});
  assert.equal(growth.talentAllowed(nodes[1],nodes,{base:4}),false);
});

test('shipped layout coordinates and localized effect values are used in previews',()=>{
  assert.equal(new Set(data.life_skills.map(n=>n.id)).size,85);
  for(const n of data.life_skills){assert.ok(Number.isFinite(n.x)&&Number.isFinite(n.y));assert.ok(!growth.description(n).includes('{'));}
  assert.equal(growth.description(data.heroes['4'].talents.find(n=>n.id==='HunterTalent0'),3),'+15 敏捷');
  const n=data.life_skills.find(n=>n.id==='LifeSkill 1');assert.match(growth.description(n),/10%/);
  for(const path of Object.values(data.ui_assets))assert.ok(fs.existsSync(require('node:path').join(__dirname,'../deskrawl_assistant/web',path)));
});

test('saved growth plans migrate independently without enabling new spending',()=>{
  const old=managed.normalizeSettings({cleanup:{equipment_pages:[6],rune_pages:[2],gem_pages:[8]}});
  assert.equal(growth.enabled(old),false);
  assert.deepEqual(old.life_skills,{enabled:false,priorities:[],gold_reserve:0});
  assert.deepEqual(old.cleanup.equipment_pages,[6]);
  const input={life_skills:{enabled:true,priorities:['LifeSkill 66'],gold_reserve:5000},
    progression:{talent_targets:{'4':{HunterTalent0:6}},skill_stages:{'8':[{level:20,slots:[null,null,'MonkSpecial1',null]}]}},
    merchant:{weights:{1:20,2:0},trigger_percent:80}};
  const saved=managed.normalizeSettings(input);input.life_skills.priorities.push('LifeSkill 8');
  assert.deepEqual(saved.life_skills.priorities,['LifeSkill 66']);
  assert.equal(saved.merchant.weights['2'],0);
  assert.equal(saved.merchant.weights['1'],20);
  assert.equal(saved.progression.talent_targets['4'].HunterTalent0,6);
});

test('each growth feature can run alone through its own test capability',()=>{
  for(const [group,key,cap] of [['life_skills','enabled','life_skills'],['merchant','enabled','merchant'],
                             ['progression','talents_enabled','talents'],['progression','skills_enabled','skills']]){
    const cfg=managed.normalizeSettings();cfg[group][key]=true;
    if(group==='merchant')cfg.merchant.weights['2']=1;
    assert.equal(growth.enabled(cfg),true);
    assert.ok(managed.requiredCapabilities(cfg).includes(cap));
    const capabilities=Object.fromEntries(managed.requiredCapabilities(cfg).map(k=>[k,{available:true,native_verified:false,test_enabled:true}]));
    const progression_state={available:true,merchant:{unlock_known:true,unlocked:true}};
    assert.equal(managed.controlState({phase:'idle',capabilities,progression_state},cfg,true).canStart,true);
    capabilities[cap].test_enabled=false;
    assert.equal(managed.controlState({phase:'idle',capabilities},cfg,true).canStart,false);
  }
});

test('talent editing fills prerequisite chains, enforces exclusivity and clears descendants',()=>{
  const nodes=[{id:'a',max_points:3},{id:'b',max_points:2,prerequisite:'a'},
    {id:'c',max_points:1,prerequisite:'b',exclusive_group:'capstone'},
    {id:'d',max_points:1,exclusive_group:'capstone'}, {id:'unused',max_points:1,selectable:false}];
  assert.deepEqual(growth.talentChange(nodes,{},'c',1),{a:3,b:2,c:1});
  assert.deepEqual(growth.talentChange(nodes,{a:3,b:2,c:1},'a',-1),{a:2});
  assert.deepEqual(growth.talentChange(nodes,{a:3,b:2,c:1},'d',1),{a:3,b:2,d:1});
  assert.deepEqual(growth.talentChange(nodes,{},'unused',1),{});
  assert.deepEqual(growth.talentChange(nodes,{a:3},'a',1),{a:3});
});

test('talent clicks and shift-fill share a seventy point budget including prerequisites',()=>{
  const nodes=[{id:'a',max_points:70},{id:'b',max_points:5},{id:'c',max_points:1,prerequisite:'b'}];
  assert.deepEqual(growth.talentChange(nodes,{a:70},'b',1),{a:70});
  assert.deepEqual(growth.talentChange(nodes,{a:69},'b',5),{a:69,b:1});
  assert.deepEqual(growth.talentChange(nodes,{a:69},'c',1),{a:69});
  assert.deepEqual(growth.talentChange(nodes,{a:70},'a',-1),{a:69});
  const cfg=managed.normalizeSettings({progression:{talent_targets:{'4':{a:70,b:1}}}});
  assert.match(managed.validateSettings(cfg),/最多 70 点/);
});

test('merchant defaults are zero and saved explicit ratios survive normalization',()=>{
  assert.deepEqual(Object.values(growth.normalize().merchant.weights),Array(10).fill(0));
  const cfg=growth.normalize({merchant:{weights:{'2':10,'3':1}}});
  assert.equal(cfg.merchant.weights['2'],10);assert.equal(cfg.merchant.weights['3'],1);
  assert.equal(cfg.merchant.weights['1'],0);
});

test('catalog exposes current tree nodes with resolvable icons and actual shard bonuses',()=>{
  assert.deepEqual(Object.values(data.heroes).map(h=>h.talents.filter(n=>n.selectable!==false).length).sort(),[40,40,41,41]);
  const capNodes=data.life_skills.filter(n=>n.soul_capacity_per_rank);
  assert.equal(data.soul_maximum+capNodes.reduce((sum,n)=>sum+n.soul_capacity_per_rank*n.max_points,0),3000);
  assert.ok(capNodes.every(n=>!n.description.includes('{value}')));
  for(const h of Object.values(data.heroes))for(const row of [...h.talents,...h.abilities])
    assert.ok(fs.existsSync(require('node:path').join(__dirname,'../deskrawl_assistant/web',row.icon)));
});

test('merchant ratios and gold reserves reject unsafe numeric values',()=>{
  const cfg=managed.normalizeSettings();cfg.merchant.enabled=true;
  cfg.merchant.weights=Object.fromEntries(Array.from({length:10},(_,n)=>[n+1,0]));
  assert.match(managed.validateSettings(cfg),/购买比例/);
  cfg.merchant.weights['1']=1;cfg.merchant.spend_to_percent=90;
  assert.match(managed.validateSettings(cfg),/保留比例/);
  cfg.merchant.spend_to_percent=10;cfg.life_skills.gold_reserve=-1;
  assert.match(managed.validateSettings(cfg),/保留金币/);
});
