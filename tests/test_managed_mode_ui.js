const {test}=require('node:test');
const assert=require('node:assert/strict');
const ui=require('../deskrawl_assistant/web/managed-mode.js');
const settings=(extra={})=>ui.normalizeSettings({auto_equip:{enabled:false,minimum_delta:1,slot_locks:{}},
  farming:{enabled:true,mode:'repeat',dungeon_id:12,progression:[],free_threshold:4},
  cleanup:{equipment_action:'store',equipment_fallback:'sell',equipment_pages:[1],rune_action:'store',rune_pages:[3],gem_action:'store',gem_pages:[3]},...extra});
const capabilities=value=>Object.fromEntries(['transfer','lock','equip','travel','difficulty','sell','salvage','chests','ground_pickup'].map(key=>[key,value]));

test('partition defaults fill absent values without replacing saved choices or explicit empty selections',()=>{
  const defaults=ui.normalizeSettings();
  assert.deepEqual(defaults.cleanup.equipment_pages,[1,2,3]);
  assert.deepEqual(defaults.cleanup.rune_pages,[4]);assert.deepEqual(defaults.cleanup.gem_pages,[5]);
  const saved=ui.normalizeSettings({cleanup:{equipment_pages:[7],rune_pages:[2,8],gem_pages:[]}});
  assert.deepEqual(saved.cleanup.equipment_pages,[7]);assert.deepEqual(saved.cleanup.rune_pages,[2,8]);assert.deepEqual(saved.cleanup.gem_pages,[]);
  defaults.cleanup.gem_pages.push(9);assert.deepEqual(ui.normalizeSettings().cleanup.gem_pages,[5]);
});

test('prohibited slot choice retains named gear, remains independent and survives save normalization',()=>{
  const original=settings({auto_equip:{enabled:true,slot_locks:{'6':'LegendaryRing1','7':'LegendaryRing2'}}});
  assert.deepEqual(original.auto_equip.disabled_slots,[]);
  const excluded=ui.withSlotChoice(original,6,ui.disabledChoice);
  assert.deepEqual(excluded.auto_equip.disabled_slots,[6]);
  assert.deepEqual(excluded.auto_equip.slot_locks,original.auto_equip.slot_locks);
  assert.deepEqual(original.auto_equip.disabled_slots,[]);
  assert.deepEqual(ui.normalizeSettings(JSON.parse(JSON.stringify(excluded))),excluded);
  assert.deepEqual(ui.equipmentPreset(excluded,'sell_low').auto_equip,excluded.auto_equip);
  assert.equal(ui.validateSettings(excluded),'');
  const both=ui.withSlotChoice(excluded,7,ui.disabledChoice);
  assert.deepEqual(both.auto_equip.disabled_slots,[6,7]);
  const restore=ui.withSlotChoice(both,6,'LegendaryRing1');
  assert.deepEqual(restore.auto_equip.disabled_slots,[7]);
  assert.equal(restore.auto_equip.slot_locks['6'],'LegendaryRing1');
  const unrestricted=ui.withSlotChoice(both,6,'');
  assert.deepEqual(unrestricted.auto_equip.disabled_slots,[7]);
  assert.equal(unrestricted.auto_equip.slot_locks['6'],undefined);
  assert.equal(unrestricted.auto_equip.slot_locks['7'],'LegendaryRing2');
  for(const bad of [[true],[-1],[12],['6'],[6,6]]){
    const invalid=ui.normalizeSettings(original);invalid.auto_equip.disabled_slots=bad;
    assert.match(ui.validateSettings(invalid),/部位/);
  }
});

