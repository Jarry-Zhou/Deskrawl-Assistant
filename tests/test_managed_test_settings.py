"""Recovery of supervised test settings, without a server or game process."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tools.managed_test_settings import ManagedTestSettings
from test_managed_mode import settings


class ManagedTestSettingsTests(unittest.TestCase):
    def fixture(self):
        current = settings(equip=True)
        current['auto_equip']['slot_locks'] = {'8': 'LegendaryNeck5', '6': 'LegendaryRing2'}
        current['cleanup']['equipment_policies'] = {
            key: {'action': action, 'fallback': action}
            for key, action in (('normal', 'sell'), ('rare', 'salvage'))}
        current['merchant'].update(trigger_percent=85, spend_to_percent=0)
        current['progression']['talent_targets'] = {'4': {'HunterTalent0': 10}}
        return current

    def test_temporary_threshold_preserves_named_gear_disposal_and_growth(self):
        current = self.fixture(); original = deepcopy(current)
        override = ManagedTestSettings(current, {('merchant', 'trigger_percent'): 1})
        temporary = override.temporary()
        self.assertEqual(temporary['merchant']['trigger_percent'], 1)
        current['merchant']['trigger_percent'] = 1
        self.assertEqual(temporary, current)
        self.assertEqual(override.restore(temporary), original)

    def test_restore_keeps_new_user_changes_and_does_not_restore_stale_groups(self):
        current = self.fixture(); override = ManagedTestSettings(current, {('merchant', 'trigger_percent'): 1})
        latest = override.temporary()
        latest['auto_equip']['slot_locks']['8'] = 'LegendaryNeck1'
        latest['cleanup']['equipment_policies']['rare']['action'] = 'sell'
        latest['progression']['talent_targets']['4']['HunterTalent0'] = 8
        latest['merchant']['weights']['7'] = 10
        expected = deepcopy(latest); expected['merchant']['trigger_percent'] = 85
        self.assertEqual(override.restore(latest), expected)
        latest['merchant']['trigger_percent'] = 92
        self.assertEqual(override.restore(latest), latest)

    def test_cannot_replace_entire_groups_or_invent_missing_fields(self):
        current = self.fixture()
        for changes in ({('auto_equip',): {}}, {('cleanup', 'equipment_policies'): {}},
                        {('merchant', 'unknown_field'): 1}):
            with self.assertRaises(ValueError): ManagedTestSettings(current, changes)

    def test_backup_is_exact_and_never_overwrites_an_existing_backup(self):
        current = self.fixture(); override = ManagedTestSettings(current, {('merchant', 'trigger_percent'): 1})
        with tempfile.TemporaryDirectory() as folder:
            path = override.backup(Path(folder)/'before.json')
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), current)
            with self.assertRaises(FileExistsError): override.backup(path)
