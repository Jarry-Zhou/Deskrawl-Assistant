"""Shared partition choices; game permissions decide which slots are usable."""
from copy import deepcopy
import json

from .models import ValidationError

DEFAULT_STORAGE_PAGES = {'equipment': (1, 2, 3), 'rune': (4,), 'gem': (5,)}

SHARED_STORAGE_GROUPS = (('rune', 'runes'), ('gem', 'gems'))


def organizer_with_shared_pages(automation, cleanup):
    """Managed cleanup is the persisted authority for these two destinations."""
    result = deepcopy(automation)
    for kind, group in SHARED_STORAGE_GROUPS:
        result[group]['pages'] = list(cleanup[kind + '_pages'])
    return result


def validate_shared_pages(automation, cleanup):
    # Protected runes always need storage, even if ordinary runes are sold and
    # the independent organizer is off. Gems need it if either user stores them.
    if not cleanup['rune_pages']:
        raise ValidationError('请选择符文共用存放页，用于收纳套装／宏伟符文。')
    if not cleanup['gem_pages'] and (cleanup['gem_action'] == 'store' or automation['gems']['enabled']):
        raise ValidationError('请选择宝石共用存放页，或先关闭宝石自动入库并将托管宝石改为出售。')


def write_settings_files(values):
    """Stage both views before replacing either, restoring files on failure."""
    originals = {path: path.read_bytes() if path.exists() else None for path in values}
    replaced = []
    try:
        for path, value in values.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_suffix('.json.tmp').write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        for path in values:
            path.with_suffix('.json.tmp').replace(path)
            replaced.append(path)
    except Exception:
        for path in reversed(replaced):
            original = originals[path]
            if original is None:
                path.unlink()
            else:
                temp = path.with_suffix('.json.tmp')
                temp.write_bytes(original)
                temp.replace(path)
        raise
    finally:
        for path in values:
            path.with_suffix('.json.tmp').unlink(missing_ok=True)