test('legendary choices follow the current class and include shared equipment',()=>{
  const equipment=[1,2,4,8,15].map(mask=>({key:'weapon-'+mask,name:'武器 '+mask,slot:'Weapon',class_mask:mask,legendary:true,icon:'/icons/'+mask+'.png'}));
  equipment.push({key:'normal',slot:'Weapon',class_mask:15,legendary:false},
    {key:'helmet',slot:'Helm',class_mask:15,legendary:true},
    {key:'unknown',slot:'Weapon',legendary:true});
  for(const mask of [1,2,4,8]){
    const rows=ui.slotEquipment(equipment,'Weapon',{available:true,class_mask:mask});
    assert.deepEqual(rows.map(g=>g.key),['weapon-'+mask,'weapon-15']);
    assert.equal(rows[0].icon,'/icons/'+mask+'.png');
  }
});

test('class availability never expands choices to other classes and rings stay searchable',()=>{
  const rows=[{key:'hunter-ring',name:'猎人戒指',en:'Hunter ring',slot:'Ring',class_mask:4,legendary:true},
    {key:'mage-ring',name:'法师戒指',slot:'Ring',class_mask:2,legendary:true},
    {key:'shared',name:'通用戒指',slot:'Ring',class_mask:15,legendary:true}];
  for(const character of [undefined,{available:false,class_mask:4},{available:true,class_mask:'4'},
    {available:true,class_mask:0},{available:true,class_mask:3},{available:true,class_mask:true}]){
    assert.equal(ui.characterClass(character),null);assert.deepEqual(ui.slotEquipment(rows,'Ring',character),[]);
  }
  const hunter={available:true,class_mask:4};
  assert.deepEqual(ui.slotEquipment(rows,'Ring1',hunter).map(g=>g.key),['hunter-ring','shared']);
  assert.deepEqual(ui.slotEquipment(rows,'Ring2',hunter,' HUNTER ').map(g=>g.key),['hunter-ring']);
  assert.deepEqual(ui.slotEquipment(rows,'Ring',hunter,'法师'),[]);
});

test('recommended background switches migrate and respect explicit disable',()=>{
  assert.deepEqual(settings().background,{rule_monitoring:true,inventory_automation:true});
  const s=settings({background:{rule_monitoring:false,inventory_automation:false},farming:{enabled:false},auto_equip:{enabled:true}});
  assert.deepEqual(s.background,{rule_monitoring:false,inventory_automation:false});
  assert.deepEqual(ui.requiredCapabilities(s),['transfer','equip']);
});

test('graceful stop exposes a distinct immediate abort while finishing',()=>{
  assert.equal(ui.controlState({running:true},settings(),true).stopLabel,'回城整理后停止');
  const c=ui.controlState({running:true,finishing:true,phase:'cleanup'},settings(),true);
  assert.equal(c.stopLabel,'立即停止');assert.equal(c.canStop,true);assert.equal(c.canReset,false);
});

test('estimated carriage outcomes retain provenance for the count display',()=>{
  const rows=ui.statistics({equipment:{normal:{count:3,sold:3,estimated_sold:2}}}).equipment;
  const normal=rows.find(r=>r.key==='normal');assert.equal(normal.sold,3);assert.equal(normal.estimatedSold,2);
});

test('unverified native capabilities cannot enable disposal or start',()=>{
  const s=settings(),ready={running:false,phase:'idle',capabilities:capabilities({available:true,native_verified:true})};
  assert.equal(ui.controlState(ready,s,true).canStart,true);
  for(const key of ['travel','sell','ground_pickup','chests','lock']){
    const packet={...ready,capabilities:{...ready.capabilities,[key]:{available:false,reason:'待实机验证'}}};
    assert.equal(ui.controlState(packet,s,true).canStart,false);
    assert.ok(ui.controlState(packet,s,true).missing.includes(key));
  }
  assert.equal(ui.capabilityAvailable({available:true,native_verified:false}),false);
  assert.equal(ui.capabilityAvailable({available:false,supported:true}),false);
  assert.equal(ui.controlState({...ready,can_start:false},s,true).canStart,false);
  assert.equal(ui.controlState(ready,s,false).canStart,false);
});

