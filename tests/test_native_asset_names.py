"""Unity inline asset names may contain spaces. Never opens a game process."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from deskrawl_assistant.native_reader import NativeReader


class NativeAssetNameTests(unittest.TestCase):
    def reader(self, block):
        reader=NativeReader.__new__(NativeReader)
        reader.memory=SimpleNamespace(u64=Mock(return_value=0x100000),read=Mock(return_value=block),
            cstring=Mock(side_effect=AssertionError('Inline name must not be treated as a pointer')))
        return reader

    def test_life_node_inline_names_do_not_become_invalid_pointers(self):
        for key in ('LifeSkill','LifeSkill 8','LifeSkill 31','LifeSkill 44','LifeSkill 66'):
            with self.subTest(key=key):
                reader=self.reader(key.encode('ascii').ljust(32,b'\0'))
                self.assertEqual(reader.asset_name(0x200000),key)
                reader.memory.cstring.assert_not_called()

    def test_heap_name_pointer_keeps_existing_fallback(self):
        reader=self.reader(struct.pack('<Q',0x12345678).ljust(32,b'\0'))
        reader.memory.cstring=Mock(return_value='Long asset name stored in the native heap')
        self.assertEqual(reader.asset_name(0x200000),'Long asset name stored in the native heap')
        reader.memory.cstring.assert_called_once_with(0x12345678,128)
