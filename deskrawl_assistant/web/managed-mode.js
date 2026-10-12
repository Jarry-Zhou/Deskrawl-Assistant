'use strict';
(function(root){
  const growthTools=typeof module!=='undefined'&&module.exports?require('./managed-growth.js'):root.ManagedGrowthUI.helpers;
  const storageTools=typeof module!=='undefined'&&module.exports?require('./automation-tools.js'):root.AutomationTools;
  const phaseNames={idle:'尚未启动',stopped:'已停止',paused:'已暂停',starting:'准备托管',farming:'刷图中',pushing:'推图中',travel:'进入关卡',returning:'回城中',scanning:'扫描奖励',equipping:'自动换装',cleanup:'整理奖励',collecting:'收取马车 / 地面物品',opening_chests:'开启宝箱',waiting:'等待处理',blocked:'已暂停 · 需要处理',error:'已停止 · 操作异常',growing:'自动成长',shopping:'神秘商人购买'};
  const rarityNames=[['divine','神圣'],['black_mist','黑雾传说'],['ancient','远古传说'],['legendary','普通传说'],['rare','稀有'],['uncommon','优秀'],['normal','普通']];
  const disposalRarities=rarityNames.slice(2),dispositionNames={store:'放入仓库',sell:'出售',salvage:'分解'};
  const capabilityNames={transfer:'物品转移',lock:'装备保护',equip:'后台换装',travel:'回城 / 进入关卡',difficulty:'主城切换难度',sell:'出售',salvage:'分解',chests:'开启宝箱',ground_pickup:'地面拾取',merchant:'神秘商人消费',talents:'职业天赋加点',life_skills:'生活技能学习',skills:'技能切换'};
  const difficultyNames={Normal:'普通',Nightmare:'噩梦',Inferno:'炼狱'};
  const disabledChoice='__disabled_slot__';
  const clone=value=>JSON.parse(JSON.stringify(value));
  const safeNumber=(value,fallback=0)=>Number.isFinite(Number(value))&&value!==null&&value!==''?Number(value):fallback;
  const pageIds=values=>[...new Set((Array.isArray(values)?values:[]).map(Number).filter(n=>Number.isInteger(n)&&n>0))].sort((a,b)=>a-b);
  const oneOf=(value,choices,fallback)=>choices.includes(value)?value:fallback;
  function normalizeSettings(value={}){
    const eq=value.auto_equip||{},farm=value.farming||{},cleanup=value.cleanup||{},background=value.background||{};
    const mode=oneOf(farm.mode,['repeat','push'],'repeat'),repeatMaps=Array.isArray(farm.repeat_maps)&&farm.repeat_maps.length?clone(farm.repeat_maps):farm.dungeon_id!==null&&farm.dungeon_id!==undefined?[{dungeon_id:farm.dungeon_id,difficulty:farm.difficulty||'current',runs:1}]:[];
    return {...growthTools.normalize(value),background:{rule_monitoring:background.rule_monitoring!==false,inventory_automation:background.inventory_automation!==false},auto_equip:{enabled:!!eq.enabled,minimum_delta:safeNumber(eq.minimum_delta,1),slot_locks:{...(eq.slot_locks||{})},disabled_slots:Array.isArray(eq.disabled_slots)?[...eq.disabled_slots]:[]},
      farming:{enabled:!!farm.enabled,mode,dungeon_id:mode==='repeat'&&repeatMaps.length?repeatMaps[0].dungeon_id:farm.dungeon_id??null,difficulty:mode==='repeat'&&repeatMaps.length?repeatMaps[0].difficulty:oneOf(farm.difficulty,['current','Normal','Nightmare','Inferno'],'current'),progression:Array.isArray(farm.progression)?clone(farm.progression):[],repeat_maps:repeatMaps,free_threshold:safeNumber(farm.free_threshold,4)},
      cleanup:{equipment_action:oneOf(cleanup.equipment_action,['store','sell','salvage'],'store'),equipment_fallback:oneOf(cleanup.equipment_fallback,['sell','salvage'],'sell'),
        equipment_policies:Object.fromEntries(disposalRarities.map(([key])=>{const p=cleanup.equipment_policies?.[key]||{};return [key,{action:oneOf(p.action,['store','sell','salvage'],oneOf(cleanup.equipment_action,['store','sell','salvage'],'store')),fallback:oneOf(p.fallback,['sell','salvage'],oneOf(cleanup.equipment_fallback,['sell','salvage'],'sell'))}];})),equipment_pages:pageIds(cleanup.equipment_pages??storageTools.defaultPages.equipment),
        rune_action:oneOf(cleanup.rune_action,['store','sell'],'store'),rune_pages:pageIds(cleanup.rune_pages??storageTools.defaultPages.rune),gem_action:oneOf(cleanup.gem_action,['store','sell'],'store'),gem_pages:pageIds(cleanup.gem_pages??storageTools.defaultPages.gem)}};
  }
  function equipmentPreset(settings,preset){
    const next=normalizeSettings(settings);
    if(!['sell_low','sell','salvage','store'].includes(preset))throw new Error('装备处理预设无效。');
    for(const [key] of disposalRarities){
      const action=preset==='sell_low'?(['normal','uncommon'].includes(key)?'sell':'salvage'):preset;
      next.cleanup.equipment_policies[key].action=action;
      if(action!=='store')next.cleanup.equipment_policies[key].fallback=action;
    }
    return next;
  }
  function equipmentSummary(cleanup,fallback=false){
    const policies=normalizeSettings({cleanup}).cleanup.equipment_policies;
    return disposalRarities.map(([key,name])=>`${name}：${dispositionNames[policies[key][fallback?'fallback':'action']]}`).join('；');
  }
  function validateSettings(settings){
    const f=settings.farming,c=settings.cleanup;
    const disabled=settings.auto_equip.disabled_slots;
    if(!Array.isArray(disabled)||disabled.some(n=>!Number.isInteger(n)||n<0||n>=12)||new Set(disabled).size!==disabled.length)return '不参与自动换装的部位无效。';
    if(f.enabled&&f.mode==='repeat'&&!f.repeat_maps.length)return '请选择重复刷图关卡。';
    if(f.repeat_maps.length>2||f.repeat_maps.some(row=>row.dungeon_id===null||row.dungeon_id===undefined||row.dungeon_id===''||!['current','Normal','Nightmare','Inferno'].includes(row.difficulty)||!Number.isInteger(row.runs)||row.runs<1||row.runs>10000))return '请选择一张或两张关卡，每轮局数为 1 至 10000。';
    if(new Set(f.repeat_maps.map(row=>`${row.difficulty}:${row.dungeon_id}`)).size!==f.repeat_maps.length)return '两张重复刷图关卡不能相同。';
    if(!Number.isInteger(f.free_threshold)||f.free_threshold<1||f.free_threshold>2048)return '回城阈值须为 1 至 2048 的整数。';
    if(!c.equipment_pages.length)return '请选择装备存放页，黑雾 / 神圣与符合规则的装备需要保留空间。';
    if(!c.rune_pages.length)return '请勾选符文存放页，套装与宏伟符文必须收纳。';
    if(c.gem_action==='store'&&!c.gem_pages.length)return '宝石选择放入仓库时，需要至少勾选一个仓库页。';
    const {merchant:m,life_skills:l}=growthTools.normalize(settings);
    if(Object.values(settings.progression.talent_targets).some(targets=>Object.values(targets).reduce((sum,n)=>sum+n,0)>growthTools.talentPointLimit))return `每个职业的战斗天赋预设最多 ${growthTools.talentPointLimit} 点，请先减少预设点数。`;
    if(!Number.isInteger(m.trigger_percent)||!Number.isInteger(m.spend_to_percent)||m.trigger_percent<1||m.trigger_percent>100||m.spend_to_percent<0||m.spend_to_percent>=m.trigger_percent)return '购买后保留比例须低于碎片回城触发比例。';
    if(Object.values(m.weights).some(n=>!Number.isInteger(n)||n<0||n>1000)||m.enabled&&!Object.values(m.weights).some(n=>n>0))return '购买比例须为 0 至 1000 的整数，至少选择一个部位。';
    if(!Number.isInteger(l.gold_reserve)||l.gold_reserve<0||l.gold_reserve>2147483647)return '生活技能保留金币数量无效。';
    return '';
  }
  function capabilityAvailable(value){return value===true||!!(value&&typeof value==='object'&&(value.native_verified!==false||value.test_enabled===true||value.release_enabled===true)&&(value.available===true||(value.available===undefined&&value.supported===true)));}
  function requiredCapabilities(settings){
    const c=settings.cleanup,keys=[];
    if(settings.farming.enabled)keys.push('transfer','lock','chests','ground_pickup');
    else if(settings.auto_equip.enabled)keys.push('transfer');
    if(settings.auto_equip.enabled)keys.push('equip');
    if(settings.background.rule_monitoring&&!keys.includes('lock'))keys.push('lock');
    if(settings.farming.enabled){keys.push('travel');if(settings.farming.mode==='push'||settings.farming.difficulty!=='current'||settings.farming.repeat_maps?.some(row=>row.difficulty!=='current'))keys.push('difficulty');}
    const growth=growthTools.normalize(settings);
    if(growth.progression.talents_enabled)keys.push('talents');if(growth.progression.skills_enabled)keys.push('skills');if(growth.life_skills.enabled)keys.push('life_skills');
    if(growth.merchant.enabled)keys.push('merchant','travel','transfer','lock','chests','ground_pickup');
    const actions=settings.farming.enabled||growth.merchant.enabled?[...Object.values(normalizeSettings(settings).cleanup.equipment_policies).flatMap(p=>[p.action,p.fallback]),c.rune_action,c.gem_action]:[];
    if(actions.includes('sell'))keys.push('sell');if(actions.includes('salvage'))keys.push('salvage');return keys;
  }
  function controlState(packet,settings,connected,busy=false){
    const running=!!packet?.running,phase=packet?.phase||'idle',growth=growthTools.normalize(settings);
    const missing=requiredCapabilities(settings).filter(key=>!capabilityAvailable(packet?.capabilities?.[key]));
    const configurationError=validateSettings(settings)||(!settings.auto_equip.enabled&&!settings.farming.enabled&&!growth.merchant.enabled&&!growth.life_skills.enabled&&!growth.progression.talents_enabled&&!growth.progression.skills_enabled?'请至少启用一项托管功能。':'');
    const merchantBlocked=growth.merchant.enabled&&(packet?.progression_state?.available!==true||packet.progression_state.merchant?.unlock_known!==true||packet.progression_state.merchant?.unlocked!==true);
    const blocked=packet?.can_start===false||missing.length>0||!!configurationError||merchantBlocked||(settings.farming.enabled&&packet?.control_available===false);
    return {canStart:!!connected&&!running&&!busy&&!blocked,canPause:running,canStop:running||!!packet?.paused||!['idle','stopped'].includes(phase),canReset:!running&&!packet?.paused&&!busy,stopLabel:packet?.finishing?'立即停止':'回城整理后停止',missing,configurationError};
  }
  function statistics(value={}){
    const count=row=>Math.max(0,safeNumber(row?.count)),group=rows=>Array.isArray(rows)?rows:Object.entries(rows||{}).map(([name,row])=>typeof row==='object'?{name,...row}:{name,count:row});
    const equipment=rarityNames.map(([key,name])=>{const row=value.equipment?.[key]||(key==='black_mist'?value.equipment?.mist:null)||{};return {key,name,count:count(row),sold:Math.max(0,safeNumber(row.sold)),salvaged:Math.max(0,safeNumber(row.salvaged)),stored:Math.max(0,safeNumber(row.stored)),estimatedSold:Math.max(0,safeNumber(row.estimated_sold)),estimatedSalvaged:Math.max(0,safeNumber(row.estimated_salvaged))};});
    const runes=group(value.runes).map(row=>({...row,count:count(row)})),gems=group(value.gems).map(row=>({...row,count:count(row)}));
    const runeCount=runes.reduce((sum,row)=>sum+row.count,0),gemCount=gems.reduce((sum,row)=>sum+row.count,0);
    return {equipment,runes,gems,runeCount,gemCount,total:equipment.reduce((sum,row)=>sum+row.count,0)+runeCount+gemCount};
  }
  function duration(seconds){const n=Math.max(0,Math.floor(safeNumber(seconds)));return [Math.floor(n/3600),Math.floor(n/60)%60,n%60].map(n=>String(n).padStart(2,'0')).join(':');}
  function selectedDifficulty(settings,packet){return settings.farming.difficulty==='current'?packet?.current_difficulty:settings.farming.difficulty;}
  function availableMaps(packet,settings,difficulty=settings.farming.difficulty){const tier=difficulty==='current'?packet?.current_difficulty:difficulty;return packet?.maps_by_difficulty?.[tier]||packet?.maps||[];}
  function characterClass(character){
    const mask=character?.class_mask;
    return character?.available===true&&[1,2,4,8].includes(mask)?mask:null;
  }
  function slotEquipment(equipment,slot,character,query=''){
    const mask=characterClass(character),name=slot==='Ring1'||slot==='Ring2'?'Ring':slot,search=query.trim().toLowerCase();
    if(mask===null)return [];
    return (equipment||[]).filter(gear=>gear.legendary===true&&gear.slot===name&&Number.isInteger(gear.class_mask)
      &&gear.class_mask>0&&(gear.class_mask&mask)!==0&&(!search||[gear.name,gear.en,gear.key].some(v=>String(v||'').toLowerCase().includes(search))));
  }
  function withSlotChoice(settings,index,key){
    if(!Number.isInteger(index)||index<0||index>=12||typeof key!=='string')throw new Error('自动换装部位选择无效。');
    const next=normalizeSettings(settings),disabled=new Set(next.auto_equip.disabled_slots);
    if(key===disabledChoice)disabled.add(index);
    else{disabled.delete(index);if(key)next.auto_equip.slot_locks[index]=key;else delete next.auto_equip.slot_locks[index];}
    next.auto_equip.disabled_slots=[...disabled].sort((a,b)=>a-b);return next;
  }
  const helpers={normalizeSettings,validateSettings,pageIds,controlState,requiredCapabilities,statistics,duration,capabilityAvailable,selectedDifficulty,availableMaps,equipmentPreset,equipmentSummary,characterClass,slotEquipment,withSlotChoice,disabledChoice};
  if(typeof module!=='undefined'&&module.exports)module.exports=helpers;
  if(!root.document)return;
  const $=id=>root.document.getElementById(id);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let context=null,packet=null,draft=null,dirty=false,connected=false,busy=false,polling=false,active=false,initialized=false;
  let receivedAt=0,pageSignature='',mapSignature='',slotSignature='',statsSignature='',historySignature='',actionVersion=0;
  let currentCharacter=null,pickerSlot=null,pickerSignature='';
  const farmFields=['managed-farm-mode','managed-difficulty','managed-map','managed-repeat-two','managed-repeat-count','managed-difficulty-two','managed-map-two','managed-repeat-count-two','managed-free-threshold'];
  const fieldIds=['managed-rule-monitoring','managed-inventory-automation','managed-auto-equip','managed-farming',...farmFields,'managed-rune-action','managed-gem-action'];
  const catalog=()=>context?.catalog||{};
  const maps=()=>availableMaps(packet,draft||normalizeSettings());
  const mapId=row=>row.id??row.dungeon_id;
  const phaseLabel=()=>packet?.phase_label||phaseNames[packet?.phase]||packet?.phase||'尚未启动';
  function markDirty(value=true){dirty=value;const text=dirty?'有未保存的托管设置':'设置已保存';for(const id of ['managed-draft-state','managed-growth-save-state','managed-shop-save-state'])$(id).textContent=text;context?.onDirty?.();}
  function report(error){$('managed-error').textContent=error?.message||String(error);$('managed-error').hidden=false;context?.toast?.($('managed-error').textContent,true);}
  function readForm(){
    const next=normalizeSettings({...draft,...root.ManagedGrowthUI?.read?.()}),f=next.farming,c=next.cleanup;
    next.background.rule_monitoring=$('managed-rule-monitoring').checked;next.background.inventory_automation=$('managed-inventory-automation').checked;
    next.auto_equip.enabled=$('managed-auto-equip').checked;next.auto_equip.slot_locks={};
    root.document.querySelectorAll('[data-managed-slot]').forEach(select=>{if(select.value)next.auto_equip.slot_locks[select.dataset.managedSlot]=select.value;});
    f.enabled=$('managed-farming').checked;f.mode=$('managed-farm-mode').value;f.free_threshold=Number($('managed-free-threshold').value);
    f.difficulty=$('managed-difficulty').value;
    const selectedMap=(id,difficulty)=>{const value=$(id).value,found=availableMaps(packet,next,difficulty).find(row=>String(mapId(row))===value);return found?mapId(found):value||null;};
    f.dungeon_id=selectedMap('managed-map',f.difficulty);
    f.repeat_maps=f.dungeon_id!==null||$('managed-repeat-two').checked?[{dungeon_id:f.dungeon_id,difficulty:f.difficulty,runs:Number($('managed-repeat-count').value)}]:[];
    if($('managed-repeat-two').checked)f.repeat_maps.push({dungeon_id:selectedMap('managed-map-two',$('managed-difficulty-two').value),difficulty:$('managed-difficulty-two').value,runs:Number($('managed-repeat-count-two').value)});
    if(f.mode==='push'&&f.repeat_maps.some(row=>row.dungeon_id===null||!Number.isInteger(row.runs)||row.runs<1||row.runs>10000))f.repeat_maps=[];
    if(f.mode==='repeat')f.progression=[]; // Only the backend declares the campaign route.
    for(const [key] of disposalRarities){const p=c.equipment_policies[key];for(const field of ['action','fallback'])p[field]=$(`managed-equipment-${key}-${field}`).value;}
    c.rune_action=$('managed-rune-action').value;c.gem_action=$('managed-gem-action').value;
    for(const kind of ['equipment','rune','gem'])c[kind+'_pages']=pageIds([...root.document.querySelectorAll(`[data-managed-pages="${kind}"]:checked`)].map(input=>input.value));
    return next;
  }
  function slots(){
    if(Array.isArray(catalog().equipped_slot_options))return catalog().equipped_slot_options;
    return ['Weapon','Helm','Chest','Pants','Boots','Belt','Ring','Ring','Necklace','Shoulder','Gloves','Back'].map((slot,index)=>({index,slot,name:['武器','头盔','胸甲','裤子','靴子','腰带','戒指 1','戒指 2','项链','护肩','手套','披风'][index]}));
  }
  const character=()=>connected?currentCharacter:null;
  function className(){const mask=characterClass(character());return (catalog().classes||[]).find(row=>row.value===mask)?.name||'当前职业';}
  function gearIcon(gear){return gear?.disabled?'<svg class="managed-prohibited-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M5.6 5.6 18.4 18.4"/></svg>':gear?.icon?`<img src="${esc(gear.icon)}" alt="" loading="lazy">`:'<span aria-hidden="true">◇</span>';}
  function closePicker(restoreFocus=false){
    const button=pickerSlot===null?null:root.document.querySelector(`[data-managed-picker="${pickerSlot}"]`);
    $('managed-gear-menu').hidden=true;pickerSlot=null;pickerSignature='';
    root.document.querySelectorAll('[data-managed-picker]').forEach(input=>input.setAttribute('aria-expanded','false'));
    if(restoreFocus)button?.focus();
  }
  function positionPicker(){
    if(pickerSlot===null)return;
    const button=root.document.querySelector(`[data-managed-picker="${pickerSlot}"]`),menu=$('managed-gear-menu');
    if(!button||!button.getClientRects().length){closePicker();return;}
    const rect=button.getBoundingClientRect(),margin=8,gap=5,width=Math.min(Math.max(rect.width,280),root.innerWidth-margin*2);
    if(rect.bottom<=0||rect.top>=root.innerHeight){closePicker();return;}
    const below=root.innerHeight-rect.bottom-margin-gap,above=rect.top-margin-gap,up=below<240&&above>below;
    menu.style.width=width+'px';menu.style.left=Math.max(margin,Math.min(rect.left,root.innerWidth-width-margin))+'px';
    menu.style.maxHeight=Math.max(0,Math.min(360,up?above:below))+'px';
    menu.style.top=up?'auto':rect.bottom+gap+'px';menu.style.bottom=up?root.innerHeight-rect.top+gap+'px':'auto';
  }
  function renderSlots(){
    const mask=characterClass(character()),signature=JSON.stringify([slots(),catalog().equipment,draft?.auto_equip.slot_locks,draft?.auto_equip.disabled_slots,mask,connected]);if(signature===slotSignature)return;slotSignature=signature;
    $('managed-class-scope').textContent=mask===null?(connected?'正在读取角色职业，读取完成后显示可用装备。':'连接游戏后，自动按当前职业筛选装备。'):`当前职业：${className()} · 仅显示本职业及通用装备`;
    $('managed-slot-locks').innerHTML=slots().map(row=>{
      const index=String(row.index??row.value??row.id),slot=row.slot==='Ring1'||row.slot==='Ring2'?'Ring':row.slot;
      const options=slotEquipment(catalog().equipment,slot,character()),selected=draft?.auto_equip.slot_locks[index]||'',gear=(catalog().equipment||[]).find(g=>g.key===selected);
      const excluded=draft?.auto_equip.disabled_slots.includes(Number(index));
      const unavailable=selected&&!options.some(g=>g.key===selected),note=unavailable?(mask===null?'等待读取职业':gear?'当前职业不可用':'暂未收录'):'点击选择暗金装备';
      const unknown=selected&&!options.some(g=>g.key===selected)?`<option value="${esc(selected)}" selected>${esc(selected)} · 暂未收录</option>`:'';
      const label=row.name||row.label||slot,disabled=packet?.running||busy||!draft?.auto_equip.enabled;
      return `<div class="managed-slot-field"><span>${esc(label)}</span><button class="managed-gear-select ${excluded?'excluded':unavailable?'unavailable':''}" type="button" data-managed-picker="${esc(index)}" aria-label="${esc(label)}自动换装设置" aria-haspopup="listbox" aria-controls="managed-gear-choices" aria-expanded="${pickerSlot===index}" ${disabled?'disabled':''}><span class="managed-gear-icon">${gearIcon(excluded?{disabled:true}:gear)}</span><span class="managed-gear-label"><strong>${esc(excluded?'不参与自动换装':gear?.name||selected||'不限制名称')}</strong><small>${esc(excluded?'保持当前部位装备':selected?note:'所有可穿戴品质')}</small></span><span class="managed-gear-caret" aria-hidden="true">⌄</span></button><select data-managed-slot="${esc(index)}" hidden aria-hidden="true" tabindex="-1"><option value="">不限制名称 · 所有品质</option>${unknown}${options.map(g=>`<option value="${esc(g.key)}" ${g.key===selected?'selected':''}>${esc(g.name)}</option>`).join('')}</select></div>`;
    }).join('');
    if(pickerSlot!==null){renderPicker();positionPicker();}
  }
  function renderPicker(){
    const row=slots().find(row=>String(row.index??row.value??row.id)===pickerSlot);if(!row)return;
    const query=$('managed-gear-search').value,options=slotEquipment(catalog().equipment,row.slot,character(),query),selected=draft?.auto_equip.disabled_slots.includes(Number(pickerSlot))?disabledChoice:draft?.auto_equip.slot_locks[pickerSlot]||'';
    const signature=JSON.stringify([pickerSlot,characterClass(character()),query,options,selected]);if(signature===pickerSignature)return;pickerSignature=signature;
    $('managed-gear-choices').setAttribute('aria-label',(row.name||row.label||row.slot)+'自动换装选项');
    $('managed-gear-scope').textContent=characterClass(character())===null?'连接游戏后显示可用装备':`${className()}可用 · ${options.length} 件装备`;
    const choice=(gear)=>`<button class="managed-gear-choice ${gear.disabled?'excluded ':''}${gear.key===selected?'selected':''}" type="button" role="option" data-managed-choice="${esc(gear.key)}" aria-selected="${gear.key===selected}" title="${esc(gear.description||'所有可穿戴品质均可参与战力比较')}"><span class="managed-gear-icon">${gearIcon(gear)}</span><span><strong>${esc(gear.name)}</strong><small>${esc(gear.disabled?'保持当前部位装备':gear.key?gear.en||gear.slot_label||'传说装备':'所有可穿戴品质')}</small></span><b aria-hidden="true">${gear.key===selected?'✓':''}</b></button>`;
    $('managed-gear-choices').innerHTML=choice({key:disabledChoice,name:'不参与自动换装',disabled:true,description:'跳过此部位的自动换装，保留已配置的暗金限制。'})+choice({key:'',name:'不限制名称'})+options.map(choice).join('')+(!options.length?'<p class="managed-picker-empty">'+esc(characterClass(character())===null?'等待读取职业':'没有符合搜索条件的装备')+'</p>':'');
  }
  function openPicker(index){
    if(packet?.running||busy||!draft?.auto_equip.enabled)return;
    if(!slots().some(row=>String(row.index??row.value??row.id)===index))return;
    if(pickerSlot===index){closePicker(true);return;}
    closePicker();pickerSlot=index;pickerSignature='';$('managed-gear-search').value='';renderPicker();
    $('managed-gear-menu').hidden=false;
    root.document.querySelector(`[data-managed-picker="${index}"]`).setAttribute('aria-expanded','true');
    positionPicker();if(pickerSlot!==null)$('managed-gear-search').focus();
  }
  function selectGear(key){
    if(pickerSlot===null||packet?.running||busy||!draft?.auto_equip.enabled)return;
    const row=slots().find(row=>String(row.index??row.value??row.id)===pickerSlot);
    if(!row||key&&key!==disabledChoice&&!slotEquipment(catalog().equipment,row.slot,character()).some(gear=>gear.key===key))return;
    const previous=readForm(),next=withSlotChoice(previous,Number(pickerSlot),key);
    if(JSON.stringify(previous)!==JSON.stringify(next)){draft=next;markDirty();slotSignature='';renderSlots();}
    closePicker(true);renderDependencies();renderCapabilities();
  }
  function renderPages(){
    const rows=packet?.warehouse_pages||[],ready=connected&&packet?.warehouse_ready===true,signature=JSON.stringify([rows,ready,draft?.cleanup]);if(signature===pageSignature)return;pageSignature=signature;
    for(const kind of ['equipment','rune','gem']){
      const choices=storageTools.pageChoices(rows,draft?.cleanup[kind+'_pages']||[],ready);
      $('managed-'+kind+'-pages').innerHTML=choices.map(row=>{
        const label=row.status==='available'?`${row.free} 空`:row.status==='locked'?'未解锁':'待读取';
        const title=row.status==='available'?`剩余 ${row.free} / ${row.capacity} 格`:row.status==='locked'?'该页尚未解锁；保留选择，解锁后自动使用。也可取消并选择其他页。':'连接后读取实际仓库权限。';
        return `<label class="${row.status==='available'?'':'storage-page-unavailable'}" title="${esc(title)}"><input type="checkbox" data-managed-pages="${kind}" value="${row.index}" ${row.selected?'checked':''}><span>${esc(row.name)}</span><small>${esc(label)}</small></label>`;
      }).join('')||'<small class="managed-pages-empty">连接后读取仓库页签</small>';
    }
  }
  function renderMaps(){
    for(const id of ['managed-difficulty','managed-difficulty-two'])for(const option of $(id).options){
      if(option.value==='current'){option.textContent='沿用启动时当前难度'+(difficultyNames[packet?.current_difficulty]?' · '+difficultyNames[packet.current_difficulty]:'');continue;}
      const native=packet?.difficulties?.find(row=>row.id===option.value);
      option.disabled=native?.unlocked===false;
      option.textContent=difficultyNames[option.value]+(native?.unlocked===false?' · 未解锁':'');
    }
    const target=packet?.automatic_start,tier=difficultyNames[target?.difficulty],name=target?availableMaps(packet,draft,target.difficulty).find(r=>String(mapId(r))===String(target.dungeon_id))?.name:null;
    $('managed-push-target').textContent=target?`${tier} · ${name||target.dungeon_id}`:connected?'等待读取已解锁关卡':'连接后读取';
    const progress=$('managed-farm-progress'),showProgress=(packet?.running||packet?.paused)&&packet?.settings?.farming?.enabled;
    progress.hidden=!showProgress;
    if(showProgress){
      const liveName=availableMaps(packet,draft,packet.target_difficulty).find(r=>String(mapId(r))===String(packet.target_dungeon))?.name||packet.target_dungeon;
      const repeat=packet.settings.farming.mode==='repeat'&&packet.repeat_maps?.[packet.repeat_index];
      progress.textContent=`当前目标：${difficultyNames[packet.target_difficulty]||'当前难度'} · ${liveName}${repeat?` · 图 ${packet.repeat_index+1} 本轮已完成 ${packet.repeat_completed} / ${repeat.runs} 局`:''}`;
    }
    const signature=JSON.stringify([packet?.maps_by_difficulty,packet?.maps,draft?.farming.repeat_maps,connected,packet?.control_error]);if(signature===mapSignature)return;mapSignature=signature;
    for(const [i,id] of [[0,'managed-map'],[1,'managed-map-two']]){
      const point=draft?.farming.repeat_maps[i],selected=point?.dungeon_id,rows=availableMaps(packet,draft,point?.difficulty||(i===0?draft.farming.difficulty:'current')),unknown=selected!==null&&selected!==undefined&&!rows.some(row=>String(mapId(row))===String(selected));
      $(id).innerHTML='<option value="">'+(rows.length?'请选择关卡':!connected?'连接后读取关卡':packet?.control_error?'关卡暂不可读':'正在读取关卡…')+'</option>'+(unknown?`<option value="${esc(selected)}" selected>关卡 ${esc(selected)} · 待读取</option>`:'')+rows.map(row=>`<option value="${esc(mapId(row))}" ${String(mapId(row))===String(selected)?'selected':''} ${row.automation_supported===false||row.unlocked===false?'disabled':''}>${esc(row.name||row.label||'关卡 '+mapId(row))}${row.unlocked===false?' · 未解锁':''}</option>`).join('');
    }
  }
  function writeForm(){
    if(!draft)return;
    $('managed-rule-monitoring').checked=draft.background.rule_monitoring;$('managed-inventory-automation').checked=draft.background.inventory_automation;
    $('managed-auto-equip').checked=draft.auto_equip.enabled;$('managed-farming').checked=draft.farming.enabled;$('managed-farm-mode').value=draft.farming.mode;$('managed-free-threshold').value=draft.farming.free_threshold;
    $('managed-difficulty').value=draft.farming.difficulty;
    $('managed-repeat-two').checked=draft.farming.repeat_maps.length===2;
    $('managed-repeat-count').value=draft.farming.repeat_maps[0]?.runs||1;
    $('managed-difficulty-two').value=draft.farming.repeat_maps[1]?.difficulty||'current';
    $('managed-repeat-count-two').value=draft.farming.repeat_maps[1]?.runs||1;
    for(const kind of ['rune','gem'])$('managed-'+kind+'-action').value=draft.cleanup[kind+'_action'];
    for(const [key] of disposalRarities)for(const field of ['action','fallback'])$(`managed-equipment-${key}-${field}`).value=draft.cleanup.equipment_policies[key][field];
    renderSlots();renderMaps();renderPages();renderDependencies();
  }
  function renderDependencies(){
    const running=!!packet?.running;
    fieldIds.forEach(id=>{$(id).disabled=running||busy;});
    for(const id of farmFields)$(id).disabled=running||busy||!$('managed-farming').checked;
    root.document.querySelectorAll('[data-managed-slot]').forEach(input=>input.disabled=running||busy||!$('managed-auto-equip').checked);
    root.document.querySelectorAll('[data-managed-picker]').forEach(input=>input.disabled=running||busy||!$('managed-auto-equip').checked);
    if(running||busy||!$('managed-auto-equip').checked)closePicker();
    for(const kind of ['equipment','rune','gem'])root.document.querySelectorAll(`[data-managed-pages="${kind}"]`).forEach(input=>input.disabled=running||busy||(kind==='gem'&&$('managed-gem-action').value!=='store'));
    root.document.querySelectorAll('[data-managed-policy], [data-managed-preset]').forEach(input=>input.disabled=running||busy);
    for(const id of ['managed-save','managed-growth-save','managed-shop-save'])$(id).disabled=running||busy||!draft;
    $('managed-reset-draft').disabled=running||busy||!dirty;
    const push=$('managed-farm-mode').value==='push',two=$('managed-repeat-two').checked;
    $('managed-push-preview').hidden=!push;$('managed-repeat-fields').hidden=push;$('managed-repeat-second').hidden=!two;
    root.document.querySelector('.managed-repeat-count-label').hidden=!two;
    $('managed-farm-note').textContent=push?'从最高已解锁难度的最后一张已解锁图开始；通关前进一关，失败后退一关，上一关通关后再次挑战。普通通关后进入噩梦，噩梦通关后进入炼狱。':two?'依次打满图 1、图 2 的局数后循环；胜负结算各计一局，途中回城整理不计局数。':'重复进入选定关卡；背包空格不足时先回城整理，再继续刷图。';
    root.ManagedGrowthUI?.render(draft,packet?.progression_catalog,packet?.progression_state,running||busy,(next,renderNow=true)=>{
      draft={...readForm(),...next};markDirty();if(renderNow){renderDependencies();renderCapabilities();}
    },connected);
    renderControls();
  }
  function renderControls(){
    const controls=controlState(packet,draft||normalizeSettings(),connected,busy);
    $('managed-stop').textContent=controls.stopLabel;$('managed-stop').title=packet?.finishing?'立即中止整理，等待当前已提交动作结束。':'返回主城，整理背包、马车和地面奖励后停止。';
    $('managed-start').disabled=!controls.canStart;$('managed-start').hidden=!!packet?.running;$('managed-start').textContent=packet?.paused?'继续托管':'启动托管';
    $('managed-pause').hidden=!packet?.running;$('managed-pause').disabled=!controls.canPause;$('managed-stop').disabled=!controls.canStop;$('managed-reset-stats').disabled=!controls.canReset;
    if(!connected)$('managed-start').title='请先连接游戏';
    else if(controls.missing.length)$('managed-start').title='尚未通过验证：'+controls.missing.map(key=>capabilityNames[key]).join('、');
    else $('managed-start').title=packet?.start_disabled_reason||controls.configurationError||'按保存的设置开始托管';
  }
  function renderCapabilities(){
    const requirements=requiredCapabilities(draft||normalizeSettings());
    $('managed-test-notice').hidden=packet?.capabilities?.test_mode!==true;
    $('managed-capabilities').innerHTML=requirements.map(key=>{const value=packet?.capabilities?.[key],available=capabilityAvailable(value),testing=available&&value?.test_enabled===true,reason=typeof value==='object'?value?.reason:'';return `<span class="managed-capability ${available?'available':'unavailable'}" title="${esc(reason||(available?'已验证可用':'尚未验证，启动前需要完成适配'))}"><i></i>${esc(capabilityNames[key])}<small>${testing?'测试可用':available?'可用':'待验证'}</small></span>`;}).join('');
  }
  function renderStats(){
    const signature=JSON.stringify(packet?.stats||{});if(signature===statsSignature)return;statsSignature=signature;
    const data=statistics(packet?.stats);$('managed-loot-total').textContent=data.total.toLocaleString('zh-CN')+' 件';
    $('managed-equipment-stats').innerHTML=data.equipment.map(row=>`<tr class="managed-rarity-${row.key}"><td>${esc(row.name)}</td><td>${row.count.toLocaleString('zh-CN')}</td><td title="${row.estimatedSold||row.estimatedSalvaged?'包含按稳定马车策略估算的低品质处置数量':'已核验的助手回执、游戏马车记录或系统日志'}"><span>${row.estimatedSold?'≈ ':''}${row.sold.toLocaleString('zh-CN')}</span><small> / </small><span>${row.estimatedSalvaged?'≈ ':''}${row.salvaged.toLocaleString('zh-CN')}</span></td></tr>`).join('');
    for(const [kind,rows,count] of [['rune',data.runes,data.runeCount],['gem',data.gems,data.gemCount]]){
      $('managed-'+kind+'-total').textContent=count.toLocaleString('zh-CN')+' 个';
      $('managed-'+kind+'-stats').innerHTML=rows.length?rows.map(row=>`<div data-rarity="${kind==='rune'&&Number.isInteger(row.rarity)?row.rarity:''}"><span title="${esc(row.name||row.key)}">${esc(row.name||row.key||'未命名物品')}${row.level?` <small>Lv.${esc(row.level)}</small>`:''}</span><strong>${row.count.toLocaleString('zh-CN')}</strong><small>已出售 ${Math.max(0,safeNumber(row.sold)).toLocaleString('zh-CN')} · 已存入 ${Math.max(0,safeNumber(row.stored)).toLocaleString('zh-CN')}</small></div>`).join(''):'<p class="managed-stat-empty">尚无'+(kind==='rune'?'符文':'宝石')+'掉落</p>';
    }
    if(packet?.stats?.note)$('managed-stats-note').textContent=packet.stats.note;
  }
  function renderHistory(){
    const rows=packet?.history||[],signature=JSON.stringify(rows);if(signature===historySignature)return;historySignature=signature;
    $('managed-history-count').textContent=rows.length+' 条';
    $('managed-history-list').innerHTML=rows.length?[...rows].reverse().slice(0,50).map(row=>{
      const time=row.time||row.timestamp,date=new Date(time),label=time?(Number.isNaN(date.getTime())?String(time):date.toLocaleTimeString('zh-CN',{hour12:false})):'';
      return `<li class="${row.level==='error'?'managed-history-error':''}"><time>${esc(label)}</time><p>${esc(row.message||row.text||'')}</p></li>`;
    }).join(''):'<li class="managed-history-empty">尚未启动托管</li>';
  }
  function renderTime(){const stats=packet?.stats||{},extra=packet?.running?Math.max(0,(Date.now()-receivedAt)/1000):0;$('managed-elapsed').textContent=duration(safeNumber(stats.elapsed_seconds??packet?.elapsed_seconds)+extra);}
  function render(){
    $('managed-phase').textContent=packet?.finishing?'结束中 · '+phaseLabel():phaseLabel();$('managed-message').textContent=packet?.message||(!connected?'请先连接游戏，读取关卡和仓库页签。':'配置托管策略后，点击启动。');
    $('managed-status-dot').className='managed-status-dot '+(packet?.running?'running':packet?.phase==='error'||packet?.phase==='blocked'?'error':'');
    const error=packet?.error||packet?.start_disabled_reason||(draft?.farming.enabled&&connected&&packet?.control_error);if(error){$('managed-error').textContent=String(error);$('managed-error').hidden=false;}
    renderMaps();renderPages();renderSlots();renderDependencies();renderCapabilities();renderStats();renderHistory();renderTime();
  }
  function applyPacket(value){
    if(!value||typeof value!=='object')return;
    const next=value.managed||value;packet={...next,stats:next.stats||next.statistics,message:next.message||next.status,paused:next.paused??next.phase==='paused'};receivedAt=Date.now();
    if(!dirty&&packet.settings){draft=normalizeSettings(packet.settings);writeForm();}
    if(!draft){draft=normalizeSettings();writeForm();}render();
  }
  async function refresh(){
    if(!context||polling)return;polling=true;
    try{applyPacket(await context.api('managed'));if(!packet?.error&&!packet?.start_disabled_reason&&!(draft?.farming.enabled&&connected&&packet?.control_error))$('managed-error').hidden=true;}
    catch(error){report(error);}finally{polling=false;}
  }
  async function save(){
    draft=readForm();const error=validateSettings(draft);if(error)throw new Error(error);
    const value=await context.api('managed/settings',{settings:clone(draft)});markDirty(false);applyPacket(value);context.toast?.('托管设置已保存');return true;
  }
  async function runAction(action){
    if(!context||busy&&!['pause','stop'].includes(action))return;
    const ticket=++actionVersion;busy=true;renderDependencies();$('managed-error').hidden=true;
    try{
      if(action==='save')await save();
      if(action==='start'){
        draft=readForm();const error=validateSettings(draft);if(error)throw new Error(error);
        if(!draft.auto_equip.enabled&&!draft.farming.enabled&&!growthTools.enabled(draft))throw new Error('请至少启用一项托管功能。');
        if(dirty)await save();
        if(ticket!==actionVersion)return;
        const c=draft.cleanup,disposition=dispositionNames;
        const growthNotice=[draft.progression.talents_enabled?'按当前职业的目标逐点学习天赋，不重置已有天赋。':'',draft.progression.skills_enabled?'到达设定等级并解锁后切换目标技能组合。':'',draft.life_skills.enabled?`按优先顺序学习生活技能，随后补满；至少保留 ${draft.life_skills.gold_reserve} 金币。`:'',draft.merchant.enabled?'灵魂碎片达到实际容量的回城比例后，整理奖励并按部位比例消费；新购买的装备重新筛选整理。':''].filter(Boolean).join('\n');
        const cleanupNotice=(draft.farming.enabled||draft.merchant.enabled)?`不符合规则的装备按品质处理：\n${equipmentSummary(c)}。\n仓库满时清理所选页的未锁定垃圾：\n${equipmentSummary(c,true)}。\n普通符文：${disposition[c.rune_action]}；宝石：${disposition[c.gem_action]}。出售和分解无法撤回，强化和宝石不自动返还。神圣、黑雾装备及套装、宏伟符文必须收纳；已锁定、符合规则与待核验装备保留。神圣装备禁止自动穿戴，主城奖励未收完不得入图。`:draft.auto_equip.enabled?'按固定单体 Boss 战力更换更高战力的装备。神圣装备禁止自动穿戴。未指定暗金时允许其他品质；指定但尚未穿上时允许普通、优秀、稀有装备过渡，穿上后只比较同名装备。不自动转移宝石。':'';
        const confirmed=await context.confirmAction?.('启动托管？',[growthNotice,cleanupNotice].filter(Boolean).join('\n\n'),'启动托管',false);
        if(confirmed===false||ticket!==actionVersion)return;
        const result=await context.api('managed/run',{enabled:true});if(ticket===actionVersion)applyPacket(result);
      }
      if(action==='pause'){const result=await context.api('managed/run',{enabled:false});if(ticket===actionVersion)applyPacket(result);}
      if(action==='stop'){const result=await context.api(packet?.finishing?'managed/abort':'managed/stop',{});if(ticket===actionVersion)applyPacket(result);}
      if(action==='reset'){
        const confirmed=await context.confirmAction?.('清空本次统计？','只清空托管的累计掉落和本次流程记录，本机物品操作日志保留。','清空统计',false);
        if(confirmed===false)return;applyPacket(await context.api('managed/reset',{}));
      }
    }catch(error){if(ticket===actionVersion)report(error);}finally{if(ticket===actionVersion){busy=false;renderDependencies();renderCapabilities();}}
  }
  function init(options){
    context=options;if(initialized)return;initialized=true;root.ManagedGrowthUI?.init();draft=normalizeSettings();writeForm();render();
    $('managed-page').addEventListener('change',event=>{
      if(event.target.matches('input,select')&&!event.target.closest('#managed-growth')){
        draft=readForm();
        if(['managed-difficulty','managed-difficulty-two','managed-repeat-two'].includes(event.target.id)){
          const index=event.target.id==='managed-difficulty-two'?1:0,point=draft.farming.repeat_maps[index],selected=point&&availableMaps(packet,draft,point.difficulty).find(row=>String(mapId(row))===String(point.dungeon_id));
          if(point&&(selected?.automation_supported===false||selected?.unlocked===false)){point.dungeon_id=null;if(index===0)draft.farming.dungeon_id=null;}
          mapSignature='';renderMaps();
        }
        markDirty();renderDependencies();renderCapabilities();
      }
    });
    $('managed-free-threshold').addEventListener('input',()=>{draft=readForm();markDirty();});
    for(const id of ['managed-repeat-count','managed-repeat-count-two'])$(id).addEventListener('input',()=>{draft=readForm();markDirty();});
    for(const [id,action] of [['managed-save','save'],['managed-growth-save','save'],['managed-shop-save','save'],['managed-start','start'],['managed-pause','pause'],['managed-stop','stop'],['managed-reset-stats','reset']])$(id).addEventListener('click',()=>runAction(action));
    $('managed-refresh').addEventListener('click',refresh);
    $('managed-slot-locks').addEventListener('click',event=>{const button=event.target.closest('[data-managed-picker]');if(button)openPicker(button.dataset.managedPicker);});
    $('managed-gear-search').addEventListener('input',renderPicker);
    $('managed-gear-choices').addEventListener('click',event=>{const button=event.target.closest('[data-managed-choice]');if(button)selectGear(button.dataset.managedChoice);});
    root.document.addEventListener('pointerdown',event=>{
      if(pickerSlot!==null&&!event.target.closest('#managed-gear-menu, [data-managed-picker]'))closePicker();
    });
    root.document.addEventListener('focusin',event=>{
      if(pickerSlot!==null&&!event.target.closest('#managed-gear-menu, [data-managed-picker]'))closePicker();
    });
    root.document.addEventListener('keydown',event=>{
      if(pickerSlot!==null&&event.key==='Escape'){event.preventDefault();closePicker(true);}
    });
    $('managed-gear-menu').addEventListener('keydown',event=>{
      const choices=[...$('managed-gear-choices').querySelectorAll('[data-managed-choice]')];
      if(!choices.length)return;
      const index=choices.indexOf(root.document.activeElement);
      if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)&&!(event.target.id==='managed-gear-search'&&['Home','End'].includes(event.key))){
        event.preventDefault();
        const target=event.key==='Home'?0:event.key==='End'?choices.length-1:event.key==='ArrowDown'?(index+1)%choices.length:index<0?choices.length-1:(index-1+choices.length)%choices.length;
        choices[target].focus();
      }
    });
    $('managed-lock-details').addEventListener('toggle',()=>{if(!$('managed-lock-details').open)closePicker();});
    root.addEventListener('resize',positionPicker);
    root.document.addEventListener('scroll',positionPicker,true);
    root.document.querySelectorAll('[data-managed-preset]').forEach(button=>button.addEventListener('click',()=>{
      if(packet?.running||busy)return;draft=equipmentPreset(readForm(),button.dataset.managedPreset);markDirty();pageSignature='';writeForm();renderCapabilities();
    }));
    $('managed-reset-draft').addEventListener('click',()=>{draft=normalizeSettings(packet?.settings);markDirty(false);slotSignature='';pageSignature='';mapSignature='';writeForm();render();});
    root.setInterval(()=>{renderTime();if(active||packet?.running)refresh();},1500);
  }
  function setConnection(value){
    connected=!!value;
    // Reconnecting must wait for a fresh character snapshot, rather than
    // temporarily resurrecting the previous connection's profession.
    if(!connected&&packet)packet={...packet,progression_state:{available:false,reason:'连接游戏后读取成长状态。'}};
    renderPages();renderDependencies();renderSlots();renderControls();
  }
  function setCharacter(value){currentCharacter={available:value?.available===true,class_mask:value?.class_mask};renderSlots();}
  function setActive(value){active=!!value;if(active)refresh();else closePicker();}
  root.ManagedModeUI={init,refresh,applyPacket,setConnection,setCharacter,setActive,isDirty:()=>dirty,helpers};
})(typeof window!=='undefined'?window:globalThis);