test('only automatic equip does not require selling, chest opening or ground collection',()=>{
  const s=settings({auto_equip:{enabled:true,slot_locks:{'8':'LegendaryNeck3'}},farming:{enabled:false,free_threshold:4}});
  assert.deepEqual(ui.requiredCapabilities(s),['transfer','equip','lock']);
  assert.equal(ui.controlState({phase:'idle',capabilities:{transfer:true,equip:true,lock:true}},s,true).canStart,true);
  assert.equal(s.auto_equip.slot_locks['8'],'LegendaryNeck3');
});

test('difficulty settings preserve old configuration and choose maps from the selected tier',()=>{
  const s=settings(),packet={current_difficulty:'Inferno',maps:[{id:'current'}],
    maps_by_difficulty:{Normal:[{id:'normal'}],Nightmare:[{id:'nightmare'}],Inferno:[{id:'inferno'}]}};
  assert.equal(s.farming.difficulty,'current');
  assert.deepEqual(ui.availableMaps(packet,s),[{id:'inferno'}]);
  s.farming.difficulty='Nightmare';
  assert.deepEqual(ui.availableMaps(packet,s),[{id:'nightmare'}]);
  assert.equal(ui.selectedDifficulty(s,packet),'Nightmare');
  assert.ok(ui.requiredCapabilities(s).includes('difficulty'));
});

test('a partially verified profile permits current difficulty repeat but blocks unavailable switching and pushing',()=>{
  const s=settings();s.cleanup.equipment_action='salvage';s.cleanup.equipment_fallback='salvage';
  s.cleanup.equipment_policies={};
  const available=capabilities({available:true,native_verified:true});
  available.difficulty=available.sell={available:false,native_verified:false};
  const packet={phase:'idle',capabilities:available};
  assert.equal(ui.requiredCapabilities(s).includes('difficulty'),false);
  assert.equal(ui.controlState(packet,s,true).canStart,true);
  s.farming.mode='push';assert.equal(ui.controlState(packet,s,true).canStart,false);
  s.farming.mode='repeat';s.farming.difficulty='Nightmare';
  assert.equal(ui.controlState(packet,s,true).canStart,false);
});

test('the release profile permits sale and cross difficulty push through the ordinary page',()=>{
  const profile=require('../data/game-actions-profile.json');
  const kinds={travel:['return_town','enter_map'],difficulty:['switch_difficulty'],equip:['equip'],
    sell:['sell'],salvage:['salvage'],chests:['open_chest'],ground_pickup:['collect_ground']};
  const ready={phase:'idle',control_available:true,capabilities:{transfer:true,lock:true,test_mode:false}};
  for(const [key,actions] of Object.entries(kinds)){
    const verified=actions.every(kind=>profile.verified_kinds.includes(kind));
    ready.capabilities[key]={available:verified,native_verified:verified,test_enabled:false};
  }
  const s=ui.equipmentPreset(settings({auto_equip:{enabled:true},
    farming:{enabled:true,mode:'push',difficulty:'Nightmare',dungeon_id:12,free_threshold:4}}),'sell_low');
  for(const key of ['difficulty','sell','salvage','equip'])assert.ok(ui.requiredCapabilities(s).includes(key));
  const state=ui.controlState(ready,s,true);
  assert.equal(state.canStart,true);assert.deepEqual(state.missing,[]);
});

test('explicit local test capability can start while incompatible actions remain unavailable',()=>{
  const s=settings(),packet={phase:'idle',capabilities:capabilities({available:true,native_verified:false,test_enabled:true})};
  assert.equal(ui.controlState(packet,s,true).canStart,true);
  assert.equal(ui.capabilityAvailable({available:true,native_verified:false,test_enabled:'true'}),false);
  packet.capabilities.travel={available:false,native_verified:false,test_enabled:true};
  assert.equal(ui.controlState(packet,s,true).canStart,false);
});

test('unreadable campaign disables farming even when native capabilities are test available',()=>{
  const s=settings(),packet={capabilities:capabilities(true),control_available:false,control_error:'关卡记录尚未加载'};
  assert.equal(ui.controlState(packet,s,true).canStart,false);
  packet.control_available=true;
  assert.equal(ui.controlState(packet,s,true).canStart,true);
});

