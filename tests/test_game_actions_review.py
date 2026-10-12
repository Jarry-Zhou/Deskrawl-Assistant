"""Independent native-action review regressions; no game process is opened."""
from copy import deepcopy
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from deskrawl_assistant.game_actions import GameActions, normalise_run
from deskrawl_assistant.native_memory import MemoryReadError
from deskrawl_assistant.native_reader import NativeReader
from deskrawl_assistant.native_dispatcher import build_trampoline


class SlotReader:
    """The slot changes AFTER the accepted snapshot, before its guarded reread."""
    def __init__(self, *, item_changed=False, slot_locked=False, generated_change=None):
        self.session_id = 'offline-review'
        self.classes = {'InventorySlot': 0x777}
        self.snapshot_stamps = []
        self.uid = 'gear-uid' if generated_change is not None else ''
        old = bytearray(48); struct.pack_into('<Q', old, 0, 0x777)
        struct.pack_into('<Q', old, 16, 0x900); struct.pack_into('<i', old, 24, 1)
        struct.pack_into('<Q', old, 32, 0x800 if self.uid else 0)
        self.old_header = bytes(old)
        changed = bytearray(old)
        if item_changed: struct.pack_into('<Q', changed, 16, 0x901)
        if slot_locked: changed[40] = 1
        self.current_header = bytes(changed)
        self.old_generated = {'instance_id': 'same-instance', 'locked': False, 'modifiers_complete': True,
            'rarity': 3, 'is_ancient': False, 'is_black_mist': False,
            'modifiers': [{'stat': 1, 'type': 0, 'value': 10}], 'upgrade_level': 0, 'socket_count': 0, 'socketed_gems': []}
        self.current_generated = dict(deepcopy(self.old_generated), **(generated_change or {}))
        self.row = {'container': 'inventory', 'slot_index': 0, 'item_uid': self.uid,
            'count': 1, 'slot_locked': False, **self.base_item(0x900)}
        if self.uid: self.row.update(self.old_generated)
        self.row['transfer_key'] = self.transfer_key('inventory', 0, 0x500, self.old_header, self.row)
        self.memory = SimpleNamespace(read=self._read, u64=lambda a: 0x777 if a == 0x500 else 1)
        self.read = SimpleNamespace(guards=[], singleton=lambda name: 0x300, ptr=lambda a: 0x400,
            read=self._guarded_read, finish=self._finish)

    def transfer_key(self, *args): return NativeReader.transfer_key(self, *args)
    def string(self, ptr): return self.uid if ptr == 0x800 else ''
    def snapshot(self):
        self.snapshot_stamps = [(0x500, self.old_header)]
        return {'complete': True, 'containers': {'inventory': {'slots': [deepcopy(self.row)]}, 'storage': {'slots': []}}}
    def array(self, *args, **kwargs): return [struct.pack('<Q', 0x500)], struct.pack('<Q', 0x500)
    def registry(self): return {self.uid: 0x600}, {'object': 0x700, 'header': b'R'*24}
    def generated(self, obj):
        self.snapshot_stamps.append((0x600, b'G'*128))
        return deepcopy(self.current_generated)
    def base_item(self, obj):
        return {'internal_name': 'GemOriginal' if obj == 0x900 else 'GemReplacement',
            'is_equipment': bool(self.uid), 'item_type': 3 if self.uid else 6,
            'name_key': 'LegendaryNeck1' if self.uid else None}
    def _read(self, address, size):
        if address == 0x500: return self.current_header[:size]
        if address == 0x600: return b'G'*size
        if address == 0x700+24: return b'R'*size
        return b'\0'*size
    def _guarded_read(self, address, size):
        value = self._read(address, size); self.read.guards.append((address, value)); return value
    def _finish(self):
        if any(self._read(address, len(raw)) != raw for address, raw in self.read.guards):
            raise MemoryReadError('offline: changed guard')


class InventoryRaceReviewTests(unittest.TestCase):
    def assert_reread_rejected(self, reader):
        game = object.__new__(GameActions); game.reader = reader
        with self.assertRaises(MemoryReadError):
            selected, *_ = game._selected_inventory({'item': deepcopy(reader.row)}, reader.read)
            reader.read.finish()
            # Safety cannot be based on stale snapshot.locked/modifiers.
            game._disposition(selected, {'disposition_authorized': True, 'rule_matched': False, 'rule_pending': False})

    def test_empty_uid_slot_replacement_cannot_sell_another_gem(self):
        self.assert_reread_rejected(SlotReader(item_changed=True))

    def test_slot_became_locked_between_snapshot_and_preparation_is_preserved(self):
        self.assert_reread_rejected(SlotReader(slot_locked=True))

    def test_generated_locked_flag_change_same_uid_instance_is_preserved(self):
        self.assert_reread_rejected(SlotReader(generated_change={'locked': True}))

    def test_rerolled_affixes_same_uid_instance_require_new_rule_evaluation(self):
        self.assert_reread_rejected(SlotReader(generated_change={'modifiers': [{'stat': 1, 'type': 0, 'value': 20}]}))


