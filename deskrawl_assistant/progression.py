"""Plans for growth and shard spending. No process access or game writes."""
from copy import deepcopy
from functools import lru_cache
import json

from .models import ValidationError
from .paths import RESOURCE_ROOT

DEFAULT_PROGRESSION = {'talents_enabled': False, 'skills_enabled': False,
                       'talent_targets': {}, 'skill_stages': {}}
DEFAULT_LIFE = {'enabled': False, 'priorities': [], 'gold_reserve': 0}
TALENT_POINT_LIMIT = 70
PURCHASE_BATCH_LIMIT = 10
DEFAULT_MERCHANT = {'enabled': False, 'trigger_percent': 85, 'spend_to_percent': 0,
                    'weights': {str(n): 0 for n in range(1, 11)}}
NEW_ACTIONS = ('allocate_talent', 'learn_life_skill', 'set_skill', 'merchant_open', 'merchant_buy', 'merchant_close', 'merchant_refresh')


@lru_cache(maxsize=1)
def catalog():
    return json.loads((RESOURCE_ROOT / 'data/progression-catalog.json').read_text(encoding='utf-8'))


def enabled(settings):
    return (settings['merchant']['enabled'] or settings['life_skills']['enabled']
            or settings['progression']['talents_enabled'] or settings['progression']['skills_enabled'])


def _integer(n, lo, hi, label):
    if type(n) is not int or not lo <= n <= hi:
        raise ValidationError(label + '无效。')


def validate_growth(settings, data=None):
    data = data or catalog()
    p, life, merchant = (settings[k] for k in ('progression', 'life_skills', 'merchant'))
    for value in (p['talents_enabled'], p['skills_enabled'], life['enabled'], merchant['enabled']):
        if type(value) is not bool: raise ValidationError('成长与商人功能开关无效。')
    _integer(life['gold_reserve'], 0, 2**31 - 1, '生活技能保留金币')
    _integer(merchant['trigger_percent'], 1, 100, '碎片回城百分比')
    _integer(merchant['spend_to_percent'], 0, 99, '碎片购买后保留百分比')
    if merchant['spend_to_percent'] >= merchant['trigger_percent']:
        raise ValidationError('购买后保留比例必须低于回城触发比例。')
    weights = merchant['weights']
    if not isinstance(weights, dict) or set(weights) != {str(r['slot']) for r in data['shop']}:
        raise ValidationError('商人购买部位无效。')
    for weight in weights.values(): _integer(weight, 0, 1000, '购买比例')
    if merchant['enabled'] and not any(weights.values()): raise ValidationError('至少选择一个购买部位。')
    life_ids = {n['id'] for n in data['life_skills']}
    priority = life['priorities']
    if (not isinstance(priority, list) or any(type(k) is not str or k not in life_ids for k in priority)
            or len(priority) != len(set(priority))):
        raise ValidationError('生活技能优先节点无效。')
    for field in ('talent_targets', 'skill_stages'):
        if not isinstance(p[field], dict) or not set(p[field]) <= set(data['heroes']):
            raise ValidationError('职业成长配置无效。')
    for mask, targets in p['talent_targets'].items():
        nodes = {n['id']: n for n in data['heroes'][mask]['talents']}
        if not isinstance(targets, dict) or not set(targets) <= set(nodes):
            raise ValidationError('天赋不属于指定职业。')
        exclusive = set()
        for key, rank in targets.items():
            node = nodes[key]; _integer(rank, 0, node['max_points'], '天赋目标点数')
            if not rank: continue
            if node.get('selectable') is False: raise ValidationError('该天赋未在游戏中开放。')
            parent = node['prerequisite']
            if parent and targets.get(parent, 0) != nodes[parent]['max_points']:
                raise ValidationError('请先点满天赋前置：' + nodes[parent]['name'])
            group = node['exclusive_group']
            if group and group in exclusive: raise ValidationError('互斥天赋只能选择其中一项。')
            if group: exclusive.add(group)
        if sum(targets.values()) > TALENT_POINT_LIMIT:
            raise ValidationError(f'每个职业的战斗天赋预设最多 {TALENT_POINT_LIMIT} 点，请先减少预设点数。')
        # A final plan must be reachable within the configured point budget.
        ranks = {}; left = sum(targets.values())
        while left:
            key = next((k for k, n in nodes.items() if ranks.get(k, 0) < targets.get(k, 0)
                        and talent_allowed(n, nodes, ranks)), None)
            if key is None: raise ValidationError('天赋目标无法满足已投入点数门槛，请补选前面的天赋。')
            ranks[key] = ranks.get(key, 0) + 1; left -= 1
    for mask, stages in p['skill_stages'].items():
        skills = {s['id']: s for s in data['heroes'][mask]['abilities']}
        if not isinstance(stages, list) or len(stages) > 200: raise ValidationError('技能阶段配置无效。')
        levels = set()
        for stage in stages:
            if not isinstance(stage, dict) or set(stage) != {'level', 'slots'}: raise ValidationError('技能阶段字段无效。')
            _integer(stage['level'], 1, 200, '技能阶段等级')
            if stage['level'] in levels: raise ValidationError('技能阶段等级重复。')
            levels.add(stage['level']); slots = stage['slots']
            if not isinstance(slots, list) or len(slots) != 4: raise ValidationError('技能栏位配置无效。')
            if any(k is not None and type(k) is not str for k in slots): raise ValidationError('技能编号无效。')
            selected = [k for k in slots if k is not None]
            if len(set(selected)) != len(selected): raise ValidationError('同一阶段不能重复装备技能。')
            for index, key in enumerate(slots):
                if key is not None and (key not in skills or index not in skills[key]['slots']):
                    raise ValidationError('技能职业或栏位不一致。')
        stages.sort(key=lambda row: row['level'])
        combined = [None] * 4
        for stage in stages:
            combined = [new if new is not None else old for old, new in zip(combined, stage['slots'])]
            chosen = [key for key in combined if key]
            if len(chosen) != len(set(chosen)):
                raise ValidationError('技能阶段沿用之前的配置后出现重复技能，请同时调整两个特殊技能栏。')
    return settings


