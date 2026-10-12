"""Scoped overrides for supervised tests; never restore an entire old config.

Construct from the current saved settings, back them up before saving the
temporary copy, and restore against a fresh read. The caller owns API access.
"""
from copy import deepcopy
import json
from pathlib import Path


_MISSING = object()


def _read(settings, path):
    value = settings
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return _MISSING
        value = value[key]
    return value


def _write(settings, path, value):
    parent = settings
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = deepcopy(value)


class ManagedTestSettings:
    def __init__(self, current, overrides):
        self.before = deepcopy(current)
        self.overrides = deepcopy(overrides)
        for path, value in self.overrides.items():
            if not isinstance(path, tuple) or not path or any(not isinstance(key, str) or not key for key in path):
                raise ValueError('测试修改必须指定完整的字段路径。')
            previous = _read(self.before, path)
            if previous is _MISSING:
                raise ValueError('测试字段不存在，未使用默认配置替代用户数据。')
            if isinstance(previous, (dict, list)) or isinstance(value, (dict, list)):
                raise ValueError('测试不能整组替换配置，请只指定需要调整的字段。')

    def temporary(self):
        result = deepcopy(self.before)
        for path, value in self.overrides.items():
            _write(result, path, value)
        return result

    def restore(self, latest):
        result = deepcopy(latest)
        for path, temporary_value in self.overrides.items():
            current_value = _read(latest, path)
            if type(current_value) is type(temporary_value) and current_value == temporary_value:
                _write(result, path, _read(self.before, path))
        return result

    def backup(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            json.dump(self.before, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        return path