class GroundReceiptReviewTests(unittest.TestCase):
    @staticmethod
    def ground_game(consumed, inventory, remaining):
        game = object.__new__(GameActions)
        game.reader = SimpleNamespace(memory=SimpleNamespace(
            read=lambda a, n: b'\1' if consumed else b'\0', u64=lambda a: 1),
            snapshot=Mock(return_value={'complete': True, 'containers': {'inventory': {'slots': inventory}, 'storage': {'slots': []}}}))
        game._context = Mock(return_value=(SimpleNamespace(finish=lambda: None), 0x100, None, 1))
        game._ground = Mock(return_value=remaining)
        return game

    @staticmethod
    def clock():
        calls = iter([0, 0, 3])
        return lambda: next(calls, 3)

    def test_destroyed_drop_without_inventory_receipt_is_not_collected(self):
        selected = {'_address': 0x200, 'observation_id': 'world-drop', 'item_uid': 'lost-gear',
            'internal_name': 'LegendaryNeck1', 'item_type': 3, 'count': 1, '_before_total_count': 0}
        game = self.ground_game(True, [], [])
        with patch('deskrawl_assistant.game_actions.time.monotonic', side_effect=self.clock()), patch('deskrawl_assistant.game_actions.time.sleep'):
            self.assertFalse(game._confirm_effect('collect_ground', selected, {}))

    def test_partial_gem_pickup_is_confirmed_by_inventory_and_remaining_count(self):
        selected = {'_address': 0x200, 'observation_id': 'world-drop', 'item_uid': '',
            'internal_name': 'GemOriginal', 'item_type': 6, 'count': 10, '_before_total_count': 0}
        after = dict(selected, count=7)
        inventory = [{'internal_name': 'GemOriginal', 'item_uid': '', 'count': 3}]
        game = self.ground_game(False, inventory, [after])
        with patch('deskrawl_assistant.game_actions.time.monotonic', side_effect=self.clock()), patch('deskrawl_assistant.game_actions.time.sleep'):
            self.assertTrue(game._confirm_effect('collect_ground', selected, {}))
        self.assertEqual(selected['_confirmed_count'],3)

    def test_virtual_material_requires_receive_balance_to_increase_by_removed_quantity(self):
        for balance,expected in [(20,False),(22,False),(23,True)]:
            selected={'_address':0x200,'observation_id':'virtual-drop','internal_name':'Iron',
                      'item_type':1,'count':3,'_before_virtual':20}
            game=self.ground_game(True,[],[])
            game._virtual_balance=Mock(return_value=balance)
            with self.subTest(balance=balance),patch('deskrawl_assistant.game_actions.time.monotonic',side_effect=self.clock()),patch('deskrawl_assistant.game_actions.time.sleep'):
                self.assertIs(game._confirm_effect('collect_ground',selected,{}),expected)

    def test_healing_drop_must_heal_or_be_consumed_at_full_health(self):
        for before,after,expected in [({'current':50,'maximum':100},{'current':50,'maximum':100},False),
                                      ({'current':50,'maximum':100},{'current':80,'maximum':100},True),
                                      ({'current':100,'maximum':100},{'current':100,'maximum':100},True)]:
            selected={'_address':0x200,'observation_id':'health-drop','internal_name':'HealthPotionDrop',
                      'item_type':1,'count':1,'_before_virtual':before}
            game=self.ground_game(True,[],[]);game._virtual_balance=Mock(return_value=after)
            with self.subTest(before=before,after=after),patch('deskrawl_assistant.game_actions.time.monotonic',side_effect=self.clock()),patch('deskrawl_assistant.game_actions.time.sleep'):
                self.assertIs(game._confirm_effect('collect_ground',selected,{}),expected)

    def test_equipment_receipt_requires_same_uid_and_template_in_inventory(self):
        selected={'_address':0x200,'observation_id':'gear-drop','internal_name':'LegendaryNeck1',
                  'item_uid':'new-gear','item_type':3,'count':1,'_before_total_count':0}
        for row,expected in [({'item_uid':'other','internal_name':'LegendaryNeck1'},False),
                             ({'item_uid':'new-gear','internal_name':'LegendaryNeck2'},False),
                             ({'item_uid':'new-gear','internal_name':'LegendaryNeck1'},True)]:
            game=self.ground_game(True,[row],[])
            with self.subTest(row=row),patch('deskrawl_assistant.game_actions.time.monotonic',side_effect=self.clock()),patch('deskrawl_assistant.game_actions.time.sleep'):
                self.assertIs(game._confirm_effect('collect_ground',selected,{}),expected)


