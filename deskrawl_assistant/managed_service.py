"""Application bridge for the serial planner; no startup-time game operations."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import time

from .managed_mode import (ManagedMode, DEFAULT_SETTINGS, validate_settings, identity,
    run_record, DIFFICULTIES, equip_candidate_allowed, equipment_actions, equipment_policy)
from .models import ValidationError
from .rules import evaluate, DEFAULT_MIN_CONFIDENCE
from .native_memory import SnapshotChangedError
from .paths import RESOURCE_ROOT
from .item_protection import disposal_protection, mandatory_storage, town_rewards_clear
from .action_log import record


def required_capabilities(settings):
    required = {'transfer'}
    if settings['auto_equip']['enabled']: required.add('equip')
    if settings['background']['rule_monitoring']: required.add('lock')
    if settings['farming']['enabled']:
        required.update(('lock','travel','chests','ground_pickup'))
        if settings['farming']['mode']=='push' or settings['farming']['difficulty']!='current':
            required.add('difficulty')
        cleanup = settings['cleanup']
        required.update(equipment_actions(cleanup))
        required.update((cleanup['rune_action'],cleanup['gem_action']))
    return required - {'store'}


def available_capability(value):
    return value is True or (isinstance(value,dict) and value.get('available') is True
                            and (value.get('native_verified') is not False or value.get('test_enabled') is True))


def progression_from_catalog(maps, start):
    """Follow explicit prerequisites along the ordinary campaign, not name order."""
    current = str(start)
    by_id = {str(m.get('map_id',m.get('id'))):m for m in maps}
    if current not in by_id: raise ValidationError('目标关卡未收录。')
    route = [current]
    while True:
        following = [m for m in maps if str(m.get('prerequisite')) == current
                     and m.get('map_type') == 0 and m.get('supported') is not False
                     and not m.get('unavailable')]
        if len(following) != 1: break
        current = str(following[0].get('map_id',following[0].get('id')))
        if current in route: raise ValidationError('关卡前置关系存在循环。')
        route.append(current)
    return route


def campaign_route(maps, start, difficulty):
    if difficulty not in DIFFICULTIES: raise ValidationError('推图起始难度未确认。')
    first = progression_from_catalog(maps,start)
    result = [{'dungeon_id':key,'difficulty':difficulty} for key in first]
    ordinary = [m for m in maps if m.get('map_type')==0 and not m.get('unavailable') and m.get('supported') is not False]
    roots = [m for m in ordinary if not m.get('prerequisite')]
    if len(roots)!=1: raise ValidationError('普通关卡起始节点未唯一确认。')
    by_id = {str(m.get('map_id',m.get('id'))):m for m in ordinary}
    if any(str(key) not in by_id for key in first): return result
    root_id = roots[0].get('map_id',roots[0].get('id'))
    full = progression_from_catalog(ordinary,root_id)
    if str(first[-1])!=str(full[-1]): raise ValidationError('推图路线未连接到常规关卡终点。')
    for tier in DIFFICULTIES[DIFFICULTIES.index(difficulty)+1:]:
        result.extend({'dungeon_id':key,'difficulty':tier} for key in full)
    return result


class ManagedServiceMixin:
    def _init_managed(self):
        self.managed_config = self.config.with_name('managed-mode.json')
        self.managed = ManagedMode()
        self.managed_control = {}
        self.managed_capabilities = {}
        self.managed_history = []
        self.managed_started_at = None
        self.managed_started_clock = None
        self.managed_can_resume = False
        self.managed_stop_request = None
        self.managed_fast_followup = False
        self.managed_transition = None
        self.managed_elapsed = 0
        self.managed_config_error = ''
        self.managed_catalog = json.loads((RESOURCE_ROOT/'data/recommendation-catalog.json').read_text(encoding='utf-8'))['maps']
        try:
            if self.managed_config.exists():
                settings = validate_settings(json.loads(self.managed_config.read_text(encoding='utf-8')),
                                             equipment_keys=self.ui['equipment'],allow_empty_rune_pages=True)
                self._validate_slot_locks(settings)
                if not settings['cleanup']['rune_pages']:
                    # Keep every old preference editable; never silently replace
                    # a sale-policy configuration with the default preset.
                    self.managed.settings = settings
                    self.managed_config_error = '请补选符文存放页，用于强制收纳套装／宏伟符文；其他设置与原文件已保留。'
                else:
                    self.managed = ManagedMode(settings)
        except Exception as exc:
            self.managed_config_error = '托管配置未载入，原文件已保留：'+str(exc)

    def _validate_slot_locks(self, settings):
        from .character import EQUIPPED_SLOTS
        for slot,key in settings['auto_equip']['slot_locks'].items():
            meta = self.ui['equipment'].get(key,{})
            target = EQUIPPED_SLOTS[int(slot)]
            if target.startswith('Ring'): target = 'Ring'
            if not key.startswith('Legendary') or meta.get('slot') != target:
                raise ValidationError('指定暗金必须属于对应的穿戴部位。')

    def _managed_refresh_control(self):
        """Called only by a new assistant's read worker, never by an HTTP GET."""
        if not self.client.connected: return
        if not hasattr(self.client,'control_snapshot'): return
        try:
            value = self.client.control_snapshot()
            capabilities = self.client.managed_capabilities()
        except SnapshotChangedError:
            raise
        except Exception as exc:
            value = {'available':False,'reason':str(exc)}
            capabilities = {}
        with self.guard:
            self.managed_control = deepcopy(value)
            self.managed_capabilities = deepcopy(capabilities)

    def _managed_scene(self):
        control = deepcopy(self.managed_control)
        scene = control.get('scene',{})
        if not isinstance(scene,dict):
            scene = {'in_town':scene=='town','in_dungeon':scene=='combat'}
        scene.setdefault('available',control.get('available') is True)
        scene.setdefault('dungeon_id',control.get('map_id'))
        scene.setdefault('difficulty',control.get('difficulty'))
        for key in ('scene_changing','teleporting','dead','completion_visible'):
            scene.setdefault(key,control.get(key))
        run = deepcopy(run_record(scene.get('run',control.get('run'))))
        if run:
            run.setdefault('id',run.get('run_id'))
            run.setdefault('dungeon_id',run.get('map_id',scene['dungeon_id']))
        scene['run'] = run
        return scene

    def _managed_observation(self):
        # Every write is planned from the latest server-side read, not browser rows.
        snap = self.client.snapshot()
        self._publish(snap)
        self._managed_refresh_control()
        payload = self.state()
        raw = {(r.get('container'),r.get('slot_index')):r for c in snap.get('containers',{}).values() for r in c.get('slots',[])}
        observations = {(a.container,a.index):a.observation for a in self.adapter.adapt_snapshot(snap).items}
        for item in payload['items']:
            source = raw.get((item['container'],item['slot_index']),{})
            item['issues'] = list(source.get('issues',[]))
            item['item_type'] = source.get('item_type')
            item['item_class'] = source.get('item_class')
            item['base_rarity'] = source.get('base_rarity')
            if not item['is_equipment']:
                item['rarity'] = source.get('rarity',source.get('base_rarity'))
            item['rune_level'] = source.get('rune_level')
            item['rules_known'] = not bool(self.config_error)
            obs = observations.get((item['container'],item['slot_index']))
            if item['is_equipment']:
                known = bool(obs and obs.name_confidence >= DEFAULT_MIN_CONFIDENCE
                             and obs.lock_confidence >= DEFAULT_MIN_CONFIDENCE
                             and all(obs.groups_complete.get(g) is True for g in ('primary','secondary')))
                active_rules = [r for r in self._rules() if r.enabled and item['name_key'] in r.equipment_keys]
                if not known or not item['rules_known']:
                    item['review'] = True; item['rule_status'] = 'review'
                elif not active_rules:
                    item['matches'] = False; item['review'] = False; item['rule_status'] = 'no_rule'
                else:
                    evaluations = [evaluate(r,obs,self.catalog) for r in active_rules]
                    item['review'] = any(e.status=='uncertain' for e in evaluations) and not item['matches']
                    item['rule_status'] = 'review' if item['review'] else 'match' if item['matches'] else 'miss'
        carriage = deepcopy(self.managed_control.get('carriage',self._carriage_payload()))
        ground = deepcopy(self.managed_control.get('ground',{}))
        if isinstance(ground,list):
            ground = {'items':ground,'complete':self.managed_control.get('ground_complete') is True}
        ground.setdefault('complete',False)
        for container in (carriage,ground):
            for item in container.get('items',[]):
                name,kind = self._describe_item(item.get('name_key') or item.get('internal_name'))
                item.setdefault('name',name); item.setdefault('kind',kind)
        return {'complete':payload['complete'], 'session':snap.get('bridge_session'),
                'items':payload['items'],'counts':payload['counts'],'character':deepcopy(self.character),
                'scene':self._managed_scene(),'carriage':carriage,'ground':ground,
                'automation_settings':deepcopy(self.automation_settings),
                'loot_ledger':deepcopy(self.managed_control.get('loot_ledger', {})),
                'system_log':deepcopy(self.managed_control.get('system_log', {})),
                'storage':{'page_size':snap.get('transfer',{}).get('page_size'),
                           'allowed_indices':snap.get('transfer',{}).get('storage_indices',[])}}

    def managed_page(self):
        with self.guard:
            engine = self.managed.state()
            transfer = (self.snapshot or {}).get('transfer',{})
            capabilities = deepcopy(self.managed_capabilities)
            capabilities['transfer'] = transfer.get('available') is True
            capabilities['lock'] = bool(self.client.connected and (self.snapshot or {}).get('complete'))
            missing = [k for k in sorted(required_capabilities(engine['settings']))
                       if not available_capability(capabilities.get(k))]
            blocked = [f'{key}：'+(capabilities.get(key,{}).get('reason','尚未核验')
                       if isinstance(capabilities.get(key),dict) else '尚未核验') for key in missing]
            control_available = self.managed_control.get('available') is True
            control_error = (self.managed_control.get('reason') or '等待关卡与场景完整读取。') if not control_available else ''
            if engine['settings']['farming']['enabled'] and not control_available:
                blocked.append('关卡读取：'+control_error)
            size = transfer.get('page_size')
            indices = transfer.get('storage_indices',[])
            pages = []
            warehouse_ready = bool(self.client.connected and (self.snapshot or {}).get('complete') is True
                and transfer.get('available') is True and type(size) is int and size > 0
                and isinstance(indices,list) and all(type(n) is int and n>=0 for n in indices)
                and len(set(indices))==len(indices))
            if warehouse_ready:
                occupied = {r.get('slot_index') for r in (self.snapshot or {}).get('containers',{}).get('storage',{}).get('slots',[])}
                for index in sorted({n//size+1 for n in indices}):
                    slots = [n for n in indices if n//size+1==index]
                    pages.append({'index':index,'name':f'仓库第 {index} 页',
                                  'capacity':len(slots),'free':sum(n not in occupied for n in slots)})
            maps = deepcopy(self.managed_control.get('maps',[]))
            maps_by_difficulty = deepcopy(self.managed_control.get('maps_by_difficulty',{}))
            for row in [*maps,*(row for rows in maps_by_difficulty.values() for row in rows)]:
                row.setdefault('id',row.get('map_id')); row.setdefault('name',row.get('stage',row['id']))
                row['automation_supported'] = row.get('supported',True) and row.get('unlocked') is True
                try: row['progression'] = progression_from_catalog(self.managed_catalog,row['id'])
                except ValidationError: row['progression'] = []
            elapsed = self.managed_elapsed + (max(0,time.monotonic()-self.managed_started_clock) if self.managed_started_clock else 0)
            return {**engine,'running':engine['running'] and self.managed_stop_request is None,
                    'paused':self.managed_can_resume or engine['phase']=='paused',
                    'message':self.managed_config_error or engine['status'], 'stats':engine['statistics'],
                    'started_at':self.managed_started_at,'elapsed_seconds':elapsed,
                    'capabilities':capabilities,'can_start':not blocked and not self.managed_config_error,
                    'control_available':control_available,'control_error':control_error,
                    'blocked_reasons':blocked,'maps':maps,'warehouse_pages':pages,'warehouse_ready':warehouse_ready,
                    'maps_by_difficulty':maps_by_difficulty,'current_difficulty':self.managed_control.get('difficulty'),
                    'difficulties':deepcopy(self.managed_control.get('difficulties',[])),
                    'history':deepcopy(self.managed_history),'connected':self.client.connected}

    def save_managed(self, raw):
        with self.guard:
            if self.closed.is_set() or self.updating: raise ValidationError('助手正在退出或更新。')
            if self.managed.running or self.operation_kind=='managed': raise ValidationError('请先暂停托管再修改设置。')
            settings = validate_settings(raw,equipment_keys=self.ui['equipment'])
            self._validate_slot_locks(settings)
            farming = settings['farming']
            if farming['enabled']:
                difficulty = farming['difficulty'] if farming['difficulty']!='current' else self.managed_control.get('difficulty')
                farming['progression'] = (campaign_route(self.managed_catalog,farming['dungeon_id'],difficulty)
                    if farming['mode']=='push' and difficulty in DIFFICULTIES else
                    progression_from_catalog(self.managed_catalog,farming['dungeon_id']) if farming['mode']=='push' else [])
            self.managed_config.parent.mkdir(parents=True,exist_ok=True)
            temp = self.managed_config.with_suffix('.json.tmp')
            temp.write_text(json.dumps(settings,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            temp.replace(self.managed_config)
            self.managed.settings = settings
            self.managed_can_resume = False
            self.managed_config_error = ''
            self.revision += 1
            self.journal.append('settings','managed_settings_saved','保存托管模式设置',context={'settings':settings})
            return deepcopy(settings)

    def set_managed_running(self, enabled):
        if type(enabled) is not bool: raise ValidationError('托管开关必须为布尔值。')
        if not enabled:
            return self.stop_managed(pause=True)
        with self.guard:
            if self.closed.is_set() or self.updating: raise ValidationError('助手正在退出或更新。')
            if self.managed.running: return self.managed_page()
            if self.busy: raise ValidationError('请等待当前操作完成。')
            if not self.client.connected: raise ValidationError('请先连接游戏。')
            page = self.managed_page()
            if not page['can_start']: raise ValidationError('托管入口尚未核验：'+'；'.join(page['blocked_reasons']))
            # Native callbacks and old monitor writers never run concurrently.
            self.monitoring = False; self.automation_running = False; self.loot_state = None
            self.automation_status = '自动整理已暂停，操作交由托管模式。'
            self.busy = True; self.operation_kind = 'managed'
            self.cancelled.clear()
        try:
            observation = self._managed_observation()
            with self.guard:
                if self.cancelled.is_set(): raise ValidationError('托管启动已取消。')
                refreshed = self.managed_page()
                if not refreshed['can_start']:
                    raise ValidationError('托管能力发生变化：'+'；'.join(refreshed['blocked_reasons']))
                if self.managed.settings['farming']['enabled']:
                    validate_settings(self.managed.settings)
                    farming = self.managed.settings['farming']
                    difficulty = (self.managed.target_difficulty if self.managed_can_resume else
                        farming['difficulty'] if farming['difficulty']!='current' else refreshed['current_difficulty'])
                    if difficulty not in DIFFICULTIES: raise ValidationError('当前游戏难度未确认。')
                    option = next((row for row in refreshed['difficulties'] if row['id']==difficulty),None)
                    if not option or option.get('unlocked') is not True: raise ValidationError('目标难度尚未解锁。')
                    selected_maps = refreshed['maps_by_difficulty'].get(difficulty,refreshed['maps'])
                    target_map = self.managed.target_dungeon if self.managed_can_resume else farming['dungeon_id']
                    selected = next((m for m in selected_maps if str(m['id'])==str(target_map)),None)
                    if selected is None or selected.get('unlocked') is not True or selected.get('can_enter') is False:
                        raise ValidationError('目标关卡尚未解锁或入场材料不足。')
                    if farming['mode']=='push' and not self.managed_can_resume:
                        farming['progression'] = campaign_route(self.managed_catalog,farming['dungeon_id'],difficulty)
                if self.managed_can_resume and hasattr(self.managed,'resume'):
                    self.managed.resume(observation)
                else:
                    self.managed_transition = None
                    self.managed.start(observation)
                    self.managed_started_at = datetime.now(timezone.utc).isoformat()
                    self.managed_elapsed = 0
                    self.managed_history = []
                self.managed_started_clock = time.monotonic()
                self.managed_can_resume = False
                self.journal.append('system','managed_started','启动托管模式')
        finally:
            with self.guard:
                self._managed_finish_stop()
                self.busy=False; self.operation_kind=None
        return self.managed_page()

    def stop_managed(self, *, pause=False, reason=None):
        with self.guard:
            was_running = self.managed.running
            self.managed_can_resume = pause and (was_running or self.managed_can_resume)
            if was_running or self.operation_kind=='managed': self.cancelled.set()
            if self.operation_kind=='managed':
                self.managed_stop_request = {'pause':pause,'reason':reason}
                self.managed.status = '正在停止托管，等待已提交动作的执行结果。'
            elif pause and was_running:
                self.managed_transition = None
                self.managed.pause(reason or '托管已暂停。')
            else:
                self.managed_transition = None
                self.managed.stop(reason or '托管已停止。')
            if self.operation_kind!='managed': self._managed_freeze_clock()
        return self.managed_page()

    def finish_managed(self):
        """User stop is graceful; error/disconnect/shutdown use stop_managed."""
        with self.guard:
            if self.closed.is_set() or self.updating: raise ValidationError('助手正在退出或更新。')
            if self.managed_stop_request is not None: raise ValidationError('正在等待当前动作停止，请稍后再试。')
            if not self.managed.running and self.managed.phase != 'paused': return self.managed_page()
            if not self.client.connected: raise ValidationError('游戏已断开，无法回城整理。')
            self.monitoring = False; self.automation_running = False; self.loot_state = None
            self.cancelled.clear()
            self.managed_can_resume = False
            self.managed.request_finish()
            if self.managed_started_clock is None: self.managed_started_clock = time.monotonic()
            self.journal.append('system','managed_finish_requested','主动停止：回城整理后结束托管。')
        return self.managed_page()

    def _managed_freeze_clock(self):
        if self.managed_started_clock is not None:
            self.managed_elapsed += max(0,time.monotonic()-self.managed_started_clock)
            self.managed_started_clock = None

    def _managed_finish_stop(self):
        request,self.managed_stop_request = self.managed_stop_request,None
        if request is not None:
            self.managed_transition = None
            if request['pause']: self.managed.pause(request['reason'] or '托管已暂停。')
            else: self.managed.stop(request['reason'] or '托管已停止。')
        if not self.managed.running:
            self.managed_transition = None
            self._managed_freeze_clock()

    def reset_managed(self):
        with self.guard:
            if self.managed.running or self.operation_kind=='managed': raise ValidationError('请先停止托管再清空统计。')
            self.managed = ManagedMode(self.managed.settings)
            self.managed_can_resume=False; self.managed_started_at=None; self.managed_started_clock=None
            self.managed_transition=None; self.managed_elapsed=0
            self.managed_history=[]
        return self.managed_page()

    def _managed_execute(self, action, observation):
        kind,item = action['kind'],action.get('item')
        def active(): return self.managed.running and not self.cancelled.is_set()
        if not active(): raise ValidationError('托管已取消。')
        if self.managed.finishing and kind in ('enter_dungeon','switch_difficulty'):
            return {'verified':False,'retryable':True,'reason':'已请求停止，改为回城整理。'}
        # Inventory writes need fresh rule/equip checks. Pickup backends already
        # resolve the drop, verify receiving capacity/identity and confirm the
        # receipt themselves; do not scan campaign/character/rules twice here.
        if kind not in ('collect_ground', 'collect_carriage'):
            observation = self._managed_observation()
        if observation.get('complete') is not True: raise SnapshotChangedError('物品正在变化，等待重新规划。')
        if kind in ('enter_dungeon','switch_difficulty') and not town_rewards_clear(observation):
            return {'verified':False,'retryable':True,'reason':'主城奖励尚未收取或收纳完成，继续整理后再进入地图。'}
        if self.managed.finishing and kind in ('enter_dungeon','switch_difficulty'):
            return {'verified':False,'retryable':True,'reason':'已请求停止，改为回城整理。'}
        if action.get('reason_code') == 'background_organize':
            if (not self.managed.settings['background']['inventory_automation']
                    or action.get('automation_settings') != observation.get('automation_settings')):
                return {'verified':False,'retryable':True,'reason':'自动整理设置已变化，重新规划。'}
        capability = {'enter_dungeon':'travel','return_town':'travel','open_chest':'chests',
                      'switch_difficulty':'difficulty',
                      'collect_ground':'ground_pickup','collect_carriage':'transfer'}.get(kind,kind)
        if not available_capability(self.managed_page()['capabilities'].get(capability)):
            raise ValidationError('当前托管动作能力尚未核验：'+capability)
        if item and kind in ('transfer','lock','equip','sell','salvage','open_chest'):
            current = next((r for r in observation['items'] if identity(r)==identity(item)
                            and r.get('container')==item.get('container')),None)
            if not current: raise ValidationError('物品已移动或变化。')
            if current.get('slot_index')!=item.get('slot_index') or current.get('count')!=item.get('count'):
                raise ValidationError('物品格位或数量已变化。')
            item = current
        if kind in ('sell','salvage'):
            # The locking stage is a barrier for the whole current bag, even
            # when a game-side pickup arrived after the plan was generated.
            for candidate in observation['items']:
                if candidate.get('container')!='inventory' or candidate.get('kind')!='equipment': continue
                if (candidate.get('review') is True or candidate.get('issues')
                        or not self.managed._quality_known(candidate)
                        or ((mandatory_storage(candidate)
                             or candidate.get('matches') is True) and candidate.get('locked') is not True)):
                    return {'verified':False,'retryable':True,'reason':'先完成新装备筛选与锁定。'}
        if kind=='transfer':
            if action.get('target')=='storage':
                pages = (observation['automation_settings'][action['automation_group']]['pages']
                    if action.get('reason_code') == 'background_organize' else
                    self.managed.settings['cleanup'][item['kind']+'_pages'])
                approved = set(self.managed._targets(observation,pages))
                if not set(action.get('target_indices',[])) <= approved or not action.get('target_indices'):
                    raise ValidationError('目标仓库页不在托管配置范围内。')
        # Resolve one trusted identity against a fresh snapshot before execution.
        snap = self.snapshot
        source = next((r for c in (snap or {}).get('containers',{}).values() for r in c.get('slots',[])
                       if identity(r)==identity(item) and r.get('container')==item.get('container')) ,None) if item else None
        if kind in ('sell','salvage'):
            if reason := disposal_protection(item): raise ValidationError(reason)
            if item.get('kind')=='equipment':
                if not self.managed._disposable(item): raise ValidationError('保留装备不能出售或分解。')
                expected = equipment_policy(self.managed.settings['cleanup'],item,
                    fallback=action.get('reason_code') == 'equipment_fallback')
                if kind != expected:
                    return {'verified':False,'retryable':True,'reason':'装备品质或处置策略已变化，重新规划。'}
            elif (kind=='salvage' or item.get('locked') is not False
                    or item.get('kind') not in ('rune','gem')
                    or self.managed.settings['cleanup'][item['kind']+'_action'] != 'sell'):
                raise ValidationError('当前物品不能按此策略处置。')
        if kind in ('transfer','lock','equip','sell','salvage','open_chest'):
            if not source: raise ValidationError('物品已移动或变化，请重新扫描。')
            if source.get('slot_index')!=item.get('slot_index') or source.get('count')!=item.get('count'):
                raise ValidationError('物品格位或数量已变化。')
        if kind=='equip' or kind=='transfer' and action.get('reason_code')=='equip_prepare':
            scores = item.get('power',{}).get('comparisons',[])
            current_score = next((s for s in scores if s.get('target')==action.get('target_slot')),None)
            if kind=='transfer':
                current_score = next((s for s in scores if equip_candidate_allowed(item,s,
                    self.managed.settings['auto_equip'],observation.get('character'))),None)
            if not equip_candidate_allowed(item,current_score,self.managed.settings['auto_equip'],
                                           observation.get('character')):
                return {'verified':False,'retryable':True,'reason':'换装比较已变化，重新计算。'}
        if kind=='transfer':
            result = self.client.move_items([source],action['target'],active,target_indices=action.get('target_indices'))
            result = {**result,'verified':result.get('moved')==1,'quantity':item.get('count',1)}
        elif kind=='lock':
            result = self.client.lock_equipment(source,lambda row:active())
            result = {**result,'verified':result.get('status') in ('locked','already_locked')}
        elif kind=='collect_carriage':
            result = self.client.collect_carriage(item['selection_id'],active)
            result = {**result,'verified':result.get('moved')==1}
        else:
            native_kind = 'enter_map' if kind=='enter_dungeon' else kind
            payload = {**action,'item':source or item}
            if kind=='equip': payload['expected_replaced_uid']=current_score.get('replaced_uid')
            if kind=='enter_dungeon': payload['map_id']=action['dungeon_id']
            if kind=='collect_ground': payload['selection_id']=item['selection_id']
            if kind in ('sell','salvage'):
                payload.update(disposition_authorized=True,rule_matched=item.get('matches') is True,
                               rule_pending=item.get('review') is True or bool(item.get('issues')))
            result = self.client.execute_game_action(native_kind,payload,self.cancelled,validate=active)
            if result.get('transition_requested'):
                self.managed_transition = {'action':action,'deadline':time.monotonic()+45,
                                           'requested_scene':self._transition_scene(observation['scene'])}
                record('managed_transition_requested',kind=kind,
                       target_map=action.get('dungeon_id'),difficulty=action.get('difficulty'),
                       scene=self.managed_transition['requested_scene'])
            else:
                result = {**result,'verified':result.get('effect_confirmed') is True or result.get('already_in_town') is True,
                          'quantity':result.get('quantity',item.get('count',1) if item else None)}
        return result

    @staticmethod
    def _transition_scene(scene):
        run = run_record(scene.get('run'))
        return {**{k:scene.get(k) for k in ('available','in_town','in_dungeon','dungeon_id',
                    'difficulty','scene_changing','teleporting','dead','completion_visible')},
                'run_id':run.get('id'),'run_status':run.get('status')}

    def _managed_once(self):
        self.managed_fast_followup = False
        observation = self._managed_observation()
        with self.guard:
            transition = self.managed_transition
            if transition:
                action = transition['action']
                scene = observation['scene']
                confirmed = scene.get('available') is True and (scene.get('in_town') is True if action['kind']=='return_town'
                     else scene.get('in_dungeon') is True and str(scene.get('dungeon_id'))==str(action['dungeon_id'])
                     and (not action.get('difficulty') or scene.get('difficulty')==action['difficulty'])
                     and run_record(scene.get('run')).get('status') in ('running','settling'))
                if confirmed:
                    self.managed_transition = None
                else:
                    if time.monotonic()>transition['deadline']:
                        last_scene = self._transition_scene(scene)
                        record('managed_transition_timeout',kind=action['kind'],
                               target_map=action.get('dungeon_id'),difficulty=action.get('difficulty'),
                               requested_scene=transition.get('requested_scene'),scene=last_scene,
                               control_error=self.managed_control.get('reason'))
                        label = '回城' if action['kind']=='return_town' else '进入关卡'
                        location = ('主城' if scene.get('in_town') is True else
                            '关卡 '+str(scene.get('dungeon_id') or '未知') if scene.get('in_dungeon') is True else '场景不可读')
                        raise ValidationError('关卡切换结果未确认（请求'+label+'；当前'+location+'），已停止托管。')
                    self.managed.status='等待游戏完成场景切换。'
                    return self.managed.status
            else:
                action = self.managed.next_action(observation)
                if self.managed.phase=='paused': self.managed_can_resume=True
        if not action: return self.managed.status
        result = {'verified':True,'scene_confirmed':True} if transition else self._managed_execute(action,observation)
        with self.guard:
            if result.get('transition_requested'):
                self.managed.status = '已请求场景切换，等待游戏确认。'
                return self.managed.status
            if result.get('retryable'):
                self.managed.pending = None
                self.managed.status = result.get('reason','等待下一轮读取。')
                return self.managed.status
            # A cancelled in-flight action may already have completed. Log its
            # receipt but never resume the planner or submit another action.
            if self.managed.pending:
                self.managed.complete(action['action_id'],result=result)
            message = action.get('reason','托管动作')+(' 已确认。' if result.get('verified') else ' 未确认，已停止。')
            self.managed_history.append({'time':datetime.now(timezone.utc).isoformat(),'message':message,
                                         'level':'info' if result.get('verified') else 'error'})
            self.managed_history = self.managed_history[-100:]
            self.journal.append('system','managed_action',message,context={'action':action,'result':result})
        pickup = action['kind'] in ('collect_ground', 'collect_carriage') and result.get('verified') is True
        self._publish(self.client.snapshot(), refresh_character=not pickup)
        self.managed_fast_followup = pickup
        return message
