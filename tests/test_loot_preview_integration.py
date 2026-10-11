"""Independent regression checks for transitions during a full loot copy."""
import json
import struct
import unittest

from deskrawl_assistant.loot_plan_reader import read_loot_plan
from tests.test_loot_plan_reader import Fixture


class LootPreviewTransitionTests(unittest.TestCase):
    def test_entering_town_during_copy_discards_all_previous_items(self):
        fixture = Fixture()
        fixture.set_waves([[fixture.item()], []])
        triggered = []

        def enter_town(address, size):
            if address == fixture.loot_objects[-1] + 16 and not triggered:
                triggered.append(True)
                fixture.integer(fixture.area + 120, 1)

        fixture.memory.after_read = enter_town
        result = read_loot_plan(fixture.reader)
        self.assertTrue(triggered)
        self.assertFalse(result['available'])
        self.assertEqual(result['phase'], 'waiting')
        self.assertEqual(result['waves'], [])
        self.assertIsNone(result['run'])
        self.assertFalse(any(result['totals'].values()))

    def test_modifier_changed_during_copy_retries_without_mixed_values(self):
        fixture = Fixture()
        item = fixture.item(modifiers=[('CritChance', 'Flat', .05)])
        fixture.set_waves([[item]])
        array = struct.unpack('<Q', fixture.memory.read(item + 56, 8))[0]
        modifier = struct.unpack('<Q', fixture.memory.read(array + 32, 8))[0]
        triggered = []

        def change_modifier(address, size):
            if address == modifier + 32 and not triggered:
                triggered.append(True)
                fixture.memory.write_fixture(address, struct.pack('<f', .25))

        fixture.memory.after_read = change_modifier
        result = read_loot_plan(fixture.reader)
        self.assertTrue(triggered)
        self.assertTrue(result['available'], result['reason'])
        copied = result['waves'][0]['items'][0]['modifiers'][0]
        self.assertEqual(copied['value'], .25)
        self.assertIn('+25%', copied['text'])
        serialized = json.dumps(result)
        for private in ('private-drop', 'private-run', 'private-local'):
            self.assertNotIn(private, serialized)

    def test_continuously_changing_modifier_clears_entire_preview(self):
        fixture = Fixture()
        item = fixture.item(modifiers=[('CritChance', 'Flat', .05)])
        fixture.set_waves([[item]])
        array = struct.unpack('<Q', fixture.memory.read(item + 56, 8))[0]
        modifier = struct.unpack('<Q', fixture.memory.read(array + 32, 8))[0]
        counter = [0]

        def change_modifier(address, size):
            if address == modifier + 32:
                counter[0] += 1
                fixture.memory.write_fixture(address, struct.pack('<f', .1 * (counter[0] % 2 + 1)))

        fixture.memory.after_read = change_modifier
        result = read_loot_plan(fixture.reader)
        self.assertGreater(counter[0], 1)
        self.assertFalse(result['available'])
        self.assertEqual(result['waves'], [])
        self.assertIsNone(result['run'])


if __name__ == '__main__':
    unittest.main()
