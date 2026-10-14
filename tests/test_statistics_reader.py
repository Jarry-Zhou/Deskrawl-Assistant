import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from deskrawl_assistant.native_memory import MemoryReadError, SnapshotChangedError
from deskrawl_assistant.statistics_reader import _totals, read_player_statistics


class NativeStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.fields = [{'name': 'duration', 'offset': 40, 'token': 1}, {'name': 'counts', 'offset': 72, 'token': 2}]
        self.layout = {'rva': 100, 'duration': 40, 'counts': 72, 'fields': self.fields,
                       'rarity': {'Common': 0, 'Uncommon': 1, 'Rare': 2, 'Legendary': 3, 'Divine': 4, 'RuneSet': 5}}
        self.reader = SimpleNamespace(module={'base': 1000}, session_id='current-session',
            class_name=lambda klass: 'PlayerStatistics', fields=lambda klass: self.fields,
            check_game_files=lambda: None)
        self.duration = 123456.9
        self.counts = [10000, 2000, 900, 30, 17, 9]
        self.pointers = {1100: 2000, 2184: 3000, 3000: 4000, 4000: 2000, 4072: 5000}
        self.copy = SimpleNamespace(ptr=lambda address: self.pointers[address],
            read=lambda address, size, stable=True: struct.pack('<d', self.duration),
            array=lambda *args, **kwargs: [struct.pack('<i', count) for count in self.counts])

    def test_game_seconds_and_exact_rarity_counters(self):
        self.assertEqual(_totals(self.reader, self.copy, self.layout),
                         {'play_seconds': 123456, 'divine_count': 17, 'rune_set_count': 9})

    def test_changed_live_fields_or_array_length_never_guess(self):
        self.reader.fields = lambda klass: self.fields[::-1]
        with self.assertRaises(MemoryReadError): _totals(self.reader, self.copy, self.layout)
        self.reader.fields = lambda klass: self.fields
        self.counts = self.counts[:-1]
        with self.assertRaises(MemoryReadError): _totals(self.reader, self.copy, self.layout)

    def test_null_instance_invalid_time_and_negative_counter_are_rejected(self):
        self.pointers[3000] = 0
        with self.assertRaises(MemoryReadError): _totals(self.reader, self.copy, self.layout)
        self.pointers[3000] = 4000
        for duration in (float('nan'), float('inf'), -1):
            self.duration = duration
            with self.subTest(duration=duration), self.assertRaises(MemoryReadError):
                _totals(self.reader, self.copy, self.layout)
        self.duration = 0
        self.counts[4] = -1
        with self.assertRaises(MemoryReadError): _totals(self.reader, self.copy, self.layout)

    def test_changing_character_retries_whole_read(self):
        result = {'available': True, 'session': 'current-session', 'divine_count': 17}
        with patch('deskrawl_assistant.statistics_reader._layout', return_value=self.layout), \
             patch('deskrawl_assistant.statistics_reader._snapshot', side_effect=[SnapshotChangedError('Switching'), result]) as read:
            self.assertEqual(read_player_statistics(self.reader), result)
            self.assertEqual(read.call_count, 2)

    def test_unavailable_or_changed_files_do_not_return_zero_totals(self):
        self.reader.check_game_files = lambda: (_ for _ in ()).throw(MemoryReadError('Updated files'))
        result = read_player_statistics(self.reader)
        self.assertFalse(result['available'])
        self.assertNotIn('play_seconds', result); self.assertNotIn('divine_count', result)


if __name__ == '__main__': unittest.main()
