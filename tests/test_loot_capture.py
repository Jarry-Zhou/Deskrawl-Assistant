"""Local capture must preserve evidence without treating plans as settlement."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

from deskrawl_assistant.loot_capture import LootCaptureMonitor, plan_hash, planned_hits
from deskrawl_assistant.loot_plan_reader import read_loot_plan
from tests.test_loot_plan_reader import Fixture


def bundle(key='CommonBelt3', rarity='Common', *, black_mist=False, uid='planned-drop'):
    f = Fixture()
    obj = f.item(key,rarity=rarity)
    f.text(obj+16,uid)
    f.boolean(obj+53,black_mist)
    f.set_waves([[obj]])
    raw = {}
    preview = read_loot_plan(f.reader,raw_sink=raw)
    return {'session':'isolated-session','raw_plan':raw,'preview':preview,
        'observations_complete':True,'observations':[],'observation_run':plan_hash(raw)}


def observed(uid='actual-drop',key='LegendaryBelt1',**extra):
    return {'item_uid':uid,'internal_name':key,'is_equipment':True,'rarity':4,
        'capture_source':'inventory',**extra}


class LootCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'captures'
        self.monitor = LootCaptureMonitor(self.path)
        self.monitor.set_enabled(True)

    def files(self): return list(self.path.glob('*.json'))
    def saved(self):
        self.assertEqual(len(self.files()),1)
        return json.loads(self.files()[0].read_text(encoding='utf-8'))

    def test_disabled_and_ordinary_runs_do_not_write(self):
        self.monitor.set_enabled(False)
        self.monitor.feed(bundle(rarity='Divine'))
        self.assertFalse(self.path.exists())
        self.monitor.set_enabled(True)
        self.monitor.feed(bundle())
        self.assertFalse(self.path.exists())

    def test_all_four_high_value_categories_including_blank_rune_rarity(self):
        from deskrawl_assistant.loot_plan_reader import _labels
        macro_rune = next(k for k,v in _labels()['items'].items() if v.get('kind')=='rune' and v.get('rarity')==3)
        for key,rarity,mist,expected in [('LegendaryBelt1','Divine',False,'神圣装备'),
                ('LegendaryBelt1','Legendary',True,'黑雾装备'),
                (macro_rune,'',False,'宏伟符文'),
                ('HunterSetRune1_1','Common',False,'套装符文')]:
            with self.subTest(key=key):
                data = bundle(key,rarity,black_mist=mist)
                self.assertEqual(planned_hits(data['raw_plan'])[0]['category'],expected)

    def test_unknown_divine_template_is_still_captured_from_plan_slot(self):
        self.assertEqual(planned_hits(bundle('NewServerBelt','Divine')['raw_plan'])[0]['category'],'神圣装备')

    def test_same_run_is_saved_once_and_preserves_raw_identifiers(self):
        data = bundle('LegendaryBelt1','Divine')
        original = deepcopy(data)
        self.monitor.feed(data)
        self.monitor.feed(data)
        saved = self.saved()
        self.assertEqual(saved['raw_plan'],original['raw_plan'])
        self.assertIn('planned-drop',json.dumps(saved))
        self.assertEqual(self.monitor.status()['saved_runs'],1)
        self.assertEqual(data,original)
        self.assertFalse(list(self.path.glob('*.tmp')))

    def test_moving_evidence_out_updates_count_without_restart_or_new_loot(self):
        data = bundle('LegendaryBelt1','Divine')
        self.monitor.feed(data)
        self.assertEqual(self.monitor.status()['saved_runs'],1)
        target = self.files()[0]
        moved = Path(self.temp.name)/target.name
        target.rename(moved)
        self.assertEqual(self.monitor.status()['saved_runs'],0)
        # Polling the same plan must not recreate evidence the user removed.
        self.monitor.feed(data)
        self.assertEqual(self.monitor.status()['saved_runs'],0)
        self.assertTrue(moved.is_file())

    def test_file_count_tracks_external_changes_even_when_monitor_disabled(self):
        self.monitor.set_enabled(False)
        self.path.mkdir()
        record = self.path/'imported.json'
        record.write_text('{}',encoding='utf-8')
        (self.path/'unfinished.tmp').write_text('{}',encoding='utf-8')
        (self.path/'folder.json').mkdir()
        self.assertEqual(self.monitor.status()['saved_runs'],1)
        record.unlink()
        self.assertEqual(self.monitor.status()['saved_runs'],0)

    def test_unreadable_directory_does_not_report_an_empty_archive(self):
        with patch.object(Path,'glob',side_effect=PermissionError('denied')):
            status = self.monitor.status()
        self.assertIsNone(status['saved_runs'])
        self.assertIn('文件数量未确认',status['error'])
        self.assertEqual(self.monitor.status()['saved_runs'],0)
        self.assertEqual(self.monitor.status()['error'],'')

    def test_initial_owned_items_and_transfers_do_not_trigger_actual_capture(self):
        data = bundle()
        data['observations'] = [observed()]
        self.monitor.feed(data)
        data['observations'][0]['capture_source']='storage'
        self.monitor.feed(data)
        self.assertFalse(self.files())

    def test_reenable_preserves_earliest_plan_observations_and_file_count(self):
        data = bundle('LegendaryBelt1','Divine')
        self.monitor.feed(data)
        data['observations'] = [observed()]
        self.monitor.feed(data)
        original = self.saved()
        self.monitor.set_enabled(False)
        self.monitor.set_enabled(True)
        data['preview']['run']['current_wave'] = 5
        data['raw_plan']['waves'][0]['loot']['items'][0]['itemLevel'] = 100
        self.monitor.feed(data)
        restored = self.saved()
        self.assertEqual(restored['raw_plan'],original['raw_plan'])
        self.assertEqual(restored['first_read_at'],original['first_read_at'])
        self.assertEqual(restored['first_read_wave'],original['first_read_wave'])
        self.assertEqual(restored['observed_high_value'],original['observed_high_value'])
        self.assertEqual(restored['latest_raw_plan'],data['raw_plan'])
        self.assertEqual(self.monitor.status()['saved_runs'],1)

    def test_corrupt_saved_evidence_is_not_overwritten_after_reenable(self):
        data = bundle('LegendaryBelt1','Divine')
        self.monitor.feed(data)
        target = self.files()[0]
        target.write_text('{broken evidence',encoding='utf-8')
        self.monitor.set_enabled(False)
        self.monitor.set_enabled(True)
        with self.assertRaises(ValueError): self.monitor.feed(data)
        self.assertEqual(target.read_text(encoding='utf-8'),'{broken evidence')
        self.assertEqual(self.monitor.status()['saved_runs'],1)

    def test_actual_high_value_absent_from_plan_captures_cached_ordinary_plan(self):
        data = bundle()
        self.monitor.feed(data)
        data['raw_plan'] = None
        data['preview'] = {'available':False}
        data['observations'] = [observed()]
        self.monitor.feed(data)
        saved = self.saved()
        self.assertEqual(saved['raw_plan']['waves'][0]['loot']['items'][0]['baseItemId'],'CommonBelt3')
        self.assertEqual(saved['observed_high_value'][0]['plan_membership'],'unconfirmed')
        self.assertEqual(saved['observed_high_value'][0]['same_template_waves'],[])
        data['observations'][0]['capture_source']='storage'
        self.monitor.feed(data)
        self.assertEqual(len(self.saved()['observed_high_value']),1)

    def test_exact_drop_id_requires_matching_item_template(self):
        data = bundle('LegendaryBelt1','Divine',uid='actual-drop')
        self.monitor.feed(data)
        data['observations'] = [observed()]
        self.monitor.feed(data)
        self.assertEqual(self.saved()['observed_high_value'][0]['plan_membership'],'exact_id')

    def test_confirmed_merchant_reward_is_not_attached_to_retained_run_plan(self):
        data=bundle()
        self.monitor.feed(data)
        data['raw_plan']=None;data['preview']={'available':False}
        data['merchant_uids']=['actual-drop']
        data['observations']=[observed(key='LegendaryRing2',rarity=3,is_black_mist=True)]
        self.monitor.feed(data)
        saved=self.saved()
        self.assertEqual(saved['association'],'merchant_purchase')
        self.assertIsNone(saved['raw_plan'])
        hit=saved['observed_high_value'][0]
        self.assertEqual(hit['acquisition_source'],'merchant')
        self.assertEqual(hit['category'],'黑雾装备')
        self.assertEqual(hit['exact_plan_items'],[])
        data['observations'][0]['capture_source']='storage'
        self.monitor.feed(data)
        self.assertEqual(len(self.saved()['observed_high_value']),1)

    def test_capture_loop_waits_for_purchase_receipt_before_classifying_new_items(self):
        import threading
        from deskrawl_assistant.web_service import AssistantService
        data=bundle();self.monitor.feed(data)
        data['observations']=[observed()]
        service=SimpleNamespace(closed=Mock(),updating=False,loot_capture=self.monitor,
            guard=threading.RLock(),managed_merchant_uids=set(),
            managed=SimpleNamespace(pending={'kind':'merchant_buy'}),
            client=SimpleNamespace(connected=True,loot_capture_snapshot=lambda:deepcopy(data)))
        service.closed.wait.side_effect=[False,True]
        service.closed.is_set.return_value=False
        AssistantService._loot_capture_loop(service)
        self.assertFalse(self.files())
        service.managed.pending=None;service.managed_merchant_uids.add('actual-drop')
        service.closed.wait.side_effect=[False,True]
        AssistantService._loot_capture_loop(service)
        self.assertEqual(self.saved()['association'],'merchant_purchase')

    def test_only_same_name_is_not_proof_of_plan_membership(self):
        data = bundle('LegendaryBelt1','Divine')
        self.monitor.feed(data)
        data['observations'] = [observed()]
        self.monitor.feed(data)
        hit = self.saved()['observed_high_value'][0]
        self.assertEqual(hit['same_template_waves'],[1])
        self.assertEqual(hit['plan_membership'],'unconfirmed')

    def test_incomplete_baseline_waits_and_does_not_claim_existing_drops(self):
        data = bundle()
        data['observations_complete'] = False
        data['observations'] = [observed()]
        self.monitor.feed(data)
        data['observations_complete'] = True
        self.monitor.feed(data)
        self.assertFalse(self.files())

    def test_quality_confirmation_after_pickup_uses_original_run(self):
        data = bundle()
        self.monitor.feed(data)
        data['observations'] = [observed(rarity=None,capture_source='ground')]
        self.monitor.feed(data)
        first_raw = deepcopy(data['raw_plan'])
        data['raw_plan']['runId']='second-run'
        data['observation_run']=plan_hash(data['raw_plan'])
        data['observations'] = [observed()]
        self.monitor.feed(data)
        saved = self.saved()
        self.assertEqual(saved['raw_plan'],first_raw)
        self.assertEqual(saved['observed_high_value'][0]['first_source'],'ground')

    def test_unassociated_observation_never_uses_other_run_plan(self):
        data = bundle()
        self.monitor.feed(data)
        data['observation_run']='unknown-run'
        data['observations'] = [observed()]
        self.monitor.feed(data)
        saved = self.saved()
        self.assertIsNone(saved['raw_plan'])
        self.assertEqual(saved['association'],'unattributed')

    def test_later_plan_change_preserves_first_read_before_high_value_appears(self):
        data = bundle()
        self.monitor.feed(data)
        first_raw=deepcopy(data['raw_plan'])
        data['raw_plan']['waves'][0]['loot']['items'][0]['rarity']='Divine'
        self.monitor.feed(data)
        saved = self.saved()
        self.assertTrue(saved['plan_changed_since_first_read'])
        self.assertEqual(saved['raw_plan'],first_raw)
        self.assertEqual(saved['latest_raw_plan']['waves'][0]['loot']['items'][0]['rarity'],'Divine')

    def test_write_failure_retries_without_claiming_success(self):
        data = bundle('LegendaryBelt1','Divine')
        with patch.object(Path,'replace',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.monitor.feed(data)
        self.assertEqual(self.monitor.status()['saved_runs'],0)
        self.assertFalse(self.files())
        self.assertFalse(list(self.path.glob('*.tmp')))
        self.monitor.feed(data)
        self.assertEqual(self.monitor.status()['saved_runs'],1)

    def test_new_connection_starts_a_fresh_owned_baseline(self):
        data = bundle()
        self.monitor.feed(data)
        data['session']='new-session'
        data['observations']=[observed()]
        self.monitor.feed(data)
        self.assertFalse(self.files())

    def test_switching_characters_does_not_count_their_existing_valuables(self):
        data = bundle();data['character_key']='first-character'
        self.monitor.feed(data)
        data['character_key']='second-character'
        data['observations']=[observed()]
        self.monitor.feed(data)
        self.assertFalse(self.files())

    def test_enabled_validation_rejects_truthy_strings(self):
        with self.assertRaises(ValueError): self.monitor.set_enabled('true')

    def test_client_collects_real_ground_list_contract_without_game_actions(self):
        from deskrawl_assistant.runtime_client import RuntimeClient
        client=RuntimeClient()
        client._reader=SimpleNamespace(session_id='fixture-session')
        client.snapshot=Mock(return_value={'complete':True,'containers':{'inventory':{'slots':[observed()]}}})
        client.control_snapshot=Mock(return_value={'available':True,'ground_complete':True,
            'ground':[observed(uid='ground')],'carriage':{'complete':True,'items':[observed(uid='carriage')]},'run':{'id':'run-hash'}})
        client.execute_game_action=Mock(side_effect=AssertionError('No game actions allowed'))
        def read(_reader,raw_sink):
            raw_sink.update({'runId':'private','waves':[]})
            return {'available':True}
        with patch('deskrawl_assistant.loot_plan_reader.read_loot_plan',side_effect=read):
            result=client.loot_capture_snapshot()
        self.assertTrue(result['observations_complete'])
        self.assertEqual([r['capture_source'] for r in result['observations']],['inventory','ground','carriage'])
        client.snapshot.assert_called_once_with(save=False)
        client.execute_game_action.assert_not_called()

    def test_client_keeps_valid_raw_plan_when_actual_read_fails(self):
        from deskrawl_assistant.runtime_client import RuntimeClient
        client=RuntimeClient();client._reader=SimpleNamespace(session_id='fixture-session')
        client.snapshot=Mock(side_effect=OSError('unavailable'))
        client.control_snapshot=Mock(side_effect=OSError('unavailable'))
        def read(_reader,raw_sink):
            raw_sink.update({'runId':'private','waves':[]})
            return {'available':True}
        with patch('deskrawl_assistant.loot_plan_reader.read_loot_plan',side_effect=read):
            result=client.loot_capture_snapshot()
        self.assertEqual(result['raw_plan']['runId'],'private')
        self.assertFalse(result['observations_complete'])


if __name__=='__main__': unittest.main()
