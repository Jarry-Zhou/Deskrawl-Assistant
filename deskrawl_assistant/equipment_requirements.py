"""Pure translations of the verified EquipmentManager.dds/ddt level checks."""


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(label + '尚未完整读取，暂不能自动穿戴。')
    return value


def required_level(row, max_level):
    """Mirror native priority: black mist, back slot, base rarity, item level.

    GameConfig.MaxPlayerLevel caps ItemLevel / 10. Generated rarity must not
    replace ItemData.Rarity when deciding the divine equipment requirement.
    """
    maximum = _integer(max_level, 1, 10000, '角色等级上限')
    mist = row.get('is_black_mist')
    if type(mist) is not bool:
        raise ValueError('装备黑雾状态尚未完整读取，暂不能自动穿戴。')
    if mist:
        return maximum
    slot = _integer(row.get('equip_slot'), 1, 11, '装备部位')
    if slot == 11:
        return 1
    rarity = _integer(row.get('base_rarity'), 0, 5, '装备基础品质')
    if rarity == 4:
        return maximum
    level = _integer(row.get('item_level', row.get('level')), -(2**31), 2**31 - 1, '装备等级')
    return min(maximum, max(1, level // 10)) if level > 0 else 1


def equip_eligibility(row, character):
    """Unknown inputs never authorize a managed equip or preparation transfer."""
    result = {'available': False, 'can_equip': False, 'required_level': None,
              'character_level': None, 'reason': ''}
    try:
        if not isinstance(character, dict) or character.get('available') is not True:
            raise ValueError('角色等级尚未完整读取，暂不能自动穿戴。')
        level = _integer(character.get('level'), 1, 10000, '角色等级')
        needed = required_level(row, character.get('max_level'))
        result.update(available=True, can_equip=level >= needed,
                      required_level=needed, character_level=level)
        if level < needed:
            result['reason'] = f'角色 Lv.{level}，装备需要 Lv.{needed}，暂不能穿戴。'
    except (ValueError, AttributeError, TypeError) as exc:
        result['reason'] = str(exc)
    return result