def talent_allowed(node, nodes, ranks):
    parent = node['prerequisite']
    return (node.get('selectable') is not False and ranks.get(node['id'], 0) < node['max_points']
            and sum(ranks.values()) >= node['point_requirement']
            and (not parent or ranks.get(parent, 0) >= nodes[parent]['max_points'])
            and not (node['exclusive_group'] and any(ranks.get(k, 0) > 0
                and k != node['id'] and n['exclusive_group'] == node['exclusive_group'] for k, n in nodes.items())))


def growth_action(settings, state, data=None):
    """Return one point/skill action, or a reason to wait; never reset a build."""
    data = data or catalog()
    if not (settings['life_skills']['enabled'] or settings['progression']['talents_enabled']
            or settings['progression']['skills_enabled']): return None, ''
    if state.get('available') is not True: return None, state.get('reason') or '等待成长状态读取。'
    if state.get('busy') is True: return None, '等待游戏完成在线同步后继续成长。'
    mask = str(state['class_mask']); hero = data['heroes'].get(mask)
    if not hero: raise ValidationError('当前职业成长配置尚未适配。')
    p = settings['progression']; ranks = state['talents']['ranks']
    nodes = {n['id']: n for n in hero['talents']}
    targets = p['talent_targets'].get(mask, {})
    if p['talents_enabled'] and state['talents']['unspent'] > 0:
        for key, target in targets.items():
            if ranks.get(key, 0) < target and talent_allowed(nodes[key], nodes, ranks):
                return {'kind': 'allocate_talent', 'node_id': key, 'expected_rank': ranks.get(key, 0),
                        'class_mask': state['class_mask'], 'reason': '按目标加点：' + nodes[key]['name']}, ''
    if p['skills_enabled']:
        stages = [s for s in p['skill_stages'].get(mask, []) if s['level'] <= state['level']]
        # Later stages override selected slots, while empty slots retain earlier targets.
        targets = [None] * 4
        for stage in stages:
            targets = [new if new is not None else old for old, new in zip(targets, stage['slots'])]
        known = {s['id']: s for s in hero['abilities']}
        final = [key if key and key in state['skills']['available'] and state['level'] >= known[key]['level_requirement'] else current
                 for key, current in zip(targets, state['skills']['equipped'])]
        if (final != state['skills']['equipped'] and len([k for k in final if k]) == len(set(k for k in final if k))):
            return {'kind': 'set_skill', 'skill_slots': final, 'class_mask': state['class_mask'],
                    'reason': '按当前等级切换目标技能组合。'}, ''
    life = settings['life_skills']
    if life['enabled']:
        nodes = {n['id']: n for n in data['life_skills']}; ranks = state['life_skills']['ranks']
        order = life['priorities'] + sorted((k for k in nodes if k not in life['priorities']),
                key=lambda k: (nodes[k]['gold_costs'][0] if nodes[k]['gold_costs'] else 0, k))
        def missing(key, visiting=()):
            if key in visiting: raise ValidationError('生活技能前置出现循环。')
            node = nodes[key]
            if ranks.get(key, 0) >= node['max_points']: return None
            parent = node['prerequisite']
            return missing(parent, (*visiting, key)) or key if parent else key
        key = next((pending for k in order if (pending := missing(k))), None)
        if key:
            node = nodes[key]; rank = ranks.get(key, 0); costs = node['gold_costs']
            cost = max(0, costs[min(rank, len(costs) - 1)]) if costs else 0
            if state['gold'] - life['gold_reserve'] >= cost:
                return {'kind': 'learn_life_skill', 'node_id': key, 'expected_rank': rank,
                        'gold_cost': cost, 'gold_reserve': life['gold_reserve'],
                        'class_mask': state['class_mask'], 'reason': '自动学习生活技能：' + node['name']}, ''
            return None, '生活技能等待金币：' + node['name'] + f'，需要 {cost} 金币。'
    return None, ''


