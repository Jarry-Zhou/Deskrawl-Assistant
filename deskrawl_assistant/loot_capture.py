"""Opt-in, local-only evidence capture for high-value planned/observed loot.

This is not the activity journal: server promises do not count as settled loot.
No game action or upload is performed. Polling can miss transient drops.
"""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import uuid

from .item_protection import mandatory_storage
from .loot_plan_reader import describe_item, SLOT_LABELS, _labels


def now():
    return datetime.now(timezone.utc).isoformat()


def plan_hash(raw):
    return hashlib.sha256(raw['runId'].encode()).hexdigest()


def planned_hits(raw):
    hits = []
    for wave in raw.get('waves',[]):
        for item in (wave.get('loot') or {}).get('items',[]):
            pretty = describe_item({'base_item_id':item['baseItemId'], 'slot':item['slot'],
                'rarity':item['rarity'], 'level':item['itemLevel'], 'ancient':item['ancient'],
                'black_mist':item['blackMist'], 'modifiers':item['modifiers'], 'sockets':item['sockets'],
                'qty':item['qty'], 'chest_gold':item['chestGold']})
            reason = mandatory_storage({**pretty, 'internal_name':item['baseItemId'],
                'is_black_mist':pretty['kind']=='equipment' and item['blackMist'],
                'is_equipment':pretty['kind']=='equipment' or pretty['kind']=='unknown' and item['slot'] in SLOT_LABELS})
            if not reason and pretty['kind']=='unknown' and item['slot'] in SLOT_LABELS and item['blackMist']:
                reason = '黑雾装备'
            if reason:
                hits.append({'wave':wave['wave'], 'drop_id':item['dropId'],
                    'item_key':item['baseItemId'], 'name':pretty['name'], 'category':reason})
    return hits


