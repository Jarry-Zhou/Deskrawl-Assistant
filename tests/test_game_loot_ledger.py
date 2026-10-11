import struct
import unittest
from unittest.mock import Mock, patch

from deskrawl_assistant.game_loot_ledger import read_loot_ledger
from deskrawl_assistant.native_memory import MemoryReadError, SnapshotChangedError


class GameLootLedgerTests(unittest.TestCase):
    def setUp(self):
        self.reader=Mock();self.reader.string.return_value='offline-run-guid'
        self.reader.base_item.return_value={'is_equipment':True,'rarity':3,'internal_name':'LegendaryNeck1'}
        self.reader.fields.side_effect=lambda obj:[{'name':k,'offset':v} for k,v in
            ({'Item1':16,'Item2':24,'Item3':28,'Item4':29} if obj==6100 else
             {'hashCode':16,'next':20,'key':24,'value':28}).items()]
        self.copy=Mock();self.copy.verify.side_effect=lambda obj,name:obj
        pointers={1104:2000,2088:3000,3016:9000,2160:4000,2176:5000,5016:6000,
                  6000:6001,6065:6100,8032:8000,7000:7001,7065:7100}
        self.copy.ptr.side_effect=lambda address:pointers[address]
        self.copy.read.side_effect=lambda address,size:struct.pack('<Qiiii',7000,2,0,0,1) if address==8024 else b'\0'*size
        self.entries=[struct.pack('<Iiii',0,-1,0,1),struct.pack('<Iiii',1,-1,2,2)]
        self.copy.array.side_effect=lambda obj,stride,*args,**kw:[struct.pack('<i',n) for n in (0,0,0,1,0,0)] if obj==4000 else self.entries
        self.copy.list.return_value=[struct.pack('<QiBB2x',10000,2,1,0)]
        self.action_read=Mock();self.action_read.singleton.return_value=8000

    def read(self):
        with patch('deskrawl_assistant.game_loot_ledger._Copy',return_value=self.copy):
            return read_loot_ledger(self.reader,self.action_read,1000)

    def test_exact_receipts_and_policy_read_without_invocation_or_write(self):
        result=self.read()
        self.assertTrue(result['available'])
        self.assertEqual(result['policy'],{'0':1,'2':2})
        self.assertEqual(result['receipts'][0]['action'],'salvage')
        self.assertTrue(result['receipts'][0]['item']['is_ancient'])
        self.reader.memory.write.assert_not_called();self.action_read.singleton.assert_called_once_with('CarriageAutomation')
        self.copy.finish.assert_called_once()

    def test_invalid_receipt_and_duplicate_policy_fail_closed(self):
        self.copy.list.return_value=[struct.pack('<QiBB2x',10000,9,0,0)]
        with self.assertRaises(MemoryReadError):self.read()
        self.copy.list.return_value=[]
        self.entries=[struct.pack('<Iiii',0,-1,0,1),struct.pack('<Iiii',1,-1,0,2)]
        with self.assertRaisesRegex(MemoryReadError,'重复'):self.read()

    def test_snapshot_guard_failure_is_not_an_empty_or_confirmed_ledger(self):
        self.copy.finish.side_effect=SnapshotChangedError('changing')
        with self.assertRaises(SnapshotChangedError):self.read()


if __name__=='__main__':unittest.main()