class EquipReceiptReviewTests(unittest.TestCase):
    def test_equipped_new_item_without_conserved_previous_item_cannot_succeed(self):
        for held,expected in [([],False),([{'item_uid':'old-gear','slot_index':0}],True)]:
            game=object.__new__(GameActions)
            game.reader=SimpleNamespace(snapshot=Mock(return_value={'complete':True,'containers':
                {'inventory':{'slots':held},'storage':{'slots':[]}}}))
            current={'available':True,'equipment':[{'item_uid':'new-gear','equipped_slot':8}]}
            selected={'item_uid':'new-gear','slot_index':0,'_replaced_uid':'old-gear'}
            with self.subTest(held=held),patch('deskrawl_assistant.character_reader.read_character',return_value=current),patch('deskrawl_assistant.game_actions.time.monotonic',side_effect=GroundReceiptReviewTests.clock()),patch('deskrawl_assistant.game_actions.time.sleep'):
                self.assertIs(game._confirm_effect('equip',selected,{'target_slot':8}),expected)


class RunReceiptReviewTests(unittest.TestCase):
    def test_builtin_repeat_confirms_win_before_reward_completion_flag(self):
        run = {'id': 'round', 'map_id': 'a', 'finished': False, 'final_kill_settled': True,
               'wave_count': 10, 'wave_index': 10, 'wave_active': False, 'enemy_count': 0}
        value = normalise_run(run, {'a'})
        self.assertTrue(value['completion_confirmed'])
        self.assertEqual(value['status'], 'settling')
        self.assertFalse(value['finished'])
        self.assertEqual(normalise_run(run, {'a'}, dead=True)['status'], 'failed')

    def test_builtin_repeat_still_requires_all_final_wave_evidence(self):
        run = {'id': 'round', 'map_id': 'a', 'finished': False, 'final_kill_settled': True,
               'wave_count': 10, 'wave_index': 10, 'wave_active': False, 'enemy_count': 0}
        for change in ({'wave_count': 0}, {'wave_count': True}, {'wave_index': 9},
                       {'wave_active': True}, {'enemy_count': 1}, {'final_kill_settled': False}):
            with self.subTest(change=change):
                self.assertIsNot(normalise_run({**run, **change}, {'a'}).get('completion_confirmed'), True)
        self.assertIsNot(normalise_run(run, set()).get('completion_confirmed'), True)

    def test_cleared_transient_final_kill_flag_still_accepts_settled_completed_wave(self):
        run={'id':'round','map_id':'a','finished':True,'final_kill':False,
             'wave_count':10,'wave_index':10,'wave_active':False,'enemy_count':0}
        self.assertEqual(normalise_run(run,{'a'})['status'],'success')
        for change in ({'wave_count':0},{'wave_index':9},{'wave_active':True},{'enemy_count':1}):
            with self.subTest(change=change):self.assertEqual(normalise_run({**run,**change},{'a'})['status'],'settling')
        self.assertEqual(normalise_run(run,set())['status'],'settling')
        self.assertEqual(normalise_run(run,{'a'},dead=True)['status'],'failed')


class DispatcherABIReviewTests(unittest.TestCase):
    def test_win64_stack_alignment_and_original_peek_fifth_argument(self):
        from capstone import Cs, CS_ARCH_X86, CS_MODE_64
        instructions = list(Cs(CS_ARCH_X86, CS_MODE_64).disasm(build_trampoline(0x10000), 0))
        before_call = []
        for ins in instructions:
            if ins.mnemonic == 'call': break
            before_call.append(ins)
        push = [ins.op_str for ins in before_call if ins.mnemonic == 'push']
        self.assertEqual(push, ['rbx', 'rsi', 'rdi', 'r12', 'r13', 'r14', 'r15'])
        sub = next(ins for ins in before_call if ins.mnemonic == 'sub' and ins.op_str.startswith('rsp'))
        allocation = int(sub.op_str.split(',')[1].strip(), 16)
        self.assertEqual((8 - len(push)*8 - allocation) % 16, 0)
        displaced = 40 + len(push)*8 + allocation
        self.assertTrue(any(ins.mnemonic == 'mov' and ins.op_str == f'rax, qword ptr [rsp + 0x{displaced:x}]' for ins in before_call))
        self.assertTrue(any(ins.mnemonic == 'mov' and ins.op_str == 'qword ptr [rsp + 0x20], rax' for ins in before_call))
        calls = [ins.op_str for ins in instructions if ins.mnemonic == 'call']
        self.assertEqual(calls[0], 'qword ptr [r12 + 0x50]')


if __name__ == '__main__': unittest.main()