class LootCaptureMonitor:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.guard = threading.RLock()
        self.enabled = False
        self.message = '监控未开启。'
        self.error = ''
        self.saved_runs = len(list(self.directory.glob('*.json'))) if self.directory.exists() else 0
        self.last_saved = None
        self.runs = OrderedDict()
        self.session = None
        self.character = None
        self.seen = set()
        self.new_ids = {}
        self.captured_ids = set()
        self.baseline_ready = False
        self.pending = set()
        self.polls = 0

    def status(self):
        with self.guard:
            return {'enabled':self.enabled, 'message':self.message, 'error':self.error,
                'saved_runs':self.saved_runs, 'last_saved':self.last_saved,
                'directory':str(self.directory.resolve()), 'polls':self.polls}

    def set_enabled(self, enabled):
        if type(enabled) is not bool: raise ValueError('高价值掉落监控开关必须为布尔值。')
        with self.guard:
            if enabled and not self.enabled:
                self.runs.clear()
                self.session = None
                self.character = None
                self.seen.clear()
                self.new_ids.clear()
                self.captured_ids.clear()
                self.pending.clear()
                self.baseline_ready = False
            self.enabled = enabled
            self.error = ''
            self.message = '监控已开启，等待稳定的在线关卡与物品清单。' if enabled else '监控已关闭，已保存文件仍保留。'
        return self.status()

    def waiting(self, message):
        with self.guard:
            if self.enabled: self.message = message

    def failed(self):
        with self.guard:
            if self.enabled:
                self.error = '本次监控读取或保存失败，将自动重试；其他功能继续运行。'

    def _save(self, key, entry):
        document = {'schema_version':1, 'source':'external_read_only_RunPlan',
            'capture_scope':'RunPlan context and complete RunWave.loot/PlanItem/PlanModifier fields; not a network packet.',
            'first_read_at':entry['first_read_at'], 'first_read_wave':entry['first_read_wave'],
            'saved_at':now(), 'plan_changed_since_first_read':entry['first_plan'] != entry['latest_plan'],
            'raw_plan':entry['first_plan'], 'latest_raw_plan':entry['latest_plan'] if entry['first_plan'] != entry['latest_plan'] else None,
            'planned_high_value':entry['planned_hits'], 'observed_high_value':entry['observed_hits'],
            'association':entry['association'],
            'note':'计划不等于实际结算；实际观测仅在完整清单基线后记录新增UID。无精确dropId匹配时不能证明物品在开局计划中。'}
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory/(key+'.json')
        temporary = self.directory/(key+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('w',encoding='utf-8') as stream:
                json.dump(document,stream,ensure_ascii=False,indent=2,allow_nan=False)
                stream.write('\n')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        if not entry.get('saved'):
            self.saved_runs += 1
            entry['saved'] = True
        self.last_saved = document['saved_at']
        self.pending.discard(key)

    def feed(self, bundle):
        with self.guard:
            if not self.enabled: return
            session = bundle['session']
            if session != self.session:
                self.runs.clear()
                self.pending.clear()
                self.seen.clear()
                self.new_ids.clear()
                self.captured_ids.clear()
                self.baseline_ready = False
                self.session = session
                self.character = None
            character = bundle.get('character_key')
            if character and character != self.character:
                # Switching save characters in the same process must establish
                # a new baseline, not call their owned valuables fresh loot.
                self.seen.clear()
                self.new_ids.clear()
                self.captured_ids.clear()
                self.baseline_ready = False
                self.character = character
            self.polls += 1
            self.error = ''
            raw = bundle.get('raw_plan')
            preview = bundle.get('preview') or {}
            if raw and preview.get('available'):
                digest = plan_hash(raw)
                key = hashlib.sha256((session+'\0'+raw['runId']).encode()).hexdigest()
                if key not in self.runs:
                    self.runs[key] = {'first_read_at':now(), 'first_read_wave':preview['run']['current_wave'],
                        'first_plan':deepcopy(raw), 'latest_plan':deepcopy(raw), 'plan_hash':digest,
                        'association':'same_run', 'planned_hits':[], 'observed_hits':[], 'observed_ids':set()}
                entry = self.runs[key]
                changed = entry['latest_plan'] != raw
                entry['latest_plan'] = deepcopy(raw)
                hits = planned_hits(raw)
                if hits != entry['planned_hits'] or changed and entry.get('saved'):
                    entry['planned_hits'] = hits
                    if hits or entry.get('saved'): self.pending.add(key)
                self.runs.move_to_end(key)
            if bundle.get('observations_complete') is True:
                observations = bundle.get('observations',[])
                ids = {r['item_uid'] for r in observations if isinstance(r.get('item_uid'),str) and r['item_uid']}
                if not self.baseline_ready:
                    self.seen.update(ids)
                    self.baseline_ready = True
                else:
                    for row in observations:
                        uid = row.get('item_uid')
                        if not uid: continue
                        if uid not in self.seen:
                            self.seen.add(uid)
                            self.new_ids[uid] = {'run':bundle.get('observation_run'),
                                'source':row.get('capture_source'), 'time':now()}
                        # A newly seen ground drop can become classifiable
                        # only later in the bag. Existing baseline items stay
                        # excluded; a transfer cannot create a second event.
                        if uid not in self.new_ids or uid in self.captured_ids: continue
                        reason = mandatory_storage(row)
                        if not reason: continue
                        entry_pair = next(((k,e) for k,e in reversed(self.runs.items())
                            if e['plan_hash'] and e['plan_hash']==self.new_ids[uid]['run']), None)
                        if entry_pair is None:
                            # Keep the evidence without attaching it to a
                            # different/reused map's cached plan.
                            key = hashlib.sha256((session+'\0unattributed\0'+uid).encode()).hexdigest()
                            entry = {'first_read_at':now(), 'first_read_wave':None, 'first_plan':None,
                                'latest_plan':None, 'plan_hash':None, 'association':'unattributed',
                                'planned_hits':[], 'observed_hits':[], 'observed_ids':set()}
                            self.runs[key] = entry
                        else: key, entry = entry_pair
                        if uid in entry['observed_ids']: continue
                        entry['observed_ids'].add(uid)
                        self.captured_ids.add(uid)
                        plan_items = [(w['wave'],i) for w in (entry['latest_plan'] or {}).get('waves',[])
                            for i in (w.get('loot') or {}).get('items',[])]
                        exact = [w for w,i in plan_items if i['dropId']==uid and i['baseItemId']==row.get('internal_name')]
                        template = [w for w,i in plan_items if i['baseItemId']==row.get('internal_name')]
                        entry['observed_hits'].append({'observed_at':now(), 'item_uid':uid,
                            'item_key':row.get('internal_name'), 'category':reason, 'source':row.get('capture_source'),
                            'name':_labels()['items'].get(row.get('internal_name'),{}).get('name',row.get('internal_name')),
                            'first_observed_at':self.new_ids[uid]['time'], 'first_source':self.new_ids[uid]['source'],
                            'rarity':row.get('rarity',row.get('base_rarity')), 'black_mist':row.get('is_black_mist') is True,
                            'exact_drop_id_waves':exact, 'same_template_waves':template,
                            'exact_plan_items':[i for _,i in plan_items if i['dropId']==uid and i['baseItemId']==row.get('internal_name')],
                            'plan_membership':'exact_id' if exact else 'unconfirmed'})
                        self.pending.add(key)
                    # Fail closed for actual detection rather than silently
                    # forgetting old UIDs and treating transfers as new drops.
                    if len(self.seen)>100_000:
                        self.baseline_ready = False
                        self.seen = ids
                        self.new_ids.clear()
                        self.captured_ids.clear()
            # Retry pending writes even if the next poll has no new events.
            for key in list(self.pending): self._save(key,self.runs[key])
            while len(self.runs)>4:
                old, _ = self.runs.popitem(last=False)
                self.pending.discard(old)
            self.message = ('正在监控计划与实际新增物品。' if preview.get('available') else
                            '正在监控实际新增物品，等待下一局在线掉落计划。')
            if bundle.get('observations_complete') is not True:
                self.message += '实际物品清单暂未完整，只检查已确认计划。'