test('warehouse permissions are 1 based and do not assume continuous pages',()=>{
  assert.deepEqual(ui.pageIds([1,2,5,5,'2',0,-1,undefined]),[1,2,5]);
  const s=settings();s.cleanup.equipment_pages=[];
  assert.match(ui.validateSettings(s),/装备存放页/);
  s.cleanup.equipment_pages=[5];s.cleanup.rune_pages=[];
  assert.match(ui.validateSettings(s),/符文/);
  s.cleanup.rune_action='sell';assert.match(ui.validateSettings(s),/符文/);
  s.cleanup.rune_pages=[3];s.cleanup.gem_pages=[];
  assert.match(ui.validateSettings(s),/宝石/);
  s.cleanup.gem_action='sell';assert.equal(ui.validateSettings(s),'');
});

test('repeat and push map identifiers retain zero and numeric types, double rings retain independent locks',()=>{
  const s=settings({auto_equip:{enabled:true,slot_locks:{'6':'LegendaryRing1','7':'LegendaryRing2'}},
    farming:{enabled:true,mode:'push',dungeon_id:0,progression:[0,1,2],free_threshold:4}});
  assert.equal(s.farming.dungeon_id,0);assert.deepEqual(s.farming.progression,[0,1,2]);
  assert.equal(s.auto_equip.slot_locks['6'],'LegendaryRing1');assert.equal(s.auto_equip.slot_locks['7'],'LegendaryRing2');
  assert.equal(ui.validateSettings(s),'');
  s.farming.dungeon_id=null;assert.equal(ui.validateSettings(s),''); // Push selects native highest unlock.
  s.farming.mode='repeat';s.farming.repeat_maps=[];assert.match(ui.validateSettings(s),/关卡/);
  s.farming.enabled=false;s.farming.free_threshold=3.5;assert.match(ui.validateSettings(s),/整数/);
});

test('push automatically chooses native unlocks and repeat plans migrate without losing map zero',()=>{
  const push=settings({farming:{enabled:true,mode:'push'}});assert.equal(ui.validateSettings(push),'');
  const legacy=settings({farming:{enabled:true,mode:'repeat',dungeon_id:0,difficulty:'Nightmare'}});
  assert.deepEqual(legacy.farming.repeat_maps,[{dungeon_id:0,difficulty:'Nightmare',runs:1}]);
  const routes=[{dungeon_id:0,difficulty:'current',runs:10},{dungeon_id:9,difficulty:'Nightmare',runs:3}];
  const s=settings({farming:{enabled:true,repeat_maps:routes}});assert.equal(s.farming.dungeon_id,0);
  assert.equal(ui.validateSettings(s),'');assert.ok(ui.requiredCapabilities(s).includes('difficulty'));
  s.farming.repeat_maps[0].runs=0;assert.match(ui.validateSettings(s),/局数/);assert.equal(routes[0].runs,10);
  s.farming.repeat_maps[0].runs=1;s.farming.repeat_maps[1]={...s.farming.repeat_maps[0]};assert.match(ui.validateSettings(s),/不能相同/);
});

test('drop totals exclude transfers and correctly display the engine black mist bucket',()=>{
  const result=ui.statistics({equipment:{divine:{count:1,sold:0},black_mist:{count:2,stored:2},ancient:{count:10,sold:7,salvaged:2}},
    runes:[{name:'猎人符文',count:3,sold:1,stored:2}],gems:[{name:'钻石',level:1,count:5,stored:15}]});
  assert.equal(result.equipment.find(row=>row.key==='black_mist').count,2);
  assert.equal(result.total,21);assert.equal(result.runeCount,3);assert.equal(result.gemCount,5);
  assert.equal(result.equipment.find(row=>row.key==='ancient').sold,7);
  assert.equal(result.equipment.find(row=>row.key==='ancient').salvaged,2);
});

