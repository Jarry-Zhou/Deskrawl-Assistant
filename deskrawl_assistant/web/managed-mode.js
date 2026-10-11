'use strict';
(function(root){
  const storageTools=typeof module!=='undefined'&&module.exports?require('./automation-tools.js'):root.AutomationTools;
  const phaseNames={idle:'尚未启动',stopped:'已停止',paused:'已暂停',starting:'准备托管',farming:'刷图中',pushing:'推图中',travel:'进入关卡',returning:'回城中',scanning:'扫描奖励',equipping:'自动换装',cleanup:'整理奖励',collecting:'收取马车 / 地面物品',opening_chests:'开启宝箱',waiting:'等待处理',blocked:'已暂停 · 需要处理',error:'已停止 · 操作异常'};
  const rarityNames=[['divine','神圣'],['black_mist','黑雾传说'],['ancient','远古传说'],['legendary','普通传说'],['rare','稀有'],['uncommon','优秀'],['normal','普通']];
  const disposalRarities=rarityNames.slice(2),dispositionNames={store:'放入仓库',sell:'出售',salvage:'分解'};
  const capabilityNames={transfer:'物品转移',lock:'装备保护',equip:'后台换装',travel:'回城 / 进入关卡',difficulty:'主城切换难度',sell:'出售',salvage:'分解',chests:'开启宝箱',ground_pickup:'地面拾取'};
  const difficultyNames={Normal:'普通',Nightmare:'噩梦',Inferno:'炼狱'};
  const disabledChoice='__disabled_slot__';
  const clone=value=>JSON.parse(JSON.stringify(value));
  const safeNumber=(value,fallback=0)=>Number.isFinite(Number(value))&&value!==null&&value!==''?Number(value):fallback;
  const pageIds=values=>[...new Set((Array.isArray(values)?values:[]).map(Number).filter(n=>Number.isInteger(n)&&n>0))].sort((a,b)=>a-b);
  const oneOf=(value,choices,fallback)=>choices.includes(value)?value:fallback;
  function normalizeSettings(value={}){
    const eq=value.auto_equip||{},farm=value.farming||{},cleanup=value.cleanup||{},background=value.background||{};
    return {background:{rule_monitoring:background.rule_monitoring!==false,inventory_automation:background.inventory_automation!==false},auto_equip:{enabled:!!eq.enabled,minimum_delta:safeNumber(eq.minimum_delta,1),slot_locks:{...(eq.slot_locks||{})},disabled_slots:Array.isArray(eq.disabled_slots)?[...eq.disabled_slots]:[]},
      farming:{enabled:!!farm.enabled,mode:oneOf(farm.mode,['repeat','push'],'repeat'),dungeon_id:farm.dungeon_id??null,difficulty:oneOf(farm.difficulty,['current','Normal','Nightmare','Inferno'],'current'),progression:Array.isArray(farm.progression)?clone(farm.progression):[],free_threshold:safeNumber(farm.free_threshold,4)},
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
    if(f.enabled&&(f.dungeon_id===null||f.dungeon_id===undefined||f.dungeon_id===''))return '请选择复刷或推图的起始关卡。';
    if(!Number.isInteger(f.free_threshold)||f.free_threshold<1||f.free_threshold>2048)return '回城阈值须为 1 至 2048 的整数。';
    if(!c.equipment_pages.length)return '请选择装备存放页，黑雾 / 神圣与符合规则的装备需要保留空间。';
    if(!c.rune_pages.length)return '请勾选符文存放页，套装与宏伟符文必须收纳。';
    if(c.gem_action==='store'&&!c.gem_pages.length)return '宝石选择放入仓库时，需要至少勾选一个仓库页。';
    return '';
  }
  function capabilityAvailable(value){return value===true||!!(value&&typeof value==='object'&&(value.native_verified!==false||value.test_enabled===true)&&(value.available===true||(value.available===undefined&&value.supported===true)));}
  function requiredCapabilities(settings){
    const c=settings.cleanup,keys=[];
    if(settings.farming.enabled)keys.push('transfer','lock','chests','ground_pickup');
    else if(settings.auto_equip.enabled)keys.push('transfer');
    if(settings.auto_equip.enabled)keys.push('equip');
    if(settings.background.rule_monitoring&&!keys.includes('lock'))keys.push('lock');
    if(settings.farming.enabled){keys.push('travel');if(settings.farming.mode==='push'||settings.farming.difficulty!=='current')keys.push('difficulty');}
    const actions=settings.farming.enabled?[...Object.values(normalizeSettings(settings).cleanup.equipment_policies).flatMap(p=>[p.action,p.fallback]),c.rune_action,c.gem_action]:[];
    if(actions.includes('sell'))keys.push('sell');if(actions.includes('salvage'))keys.push('salvage');return keys;
  }
  function controlState(packet,settings,connected,busy=false){
    const running=!!packet?.running,phase=packet?.phase||'idle';
    const missing=requiredCapabilities(settings).filter(key=>!capabilityAvailable(packet?.capabilities?.[key]));
    const configurationError=validateSettings(settings)||(!settings.auto_equip.enabled&&!settings.farming.enabled?'请至少启用自动换装或自动刷图。':'');
    const blocked=packet?.can_start===false||missing.length>0||!!configurationError||(settings.farming.enabled&&packet?.control_available===false);
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
  function availableMaps(packet,settings){return packet?.maps_by_difficulty?.[selectedDifficulty(settings,packet)]||packet?.maps||[];}
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
  const fieldIds=['managed-rule-monitoring','managed-inventory-automation','managed-auto-equip','managed-farming','managed-farm-mode','managed-difficulty','managed-map','managed-free-threshold','managed-rune-action','managed-gem-action'];
  const catalog=()=>context?.catalog||{};
  const maps=()=>availableMaps(packet,draft||normalizeSettings());
  const mapId=row=>row.id??row.dungeon_id;
  const phaseLabel=()=>packet?.phase_label||phaseNames[packet?.phase]||packet?.phase||'尚未启动';
  function markDirty(value=true){dirty=value;$('managed-draft-state').textContent=dirty?'有未保存的托管设置':'设置已保存';context?.onDirty?.();}
  function report(error){$('managed-error').textContent=error?.message||String(error);$('managed-error').hidden=false;context?.toast?.($('managed-error').textContent,true);}
  function readForm(){
    const next=normalizeSettings(draft||{}),f=next.farming,c=next.cleanup;
    next.background.rule_monitoring=$('managed-rule-monitoring').checked;next.background.inventory_automation=$('managed-inventory-automation').checked;
    next.auto_equip.enabled=$('managed-auto-equip').checked;next.auto_equip.slot_locks={};
    root.document.querySelectorAll('[data-managed-slot]').forEach(select=>{if(select.value)next.auto_equip.slot_locks[select.dataset.managedSlot]=select.value;});
    f.enabled=$('managed-farming').checked;f.mode=$('managed-farm-mode').value;f.free_threshold=Number($('managed-free-threshold').value);
    f.difficulty=$('managed-difficulty').value;
    const found=availableMaps(packet,next).find(row=>String(mapId(row))===$('managed-map').value);f.dungeon_id=found?mapId(found):$('managed-map').value||null;
    if(f.mode==='push'){
      const declared=found?.progression||packet?.progression;
      if(Array.isArray(declared)){const ids=declared.map(row=>typeof row==='object'?mapId(row):row),index=ids.findIndex(id=>String(id)===String(f.dungeon_id));f.progression=index>=0?ids.slice(index):ids;}
      // The backend supplies an explicit route. Do not infer map progression from names.
    }else f.progression=[];
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
    for(const option of $('managed-difficulty').options){
      if(option.value==='current'){option.textContent='沿用启动时当前难度'+(difficultyNames[packet?.current_difficulty]?' · '+difficultyNames[packet.current_difficulty]:'');continue;}
      const native=packet?.difficulties?.find(row=>row.id===option.value);
      option.disabled=native?.unlocked===false;
      option.textContent=difficultyNames[option.value]+(native?.unlocked===false?' · 未解锁':'');
    }
    const signature=JSON.stringify([maps(),draft?.farming.dungeon_id,connected,packet?.control_error]);if(signature===mapSignature)return;mapSignature=signature;
    const selected=draft?.farming.dungeon_id,unknown=selected!==null&&selected!==undefined&&!maps().some(row=>String(mapId(row))===String(selected));
    $('managed-map').innerHTML='<option value="">'+(maps().length?'请选择关卡':!connected?'连接后读取关卡':packet?.control_error?'关卡暂不可读':'正在读取关卡…')+'</option>'+(unknown?`<option value="${esc(selected)}" selected>关卡 ${esc(selected)} · 待读取</option>`:'')+maps().map(row=>`<option value="${esc(mapId(row))}" ${String(mapId(row))===String(selected)?'selected':''} ${row.automation_supported===false?'disabled':''}>${esc(row.name||row.label||'关卡 '+mapId(row))}${row.unlocked===false?' · 未解锁':''}${row.automation_supported===false?' · 暂不支持':''}</option>`).join('');
  }
  function writeForm(){
    if(!draft)return;
    $('managed-rule-monitoring').checked=draft.background.rule_monitoring;$('managed-inventory-automation').checked=draft.background.inventory_automation;
    $('managed-auto-equip').checked=draft.auto_equip.enabled;$('managed-farming').checked=draft.farming.enabled;$('managed-farm-mode').value=draft.farming.mode;$('managed-free-threshold').value=draft.farming.free_threshold;
    $('managed-difficulty').value=draft.farming.difficulty;
    for(const kind of ['rune','gem'])$('managed-'+kind+'-action').value=draft.cleanup[kind+'_action'];
    for(const [key] of disposalRarities)for(const field of ['action','fallback'])$(`managed-equipment-${key}-${field}`).value=draft.cleanup.equipment_policies[key][field];
    renderSlots();renderMaps();renderPages();renderDependencies();
  }
  function renderDependencies(){
    const running=!!packet?.running;
    fieldIds.forEach(id=>{$(id).disabled=running||busy;});
    for(const id of ['managed-farm-mode','managed-difficulty','managed-map','managed-free-threshold'])$(id).disabled=running||busy||!$('managed-farming').checked;
    root.document.querySelectorAll('[data-managed-slot]').forEach(input=>input.disabled=running||busy||!$('managed-auto-equip').checked);
    root.document.querySelectorAll('[data-managed-picker]').forEach(input=>input.disabled=running||busy||!$('managed-auto-equip').checked);
    if(running||busy||!$('managed-auto-equip').checked)closePicker();
    for(const kind of ['equipment','rune','gem'])root.document.querySelectorAll(`[data-managed-pages="${kind}"]`).forEach(input=>input.disabled=running||busy||(kind==='gem'&&$('managed-gem-action').value!=='store'));
    root.document.querySelectorAll('[data-managed-policy], [data-managed-preset]').forEach(input=>input.disabled=running||busy);
    $('managed-save').disabled=running||busy||!draft;$('managed-reset-draft').disabled=running||busy||!dirty;
    const push=$('managed-farm-mode').value==='push';$('managed-map-label').textContent=push?'推图起始关卡':'复刷关卡';
    $('managed-farm-note').textContent=push?'按 普通 → 噩梦 → 炼狱 推进；每档最后一关通关后，回城整理并切换到下一难度的第一关。打不过时回到上一个已通关的难度与关卡复刷。':'按选定难度重复进入关卡；切换难度和背包空格不足时先回城整理，再继续刷图。';
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
      $('managed-'+kind+'-stats').innerHTML=rows.length?rows.map(row=>`<div><span title="${esc(row.name||row.key)}">${esc(row.name||row.key||'未命名物品')}${row.level?` <small>Lv.${esc(row.level)}</small>`:''}</span><strong>${row.count.toLocaleString('zh-CN')}</strong><small>已出售 ${Math.max(0,safeNumber(row.sold)).toLocaleString('zh-CN')} · 已存入 ${Math.max(0,safeNumber(row.stored)).toLocaleString('zh-CN')}</small></div>`).join(''):'<p class="managed-stat-empty">尚无'+(kind==='rune'?'符文':'宝石')+'掉落</p>';
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
        if(!draft.auto_equip.enabled&&!draft.farming.enabled)throw new Error('请至少启用自动换装或自动刷图。');
        if(dirty)await save();
        if(ticket!==actionVersion)return;
        const c=draft.cleanup,disposition=dispositionNames;
        const confirmed=await context.confirmAction?.('启动托管？',draft.farming.enabled?`不符合规则的装备按品质处理：\n${equipmentSummary(c)}。\n仓库满时清理所选页的未锁定垃圾：\n${equipmentSummary(c,true)}。\n普通符文：${disposition[c.rune_action]}；宝石：${disposition[c.gem_action]}。出售和分解无法撤回，强化和宝石不自动返还。神圣、黑雾装备及套装、宏伟符文必须收纳；已锁定、符合规则与待核验装备保留。神圣装备禁止自动穿戴，主城奖励未收完不得入图。`:'只监控换装，按固定单体 Boss 战力更换更高战力的装备。神圣装备禁止自动穿戴。未指定暗金时允许其他品质；指定但尚未穿上时允许普通、优秀、稀有装备过渡，穿上后只比较同名装备。不自动转移宝石。','启动托管',false);
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
    context=options;if(initialized)return;initialized=true;draft=normalizeSettings();writeForm();render();
    $('managed-page').addEventListener('change',event=>{
      if(event.target.matches('input,select')){
        draft=readForm();
        if(event.target.id==='managed-difficulty'){
          const selected=maps().find(row=>String(mapId(row))===String(draft.farming.dungeon_id));
          if(selected?.automation_supported===false||selected?.unlocked===false)draft.farming.dungeon_id=null;
          mapSignature='';renderMaps();
        }
        markDirty();renderDependencies();renderCapabilities();
      }
    });
    $('managed-free-threshold').addEventListener('input',()=>{draft=readForm();markDirty();});
    for(const [id,action] of [['managed-save','save'],['managed-start','start'],['managed-pause','pause'],['managed-stop','stop'],['managed-reset-stats','reset']])$(id).addEventListener('click',()=>runAction(action));
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
  function setConnection(value){connected=!!value;renderPages();renderDependencies();renderSlots();renderControls();}
  function setCharacter(value){currentCharacter={available:value?.available===true,class_mask:value?.class_mask};renderSlots();}
  function setActive(value){active=!!value;if(active)refresh();else closePicker();}
  root.ManagedModeUI={init,refresh,applyPacket,setConnection,setCharacter,setActive,isDirty:()=>dirty,helpers};
})(typeof window!=='undefined'?window:globalThis);
