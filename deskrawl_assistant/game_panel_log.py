"""Copy the game's notification log; never invoke a game method or write memory.

The UI.AutoSold / UI.AutoSalvaged producers report ground/carriage automatic
disposals. MerchantUI.gzy and hm.ecc (the assistant's inventory operations) do
not publish these notifications in the verified build. Their own receipts are
therefore a separate source. High-grade flags remain in WaveManager receipts.
"""
from functools import lru_cache
import hashlib
import json
import math
import re
import struct

from .native_memory import MemoryReadError
from .paths import RESOURCE_ROOT


@lru_cache(maxsize=1)
def equipment_names():
    catalog = json.loads((RESOURCE_ROOT / 'data/game-catalog.json').read_text(encoding='utf-8'))
    keys = catalog['indexes']['equipment_root_key_groups']['equipment_names']
    entries = catalog['tables']['Equipments']['entries']
    names = {}
    for key in keys:
        for name in {key, *(v for language, v in entries[key].items() if language != 'Key')}:
            if name:
                names.setdefault(name, set()).add(key)
    return names


@lru_cache(maxsize=32)
def _template_pattern(template):
    parts = re.split(r'(\{[01]\})', template)
    if parts.count('{0}') != 1 or parts.count('{1}') > 1:
        raise ValueError('游戏处置日志模板未核验。')
    return re.compile(''.join('(?P<item>.+?)' if p == '{0}' else '(?P<gold>[0-9]+)' if p == '{1}'
                              else re.escape(p).replace(r'\ ', r'\s+') for p in parts))


def parse_disposal(text, colors, templates, names=None):
    """Only verified localized templates, one colored equipment name and quantity 1."""
    if not isinstance(text, str): return None
    names = equipment_names() if names is None else names
    for action, values in templates.items():
        if action not in ('sell', 'salvage'): continue
        for template in set(values.values()):
            match = _template_pattern(template).fullmatch(text.strip())
            if not match: continue
            item = re.fullmatch(r'<color=#([0-9A-Fa-f]{6})>\[([^<>\r\n]+)\]</color>', match['item'])
            if not item: return None
            color, name = item.groups()
            rarity = colors.get(color.upper())
            keys = names.get(name, set())
            if type(rarity) is not int or not 0 <= rarity <= 4 or len(keys) != 1: return None
            key = next(iter(keys))
            gold = int(match['gold']) if 'gold' in match.groupdict() else None
            if gold is not None and not 0 <= gold <= 2**63-1: return None
            return {'action':action, 'quantity':1, 'gold':gold,
                    'item':{'kind':'equipment', 'is_equipment':True, 'rarity':rarity,
                            'internal_name':key, 'name_key':key, 'name':name, 'count':1}}
    return None


def _color(raw):
    channels = struct.unpack('<ffff', raw)
    if any(not math.isfinite(c) or not 0 <= c <= 1 for c in channels):
        raise MemoryReadError('游戏日志品质颜色未确认。')
    return ''.join(f'{round(c*255):02X}' for c in channels[:3])


def read_panel_log(reader, profile, manager, *, cache=None):
    """Own snapshot guards keep a changing log from invalidating other controls.

    Retain IDs for all categories to detect loss of the rolling-list anchor.
    Cache only immutable record copies, bounded by the current 1000-entry list.
    """
    from .game_actions import _Read
    reader.check_game_files()
    read = _Read(reader, profile)
    spec = profile['panel_log']
    klass = read.klass(read.ptr(reader.module['base'] + spec['class_rva']), 'hb')
    static = read.ptr(klass + 184)
    if not static: raise MemoryReadError('游戏日志尚未载入。')
    buffer = read.ptr(static)
    graphics = read.verify(read.ptr(manager + 40), 'GraphicsConfig')
    fields = {f['name']:f['rawRegistrationOffset'] for f in profile['types']['GraphicsConfig']['fields']}
    colors = {}
    for rarity, name in enumerate(('RarityCommon','RarityUncommon','RarityRare','RarityLegendary','RarityDivine')):
        color = _color(read.read(graphics + fields[name], 16))
        if color in colors: raise MemoryReadError('游戏日志装备品质颜色重复。')
        colors[color] = rarity
    records = read.list(buffer, 'ha', limit=2048)
    if len(records) > spec['capacity']: raise MemoryReadError('游戏日志条目数未确认。')
    result, next_cache = [], {}
    for address in records:
        read.verify(address, 'ha')
        raw = read.read(address + 16, 40)
        text_ptr = struct.unpack_from('<Q', raw)[0]
        category = struct.unpack_from('<i', raw, 24)[0]
        date = struct.unpack_from('<Q', raw, 32)[0]
        if category not in range(1, 7) or not 0 < date & ((1 << 62)-1) <= 3155378975999999999:
            raise MemoryReadError('游戏日志事件格式未确认。')
        token = (address, raw)
        record = (cache or {}).get(token)
        if record is None:
            event_id = hashlib.sha256(struct.pack('<QQiQ', address, text_ptr, category, date)).hexdigest()
            record = {'id':event_id, 'category':category}
            if category == 2:
                text = reader.string(text_ptr, max_length=4096)
                record['receipt'] = parse_disposal(text, colors, spec['templates'])
                record['text'] = text
        result.append(record)
        next_cache[token] = record
    read.finish()
    if cache is not None:
        cache.clear(); cache.update(next_cache)
    source = hashlib.sha256(f'{reader.session_id}:{static}:{buffer}'.encode()).hexdigest()
    return {'available':True, 'complete':True, 'id':source, 'capacity':spec['capacity'],
            'records':result, 'source':'LogPanelUI / hb.nhs'}


class DisposalLogCursor:
    """Session cursor for a bounded, rolling game list, including identical texts."""
    def __init__(self):
        self.source = None
        self.anchor = None
        self.seen = set()
        self.available = False
        self.incomplete = False
        self.reason = ''

    def observe(self, packet, *, baseline=False):
        self.available = False
        if not isinstance(packet, dict) or packet.get('available') is not True or packet.get('complete') is not True:
            self.reason = (packet.get('reason') if isinstance(packet, dict) else None) or '游戏日志暂不可读。'
            return []
        records, source = packet.get('records'), packet.get('id')
        if (not isinstance(source, str) or not source or not isinstance(records, list)
                or len(records) > 1000 or any(not isinstance(r, dict) or not isinstance(r.get('id'), str)
                    or not r['id'] or type(r.get('category')) is not int or r['category'] not in range(1,7) for r in records)):
            self.reason = '游戏日志格式未确认。'
            return []
        ids = [r['id'] for r in records]
        if len(ids) != len(set(ids)):
            self.reason = '游戏日志事件标识重复。'
            return []
        self.available = True
        self.reason = ''
        if source != self.source or baseline:
            # Attaching late cannot attribute pre-attachment history to this run.
            if not baseline: self.incomplete = True
            self.source, self.anchor, self.seen = source, ids[-1] if ids else None, set(ids)
            return []
        if self.anchor and self.anchor not in ids:
            self.incomplete = True
        new = [r for r in records if r['id'] not in self.seen]
        # The verified producer only appends/removes from the head. Retaining
        # the current window is enough and bounds memory during long sessions.
        self.seen = set(ids)
        self.anchor = ids[-1] if ids else None
        return [r for r in new if r['category'] == 2]
