"""Logical floor identities mirror SaveSystem's completed-map keys."""
import re

MYTHIC = 'Mythic'
MAP_ID = 'MythicDungeon'
WORLD_DIFFICULTIES = ('Normal','Nightmare','Inferno')


def floor_id(floor):
    if type(floor) is not int or not 1 <= floor <= 100:
        raise ValueError('神话裂隙层数必须为 1 至 100。')
    return f'{MAP_ID}::mythic::{floor}'


def floor_number(key):
    match = re.fullmatch(r'MythicDungeon::mythic::([1-9][0-9]?|100)', str(key))
    return int(match.group(1)) if match else None


def unlocked_floors(completed, *, eligible):
    return [n for n in range(1,101) if eligible and (n == 1 or floor_id(n-1) in completed)]
