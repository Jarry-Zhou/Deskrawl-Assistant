"""Regression checks against the copied Mono Dictionary native layout.

These fixtures model a dictionary's high water mark and free list, rather than
building Python dictionaries whose deleted slots would already be hidden.
"""
from types import SimpleNamespace
import math
import struct
import unittest

from deskrawl_assistant.native_memory import MemoryReadError, SnapshotChangedError
from deskrawl_assistant.recommendation_reader import _Copy


DICT = 0x1000
DICT_CLASS = 0x2000
ARRAY = 0x3000
ARRAY_CLASS = 0x4000
ENTRY_CLASS = 0x5000
HEADER = DICT + 24
BODY = ARRAY + 32
VALID_OBSCURED = bytes.fromhex(
    '0a6991de00000000a11e94b3320a8abc1ea194d333f0673500000000000000000000000000000000'
)


def entry(key, value=0, *, kind='double', hash_code=1, next_=-1):
    """Native Entry<T> bytes exclude the managed object header's 16 bytes."""
    raw = bytearray(56 if kind == 'obscured' else 24)
    struct.pack_into('<iiQ', raw, 0, hash_code, next_, key)
    if kind == 'obscured':
        raw[16:56] = value if isinstance(value, bytes) else bytes(40)
    elif kind == 'double':
        struct.pack_into('<d', raw, 16, value)
    elif kind == 'pointer':
        struct.pack_into('<Q', raw, 16, value)
    elif kind == 'float':
        struct.pack_into('<f', raw, 16, value)
    else:
        struct.pack_into('<i', raw, 16, value)
    return bytes(raw)


class ByteMemory:
    def __init__(self):
        self.bytes = {}
        self.after_read = None

    def put(self, address, raw):
        self.bytes.update((address + i, value) for i, value in enumerate(raw))

    def read(self, address, size):
        raw = bytes(self.bytes[address + i] for i in range(size))
        if self.after_read:
            self.after_read(address, size, raw)
        return raw


def fixture(entries, *, kind='double', count=None, free=0, free_list=-1,
            version=7, null_array=False):
    memory = ByteMemory()
    count = len(entries) if count is None else count
    memory.put(DICT, bytes(48))
    memory.put(DICT, struct.pack('<Q', DICT_CLASS))
    memory.put(HEADER, struct.pack('<Qiiii', 0 if null_array else ARRAY,
                                  count, free_list, free, version))
    memory.put(ARRAY_CLASS, bytes(0x108))
    memory.put(ARRAY_CLASS + 64, struct.pack('<Q', ENTRY_CLASS))
    memory.put(ARRAY_CLASS + 0x104,
               struct.pack('<i', 56 if kind == 'obscured' else 24))
    memory.put(ARRAY, bytes(32))
    memory.put(ARRAY, struct.pack('<Q', ARRAY_CLASS))
    memory.put(ARRAY + 24, struct.pack('<Q', len(entries)))
    memory.put(BODY, b''.join(entries))
    dictionary_fields = [
        {'name': name, 'offset': offset}
        for name, offset in (
            ('_entries', 24), ('_count', 32), ('_freeList', 36),
            ('_freeCount', 40), ('_version', 44)
        )
    ]
    entry_fields = [
        {'name': name, 'offset': offset}
        for name, offset in (
            ('hashCode', 16), ('next', 20), ('key', 24), ('value', 32)
        )
    ]
    reader = SimpleNamespace(
        memory=memory,
        resolved_profiles={'recommendation-types.json': {'types': []}},
        class_name=lambda klass: 'Dictionary`2' if klass == DICT_CLASS else 'Entry',
        fields=lambda klass: dictionary_fields if klass == DICT_CLASS else entry_fields,
    )
    return _Copy(reader), memory


def read_finished(copy, **kwargs):
    result = copy.dictionary(DICT, **kwargs)
    copy.finish()
    return result


