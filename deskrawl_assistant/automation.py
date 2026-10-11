"""Validated preferences and capacity planning for automatic physical transfers."""
from copy import deepcopy
from .models import ValidationError
from .storage_preferences import DEFAULT_STORAGE_PAGES

DEFAULT_SETTINGS = {
    'carriage':{'enabled':False,'types':[]},
    'gems':{'enabled':False,'pages':list(DEFAULT_STORAGE_PAGES['gem'])},
    'runes':{'enabled':False,'pages':list(DEFAULT_STORAGE_PAGES['rune'])},
    'pressure':{'enabled':False,'threshold':4,'target_free':12,'equipment_filter':'all','pages':list(DEFAULT_STORAGE_PAGES['equipment'])},
}
ITEM_TYPES = ('equipment','rune','gem','chest','material')
LEGACY_FIELDS = {'carriage':{'enabled','items'},'gems':{'enabled'},
                 'pressure':{'enabled','threshold','target_free','equipment_filter'}}


def _migrate_legacy(raw,available):
    """Convert old named-item preferences in memory; never rewrite their file."""
    if not isinstance(raw,dict) or set(raw)!=set(LEGACY_FIELDS): return raw
    if any(not isinstance(raw[group],dict) or set(raw[group])!=fields for group,fields in LEGACY_FIELDS.items()):
        return raw
    selected = raw['carriage']['items']
    if (not isinstance(selected,list) or len(selected)>1024 or any(not isinstance(key,str) or key not in available for key in selected)
            or len(set(selected))!=len(selected)):
        raise ValidationError('旧版马车物品选择无效，原配置未改动。')
    kinds = {available[key].get('kind','material') for key in selected}
    if not kinds <= set(ITEM_TYPES): raise ValidationError('旧版马车物品类型未确认。')
    result = deepcopy(DEFAULT_SETTINGS)
    # This old schema predates partition selection and used page 1 for every
    # transfer. Preserve that behavior for saved legacy preferences.
    for group in ('gems','runes','pressure'): result[group]['pages'] = [1]
    result['carriage'].update(enabled=raw['carriage']['enabled'],types=[kind for kind in ITEM_TYPES if kind in kinds])
    result['gems']['enabled'] = raw['gems']['enabled']
    result['pressure'].update(raw['pressure'])
    return result


def validate_settings(raw,available,available_pages=None):
    """Keep reserved page choices; actual unlocked slots are checked at transfer."""
    raw = _migrate_legacy(raw,available)
    if not isinstance(raw,dict) or set(raw)!=set(DEFAULT_SETTINGS): raise ValidationError('自动整理配置格式无效。')
    for group,fields in DEFAULT_SETTINGS.items():
        if not isinstance(raw[group],dict) or set(raw[group])!=set(fields): raise ValidationError('自动整理选项不完整。')
        if not isinstance(raw[group]['enabled'],bool): raise ValidationError('自动整理开关必须为布尔值。')
    selected=raw['carriage']['types']
    if (not isinstance(selected,list) or len(selected)>len(ITEM_TYPES) or any(not isinstance(k,str) or k not in ITEM_TYPES for k in selected)
            or len(set(selected))!=len(selected)):
        raise ValidationError('马车物品类型选择无效，请重新选择。')
    if raw['carriage']['enabled'] and not selected: raise ValidationError('请先勾选至少一种要从马车收取的物品类型。')
    for group in ('gems','runes','pressure'):
        pages = raw[group]['pages']
        if (not isinstance(pages,list) or len(pages)>256 or any(type(n) is not int or n<1 for n in pages)
                or len(set(pages))!=len(pages)):
            raise ValidationError('自动整理仓库页选择无效：'+group)
        if raw[group]['enabled'] and not pages: raise ValidationError('请勾选自动入库使用的仓库页：'+group)
    p=raw['pressure'];threshold=p['threshold'];target=p['target_free']
    if any(isinstance(v,bool) or not isinstance(v,int) for v in (threshold,target)) or not 0<=threshold<target<=2048:
        raise ValidationError('整理后预留空格须大于触发空格数，范围为 0–2048。')
    if p['equipment_filter'] not in ('all','locked','unlocked'): raise ValidationError('装备入库范围无效。')
    return deepcopy(raw)


def storage_targets(snapshot,pages):
    """Return only permitted slots in explicitly selected 1-based pages."""
    transfer = snapshot.get('transfer',{})
    size,indices = transfer.get('page_size'),transfer.get('storage_indices')
    if (type(size) is not int or size<1 or not isinstance(indices,list)
            or any(type(n) is not int or n<0 for n in indices) or len(set(indices))!=len(indices)):
        raise ValidationError('仓库页大小或开放格位尚未核验，等待刷新。')
    return sorted(n for n in indices if n//size+1 in pages)


def free_slots(snapshot):
    bag=snapshot.get('containers',{}).get('inventory',{})
    capacity,occupied=bag.get('slot_count',0),bag.get('occupied_count',0)
    if not 0<=occupied<=capacity: raise ValidationError('背包容量读取异常。')
    return capacity-occupied


def pressure_candidates(snapshot,settings,continuing=False):
    free=free_slots(snapshot)
    goal=min(settings['target_free'],snapshot['containers']['inventory']['slot_count'])
    active=settings['enabled'] and (continuing or free<=settings['threshold']) and free<goal
    if not active: return [],False
    candidates=[r for r in snapshot['containers']['inventory']['slots'] if r.get('is_equipment') is True
                and not r.get('issues') and r.get('transfer_key')
                and (settings['equipment_filter']=='all' or r.get('locked') is (settings['equipment_filter']=='locked'))]
    # Retain a hysteresis goal between cycles; move only enough to reach it.
    return candidates[:goal-free],True
