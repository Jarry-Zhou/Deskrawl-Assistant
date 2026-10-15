"""Continuation uses original completion handlers and guards the old plan."""
import hashlib
import struct
from unittest import TestCase
from unittest.mock import Mock, patch
from types import SimpleNamespace

from deskrawl_assistant.game_actions import GameActions, _Read
from deskrawl_assistant.mythic import MAP_ID, floor_id
from deskrawl_assistant.native_memory import SnapshotChangedError, MemoryReadError
from deskrawl_assistant.native_dispatcher import compile_mailbox
from test_managed_service import ManagedServiceTests
from copy import deepcopy
from deskrawl_assistant.models import ValidationError
from deskrawl_assistant.managed_mode import DEFAULT_SETTINGS


class ContinueEntryTests(TestCase):
    def test_completed_entries_guard_source_plan_and_use_original_replay_handlers(self):
        for case in ('ordinary','mythic','source_changed','running','dead','plan_changed','tier_changed'):
            with self.subTest(case=case):
                reader, dispatcher, read, copy = Mock(), Mock(), Mock(), Mock()
                read.guards=[];read.singleton.return_value=3;read.boolean.return_value=False;read.ptr.return_value=1000;read.integer.return_value=1
                dispatcher.invoke.return_value={};reader.string.return_value='native-source'
                copy.verify.side_effect=lambda obj,name:obj
                copy.ptr.side_effect=lambda address:{121:100,105:200,288:101 if case=='plan_changed' else 100,116:300,65:400,432:500}[address]
                copy.boolean.side_effect=lambda address:address==448
                copy.integer.return_value=4 if case=='tier_changed' else 3
                copy.guards=[(121,struct.pack('<Q',100))]
                mythic=case in ('mythic','tier_changed');map_id=floor_id(3) if mythic else 'a';difficulty='Mythic' if mythic else 'Inferno'
                source=hashlib.sha256(b'native-source').hexdigest()
                state={'available':True,'difficulty':difficulty,'map_id':map_id,'dead':case=='dead',
                       'run':{'id':'different' if case=='source_changed' else source,
                              'status':'running' if case=='running' else 'success','mythic_tier':3},
                       'maps':[{'map_id':map_id,'map_type':int(mythic),'can_enter':True}],
                       'maps_by_difficulty':{difficulty:[{'map_id':map_id,'can_enter':True}]}}
                payload={'map_id':map_id,'difficulty':difficulty,'source_run_id':source,'reason_code':'completed_continue'}
                game=GameActions(reader,dispatcher=dispatcher,allow_unverified=True)
                with patch.object(game,'capabilities',return_value={'compatible':True}),patch.object(game,'_context',return_value=(read,1,2,0)),patch.object(game,'_require_travel_ready'),patch.object(game,'_require_empty_town') as town,patch.object(game,'control_snapshot',return_value=state),patch.object(game,'_map_objects',return_value={MAP_ID if mythic else map_id:1000}),patch.object(game,'_ground',return_value=[]),patch.object(game,'_visible_completion',return_value=8888),patch('deskrawl_assistant.recommendation_reader._Copy',return_value=copy):
                    if case in ('ordinary','mythic'):
                        result=game.execute('enter_map',payload)
                        calls=dispatcher.invoke.call_args.args[0]
                        self.assertEqual(calls[-1].method,'MythicCompletionUI.repeat' if mythic else 'CombatMapCompletionUI.repeat')
                        if mythic:self.assertEqual(calls[-1].arguments[0].raw,b'\0')
                        self.assertIn(copy.guards[0],dispatcher.invoke.call_args.args[1])
                        self.assertTrue(result['transition_requested']);self.assertFalse(result['native_verified'])
                        compile_mailbox(0x10000000,0x180000000,game.profile,1,2,3,calls,[])
                    else:
                        with self.assertRaises(SnapshotChangedError):game.execute('enter_map',payload)
                        dispatcher.invoke.assert_not_called()
                    town.assert_not_called()

    def test_combat_completion_scan_caches_only_live_matching_map_components(self):
        reader,read=Mock(),Mock();read.guards=[];read.singleton.return_value=1000
        klass,obj,expected=0x2000,0x3000,0x5000
        block=struct.pack('<QQ',klass,0)+bytes(16)+struct.pack('<QQ',klass,0)
        reader.memory.regions.return_value=[SimpleNamespace(base=obj,size=len(block),kind=0x20000)]
        reader.memory.read.return_value=block
        read.ptr.side_effect=lambda address:{obj+16:0,obj+208:expected,obj+32+16:0x6000,obj+32+208:expected}[address]
        game=GameActions(reader,dispatcher=Mock())
        self.assertEqual(game._combat_completion_instance(read,klass,expected),obj+32)
        reader.memory.regions.reset_mock()
        self.assertEqual(game._combat_completion_instance(read,klass,expected),obj+32)
        reader.memory.regions.assert_not_called()


class ContinueServiceTests(ManagedServiceTests):
    # Inherit only the fixture setup; load_tests below avoids duplicating the
    # parent's independent tests when unittest discovers this module.
    def test_same_map_success_does_not_return_and_old_success_cannot_confirm_new_run(self):
        self.client.items=[];self.client.in_town=False;self.client.current_map='offline-map';self.client.run_status='success'
        self.ready(farming=True,auto_equip=False)
        self.client.native_handler=lambda kind,payload:{'transition_requested':True}
        with patch('deskrawl_assistant.combat_rewards.CompletionRewards.QUIET_SECONDS',0):
            self.service._managed_once();self.service._managed_once()
        self.assertEqual([row[0] for row in self.client.actions],['enter_map'])
        self.assertEqual(self.service.managed_transition['action']['reason_code'],'completed_continue')
        self.service._managed_once()
        self.assertIsNotNone(self.service.managed_transition)
        base=self.client.control_snapshot
        def new_run():
            state=base();state['run'].update(id='new-run',status='running');return state
        self.client.control_snapshot=new_run
        self.service._managed_once()
        self.assertIsNone(self.service.managed_transition)
        self.assertEqual([row[0] for row in self.client.actions],['enter_map'])


def load_tests(loader, tests, pattern):
    import unittest
    result=loader.loadTestsFromTestCase(ContinueEntryTests)
    result.addTest(ContinueServiceTests('test_same_map_success_does_not_return_and_old_success_cannot_confirm_new_run'))
    return result