def merchant_prices(entries, quotes, level, difficulty, online):
    """Display the native level formula; online purchases require a valid quote."""
    slots={1:'Weapon',2:'Helm',3:'Chest',4:'Pants',5:'Boots',6:'Belt',7:'Ring',8:'Necklace',9:'Gloves',10:'Shoulder'}
    stock,preview=[],[]
    normalize_difficulty=lambda value: 'inferno' if value.casefold()=='inferno1' else value.casefold()
    for entry in entries:
        quote=quotes.get(slots[entry['slot']].casefold())
        valid=bool(quote and type(quote.get('level')) is int and quote['level']>=level
                   and isinstance(quote.get('difficulty'),str) and normalize_difficulty(quote['difficulty'])==normalize_difficulty(difficulty))
        reference=entry['base_price']*max(1,level//10)
        price=quote['price'] if valid else None if online else reference
        if price is not None and (type(price) is not int or price<1):
            raise ValidationError('商人报价无效。')
        if price is not None:
            prices=quote.get('prices',[price]) if valid else [price]
            if (not isinstance(prices,list) or not prices or len(prices)>PURCHASE_BATCH_LIMIT
                    or any(type(n) is not int or n<1 for n in prices) or prices[0]!=price):
                raise ValidationError('商人批量报价无效。')
            same=next((n for n,value in enumerate(prices) if value!=price),len(prices))
            stock.append(dict(entry,price=price,available_count=same))
        preview.append(dict(entry,price=price if price is not None else reference,price_reference=price is None,
                            price_source='quote' if valid else 'level'))
    return stock,preview


def next_purchase(settings, state, counts, *, max_quantity=1):
    """Buy consecutive batches in slot order; only confirmed receipts advance."""
    balance, capacity = state['soul_shards']['current'], state['soul_shards']['maximum']
    budget = balance - capacity * settings['spend_to_percent'] // 100
    candidates = [r for r in state['merchant']['stock'] if settings['weights'].get(str(r['slot']), 0) > 0]
    if not candidates: raise ValidationError('神秘商人没有配置的可购买部位。')
    candidates.sort(key=lambda r: r['slot'])
    cycle = sum(settings['weights'][str(r['slot'])] for r in candidates)
    position = sum(counts.get(str(r['slot']), 0) for r in candidates) % cycle
    for slot in candidates:
        amount = settings['weights'][str(slot['slot'])]
        if position < amount: break
        position -= amount
    if slot['price'] > budget: return None
    quantity=min(amount-position,slot.get('available_count',1),max_quantity,PURCHASE_BATCH_LIMIT,budget//slot['price'])
    if quantity<1:return None
    action={'kind': 'merchant_buy', 'stock_id': slot['id'], 'shop_slot': slot['slot'],
            'expected_price': slot['price'], 'before_shards': balance,
            'class_mask': state['class_mask'], 'reason': '神秘商人购买：' + slot['name']}
    if quantity>1:action.update(quantity=quantity,reason=action['reason']+f' × {quantity}')
    return action