class RecommendationDictionaryTests(unittest.TestCase):
    def test_live_entries_include_collision_links_and_hash_zero(self):
        copy, _ = fixture([
            entry(8, 12.5, hash_code=0),
            entry(20, 175, next_=0),
            entry(41, .25, next_=1),
        ])
        self.assertEqual(read_finished(copy, kind='double'),
                         {8: 12.5, 20: 175, 41: .25})

    def test_mono_deleted_slot_is_skipped_before_decoding_residual_value(self):
        copy, _ = fixture([
            entry(8, VALID_OBSCURED, kind='obscured'),
            entry(0, b'\xff' * 40, kind='obscured', hash_code=-1),
            entry(20, kind='obscured'),
        ], kind='obscured', free=1, free_list=1)
        result = read_finished(copy)
        self.assertEqual(set(result), {8, 20})
        self.assertAlmostEqual(result[8], .9300000071525574)
        self.assertEqual(result[20], 0)

    def test_deleted_zero_wrapper_does_not_inflate_active_count(self):
        # Reproduces the reported effective element count mismatch exactly.
        copy, _ = fixture([
            entry(8, kind='obscured'),
            entry(0, kind='obscured', hash_code=-1),
            entry(20, kind='obscured'),
        ], kind='obscured', free=1, free_list=1)
        self.assertEqual(read_finished(copy), {8: 0, 20: 0})

    def test_deleted_slot_does_not_decode_nonfinite_residual_values(self):
        for kind in ('double', 'float'):
            with self.subTest(kind=kind):
                copy, _ = fixture([
                    entry(8, 3, kind=kind),
                    entry(0, math.nan, kind=kind, hash_code=-1),
                ], kind=kind, free=1, free_list=1)
                self.assertEqual(read_finished(copy, kind=kind), {8: 3})

    def test_mono_free_chain_can_point_to_prior_deleted_slots(self):
        copy, _ = fixture([
            entry(8, 12),
            entry(8, math.nan, hash_code=-1),
            entry(20, 175),
            entry(0, math.nan, hash_code=-1, next_=1),
        ], free=2, free_list=3)
        self.assertEqual(read_finished(copy, kind='double'), {8: 12, 20: 175})

    def test_dictionary_with_all_entries_deleted_is_empty(self):
        copy, _ = fixture([
            entry(0, math.nan, hash_code=-1),
            entry(0, math.nan, hash_code=-1, next_=0),
            entry(0, math.nan, hash_code=-1, next_=1),
        ], free=3, free_list=2)
        self.assertEqual(read_finished(copy, kind='double'), {})

    def test_deleted_pointer_with_cleared_key_is_not_returned(self):
        copy, _ = fixture([
            entry(0x7000, 0x8000, kind='pointer'),
            entry(0, 0xDEADBEEF, kind='pointer', hash_code=-1),
        ], kind='pointer', free=1, free_list=1)
        self.assertEqual(read_finished(copy, kind='pointer', key_kind='pointer'),
                         {0x7000: 0x8000})

    def test_unused_capacity_is_not_an_active_entry(self):
        copy, _ = fixture([
            entry(8, 12),
            entry(20, 175),
            bytes(24),
            entry(0, math.nan),
        ], count=2)
        self.assertEqual(read_finished(copy, kind='double'), {8: 12, 20: 175})

    def test_never_allocated_empty_dictionary_is_empty(self):
        copy, _ = fixture([], null_array=True)
        self.assertEqual(read_finished(copy, kind='double'), {})

    def test_stable_free_count_mismatch_is_rejected(self):
        scenarios = [
            ([entry(8, 12), entry(20, 175)], 1, 1),
            ([entry(8, 12), entry(0, 0, hash_code=-1)], 0, -1),
        ]
        for entries, free, free_list in scenarios:
            with self.subTest(free=free):
                copy, _ = fixture(entries, free=free, free_list=free_list)
                with self.assertRaises(MemoryReadError) as raised:
                    read_finished(copy, kind='double')
                self.assertNotIsInstance(raised.exception, SnapshotChangedError)

    def test_duplicate_live_keys_are_rejected(self):
        copy, _ = fixture([entry(8, 12), entry(8, 15)])
        with self.assertRaises(MemoryReadError) as raised:
            read_finished(copy, kind='double')
        self.assertNotIsInstance(raised.exception, SnapshotChangedError)

    def test_header_change_during_copy_requests_a_retry(self):
        copy, memory = fixture([entry(8, 12)])
        def change_version(address, size, _):
            if address == BODY:
                memory.after_read = None
                memory.put(DICT + 44, struct.pack('<i', 8))
        memory.after_read = change_version
        with self.assertRaises(SnapshotChangedError):
            read_finished(copy, kind='double')

    def test_entries_change_during_copy_requests_a_retry(self):
        copy, memory = fixture([entry(8, 12)])
        def change_entries(address, size, _):
            if address == BODY:
                memory.after_read = None
                memory.put(BODY, entry(8, 15))
        memory.after_read = change_entries
        with self.assertRaises(SnapshotChangedError):
            read_finished(copy, kind='double')

    def test_mid_copy_count_disagreement_is_a_retry_not_stable_corruption(self):
        copy, memory = fixture([entry(8, 12), entry(0, 0, hash_code=-1)])
        def repair_header(address, size, _):
            if address == BODY:
                memory.after_read = None
                memory.put(HEADER, struct.pack('<Qiiii', ARRAY, 2, 1, 1, 8))
        memory.after_read = repair_header
        with self.assertRaises(SnapshotChangedError):
            read_finished(copy, kind='double')

    def test_mid_copy_wrapper_damage_is_a_retry_not_stable_corruption(self):
        copy, memory = fixture([
            entry(8, b'\xff' * 40, kind='obscured')
        ], kind='obscured')
        def repair_entries(address, size, _):
            if address == BODY:
                memory.after_read = None
                memory.put(BODY, entry(8, VALID_OBSCURED, kind='obscured'))
        memory.after_read = repair_entries
        with self.assertRaises(SnapshotChangedError):
            read_finished(copy)

    def test_stable_active_value_corruption_is_rejected(self):
        for kind, value in (('obscured', b'\xff' * 40), ('double', math.nan)):
            with self.subTest(kind=kind):
                copy, _ = fixture([entry(8, value, kind=kind)], kind=kind)
                with self.assertRaises(MemoryReadError) as raised:
                    read_finished(copy, kind=kind)
                self.assertNotIsInstance(raised.exception, SnapshotChangedError)


if __name__ == '__main__':
    unittest.main()