test('running controls freeze configuration mutations and paused statistics require stop before reset',()=>{
  const s=settings(),packet={running:true,phase:'cleanup',capabilities:capabilities(true)};
  assert.equal(ui.controlState(packet,s,true).canStart,false);
  assert.equal(ui.controlState(packet,s,true).canPause,true);
  assert.equal(ui.controlState(packet,s,true).canReset,false);
  const paused={...packet,running:false,paused:true,phase:'paused'};
  assert.equal(ui.controlState(paused,s,true).canStart,true);
  assert.equal(ui.controlState(paused,s,true).canStop,true);
  assert.equal(ui.controlState(paused,s,true).canReset,false);
  assert.equal(ui.controlState({...packet,running:false,phase:'stopped'},s,true).canReset,true);
  assert.equal(ui.controlState(packet,s,true,true).canPause,true);
  assert.equal(ui.controlState(packet,s,true,true).canStop,true);
});

test('protective storage overflow requires its fallback even when new junk is directly sold',()=>{
  const s=ui.equipmentPreset(settings(),'sell');s.cleanup.equipment_policies.rare.fallback='salvage';
  assert.ok(ui.requiredCapabilities(s).includes('salvage'));
  const packet={running:false,phase:'idle',capabilities:{...capabilities(true),salvage:{available:false}}};
  assert.equal(ui.controlState(packet,s,true).canStart,false);
});

test('legacy disposal choices migrate to each quality without changing user preferences',()=>{
  const s=settings({cleanup:{equipment_action:'salvage',equipment_fallback:'sell',equipment_pages:[1]}});
  for(const key of ['ancient','legendary','rare','uncommon','normal'])assert.deepEqual(s.cleanup.equipment_policies[key],{action:'salvage',fallback:'sell'});
  assert.deepEqual(ui.normalizeSettings(s),s);
});

test('low quality sale preset is a draft and includes per-quality warehouse fallback',()=>{
  const previous=settings(),next=ui.equipmentPreset(previous,'sell_low');
  for(const key of ['normal','uncommon'])assert.deepEqual(next.cleanup.equipment_policies[key],{action:'sell',fallback:'sell'});
  for(const key of ['rare','legendary','ancient'])assert.deepEqual(next.cleanup.equipment_policies[key],{action:'salvage',fallback:'salvage'});
  assert.equal(previous.cleanup.equipment_policies.normal.action,'store');
  assert.ok(ui.requiredCapabilities(next).includes('sell'));assert.ok(ui.requiredCapabilities(next).includes('salvage'));
  assert.match(ui.equipmentSummary(next.cleanup),/普通：出售/);assert.match(ui.equipmentSummary(next.cleanup,true),/稀有：分解/);
  const stored=ui.equipmentPreset(next,'store');assert.equal(stored.cleanup.equipment_policies.rare.action,'store');assert.equal(stored.cleanup.equipment_policies.rare.fallback,'salvage');
  assert.throws(()=>ui.equipmentPreset(next,'wrong'));
});

test('statistics always show the quality hierarchy independent of input order or counts',()=>{
  const rows=ui.statistics({equipment:{normal:{count:10000},legendary:{count:5},ancient:{count:1},rare:{count:100},uncommon:{count:1000},black_mist:{count:2},divine:{count:1}}}).equipment;
  assert.deepEqual(rows.map(row=>row.key),['divine','black_mist','ancient','legendary','rare','uncommon','normal']);
  assert.deepEqual(rows.map(row=>row.name),['神圣','黑雾传说','远古传说','普通传说','稀有','优秀','普通']);
  assert.equal(ui.statistics({equipment:{mist:{count:4}}}).equipment[1].count,4);
});

test('disabled automation does not present a runnable empty configuration',()=>{
  const s=settings({farming:{enabled:false,free_threshold:4}});
  assert.equal(ui.controlState({phase:'idle',capabilities:capabilities(true)},s,true).canStart,false);
  assert.match(ui.controlState({phase:'idle'},s,true).configurationError,/至少启用/);
  assert.equal(ui.duration(3661),'01:01:01');assert.equal(ui.duration(-1),'00:00:00');
});
