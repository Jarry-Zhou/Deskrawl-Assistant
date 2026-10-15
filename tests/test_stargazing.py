"""No live game actions: plan decisions, quotas and transition guards."""
from copy import deepcopy
import unittest

from deskrawl_assistant.managed_mode import ManagedMode, validate_settings
from deskrawl_assistant.stargazing import (DEFAULT_STARGAZING, FIXED_REWARDS, validate_stargazing,
                                         enabled, decide)
from tests.test_managed_mode import observation, settings, equipment, verified, after_rewards


def plan(world, items=()):
    scene = world['scene']
    rows = [{'item_key':'offline-item-'+str(index), **item} for index,item in enumerate(deepcopy(list(items)))]
    return {'available': True, 'phase':'active', 'session': world['session'], 'rules_known': True,
            'run': {'key': scene['run']['id'], 'id': scene['run']['id'], 'map_id': scene['dungeon_id'],
                    'difficulty': scene['difficulty'], 'total_waves': 1, 'current_wave':0},
            'waves': [{'number':1,'items':rows}], 'totals': {'items': len(items)}}


def setup(two=False):
    cfg = settings(equipment_action='sell')
    cfg['farming'].update(difficulty='Normal', repeat_maps=[{'dungeon_id':'a', 'difficulty':'Normal', 'runs':3}])
    if two: cfg['farming']['repeat_maps'].append({'dungeon_id':'b', 'difficulty':'Normal', 'runs':2})
    cfg['farming']['stargazing']['enabled'] = True
    world = observation()
    world['scene'].update(difficulty='Normal', in_dungeon=True)
    world['loot_plan'] = plan(world)
    engine = ManagedMode(cfg)
    engine.start(world)
    return engine, world


class StargazingDecisionTests(unittest.TestCase):
    def verdict(self, items, choices=None):
        _, world = setup()
        cfg = deepcopy(DEFAULT_STARGAZING)
        if choices: cfg['rewards'].update(choices)
        return decide(plan(world,items),world,cfg)['verdict']

    def test_defaults_preserve_old_settings_and_fixed_categories_cannot_be_disabled(self):
        cfg = settings(); del cfg['farming']['stargazing']
        upgraded = validate_settings(cfg)
        self.assertFalse(enabled(upgraded))
        self.assertTrue(all(upgraded['farming']['stargazing']['rewards'].values()))
        cfg = {'enabled': True, 'rewards': dict.fromkeys(DEFAULT_STARGAZING['rewards'],False)}
        result = validate_stargazing(cfg)
        self.assertEqual({k for k,v in result['rewards'].items() if v}, set(FIXED_REWARDS))
        self.assertTrue(all(v is False for v in cfg['rewards'].values()))

    def test_each_mandatory_category_keeps_the_run_even_with_every_optional_disabled(self):
        optional = dict.fromkeys(DEFAULT_STARGAZING['rewards'],False)
        items = [{'kind':'equipment','rarity':4}, {'kind':'equipment','rarity':3,'black_mist':True},
                 {'kind':'rune','rarity':5,'item_key':'SetRune12'},
                 {'kind':'rune','rarity':3,'item_key':'LegendaryRune_HunterHeavyAttack2'}]
        for item in items:
            with self.subTest(item=item): self.assertEqual(self.verdict([item],optional),'keep')

    def test_optional_categories_are_or_and_persist_deselection(self):
        for item, key in [({'kind':'gem'},'gem'),({'kind':'rune','rarity':2},'rare_rune'),
                          ({'kind':'rune','rarity':1},'uncommon_rune'),
                          ({'kind':'equipment','rarity':3,'ancient':True,'primary_perfect':True,'matches':False},'primary_perfect'),
                          ({'kind':'equipment','rarity':3,'matches':True,'primary_perfect':False},'rule_match')]:
            with self.subTest(key=key):
                self.assertEqual(self.verdict([item]),'keep')
                self.assertEqual(self.verdict([item],{key:False}),'skip')
        self.assertEqual(self.verdict([{'kind':'rune','rarity':1},{'kind':'gem'}],{'uncommon_rune':False}),'keep')

    def test_low_quality_equipment_never_qualifies_as_rule_matched_legendary(self):
        for rarity in (0,1,2):
            self.assertEqual(self.verdict([{'kind':'equipment','rarity':rarity,'matches':True,'primary_perfect':True}]),'skip')

    def test_new_chest_and_material_rewards_are_selected_by_default_and_can_be_cleared(self):
        for key, kind, choice in [('TreasureChest1','chest','silver_chest'),
                ('TreasureChest2','chest','golden_chest'), ('TreasureChest3','chest','mythic_chest'),
                ('GoldBar','material','gold_bar'), ('Rein_BeachCrabBoss','material','legendary_rein')]:
            with self.subTest(choice=choice):
                row={'item_key':key,'kind':kind,'rarity':3}
                self.assertEqual(self.verdict([row]), 'keep')
                self.assertEqual(self.verdict([row], {choice:False}), 'skip')
                self.assertEqual(self.verdict([row,{'kind':'gem'}], {choice:False}), 'keep')

    def test_old_choices_are_preserved_when_new_reward_choices_are_added(self):
        old={'enabled':True,'rewards':{'gem':False,'rare_rune':False}}
        result=validate_stargazing(old)
        for key in ('silver_chest','golden_chest','mythic_chest','legendary_rein','gold_bar'):
            self.assertTrue(result['rewards'][key])
        self.assertFalse(result['rewards']['gem']);self.assertFalse(result['rewards']['rare_rune'])
        self.assertEqual(validate_stargazing(deepcopy(result)),result)
        self.assertEqual(old['rewards'],{'gem':False,'rare_rune':False})

    def test_other_chests_materials_and_nonlegendary_reins_do_not_match(self):
        for key,kind in [('TreasureChest4','chest'),('GoldPotion1','material'),('GoldBarFake','material')]:
            self.assertEqual(self.verdict([{'kind':kind,'item_key':key,'rarity':3}]), 'skip')
        for rarity in (0,1,2,4,5):
            self.assertEqual(self.verdict([{'kind':'material','item_key':'Rein_BeachCrabBoss','rarity':rarity}]), 'skip')
        for rarity in (None,True,'3'):
            row={'kind':'material','item_key':'Rein_BeachCrabBoss','rarity':rarity}
            self.assertEqual(self.verdict([row]), 'unknown')
            self.assertEqual(self.verdict([row],{'legendary_rein':False}), 'skip')

    def test_unknown_items_or_unconfirmed_rule_reads_never_yield_a_miss(self):
        for item in ({'kind':'unknown'}, {'kind':'equipment','rarity':None},
                     {'kind':'equipment','rarity':3,'rule_status':'review','matches':False},
                     {'kind':'equipment','rarity':3}):
            self.assertEqual(self.verdict([item]),'unknown')
        self.assertEqual(self.verdict([{'kind':'unknown'},{'kind':'gem'}]),'keep')

    def test_full_plan_is_bound_to_current_connection_run_map_and_difficulty(self):
        _, world = setup()
        original = plan(world)
        for group, key, value in ((None,'session','another'),('run','id','other'),('run','map_id','b'),
                                  ('run','difficulty','Inferno'),('run','total_waves',2),('totals','items',1)):
            changed = deepcopy(original)
            (changed if group is None else changed[group])[key] = value
            self.assertEqual(decide(changed,world,DEFAULT_STARGAZING)['verdict'],'unknown')
        self.assertEqual(decide(None,world,DEFAULT_STARGAZING)['verdict'],'unknown')

    def test_matching_reward_in_last_wave_is_included(self):
        _, world = setup()
        value = plan(world)
        value['waves'].extend([{'number':2,'items':[{'kind':'rune','rarity':3,'item_key':'LegendaryRune_HunterHeavyAttack2'}]}])
        value['totals']['items']=1; value['run']['total_waves']=2
        self.assertEqual(decide(value,world,DEFAULT_STARGAZING)['verdict'],'keep')


class StargazingPlannerTests(unittest.TestCase):
    def test_attack_or_gather_wait_does_not_commit_skip_and_rechecks_new_rewards(self):
        for two in (False,True):
            with self.subTest(two=two):
                engine,world=setup(two)
                world['scene'].update(travel_blocked=True,travel_wait_reason='等待攻击结束')
                self.assertIsNone(engine.next_action(world))
                self.assertEqual(engine.stargazing_state['skipped'],0)
                self.assertNotIn(world['scene']['run']['id'],engine.stargazing_seen)
                world['scene']['travel_blocked']=False
                world['loot_plan']=plan(world,[{'kind':'gem'}])
                self.assertIsNone(engine.next_action(world))
                self.assertEqual(engine.stargazing_state['verdict'],'keep')

    def test_ready_state_can_retry_the_same_map_decision_after_attack(self):
        engine,world=setup(True)
        world['scene']['travel_blocked']=True
        self.assertIsNone(engine.next_action(world))
        world['scene']['travel_blocked']=False
        action=engine.next_action(world)
        self.assertEqual((action['kind'],action['dungeon_id']),('enter_dungeon','b'))
        self.assertEqual(engine.repeat_completed,0)

    def test_single_map_returns_cleans_actual_rewards_then_reenters_without_counting_skip(self):
        engine, world = setup()
        action = engine.next_action(world)
        self.assertEqual(action['kind'],'return_town')
        self.assertEqual(engine.stargazing_state['skipped'],0)
        verified(engine,action)
        self.assertEqual(engine.stargazing_state['skipped'],1)
        world['scene']['in_town']=True;world['scene']['run']['status']='success'
        world['ground']['items']=[equipment('must-pick',container='ground')]
        self.assertEqual(engine.next_action(world)['kind'],'collect_ground')
        self.assertEqual(engine.repeat_completed,0)

    def test_two_map_skip_keeps_partial_quotas_and_only_commits_target_after_receipt(self):
        engine, world = setup(True)
        engine.repeat_completed=1
        action=engine.next_action(world)
        self.assertEqual((action['kind'],action['dungeon_id']),('enter_dungeon','b'))
        self.assertEqual((engine.repeat_index,engine.target_dungeon),(0,'a'))
        verified(engine,action)
        world['scene'].update(dungeon_id='b',run={'id':'run2','status':'running'})
        world['loot_plan']=plan(world)
        self.assertEqual(engine.next_action(world)['dungeon_id'],'a')
        action=engine.pending;verified(engine,action)
        self.assertEqual((engine.repeat_index,engine.repeat_completed),(0,1))
        self.assertEqual(engine.stargazing_state['skipped'],2)

    def test_temporary_combat_switch_rejection_retries_same_target_without_claiming_a_skip(self):
        engine,world=setup(True)
        action=engine.next_action(world)
        self.assertFalse(engine.stargazing_rejected(action))
        self.assertEqual(engine.stargazing_state['skipped'],0)
        self.assertIsNone(engine.stargazing_return)
        action=engine.next_action(world)
        self.assertEqual((action['kind'],action['dungeon_id']),('enter_dungeon','b'))
        verified(engine,action)
        self.assertEqual((engine.target_dungeon,engine.repeat_completed),('b',0))

    @staticmethod
    def reject_until_fallback(engine,world):
        for attempt in range(8):
            action=engine.next_action(world)
            fallback=engine.stargazing_rejected(action)
            assert fallback is (attempt==7)

    def test_repeated_combat_switch_refusals_fall_back_without_claiming_a_skip(self):
        engine,world=setup(True)
        self.reject_until_fallback(engine,world)
        self.assertEqual(engine.stargazing_state['skipped'],0)
        action=engine.next_action(world)
        self.assertEqual((action['kind'],action['next_repeat_index']),('return_town',1))
        verified(engine,action)
        self.assertEqual(engine.target_dungeon,'b')

    def test_win_during_rejection_wait_counts_once_and_is_never_marked_skipped(self):
        engine,world=setup(True)
        self.reject_until_fallback(engine,world)
        world['scene']['run'].update(status='success',completion_confirmed=True)
        action=after_rewards(engine,world)
        self.assertEqual(action['kind'],'return_town')
        self.assertNotIn('reason_code',action)
        verified(engine,action)
        self.assertEqual(engine.repeat_completed,1)
        self.assertEqual(engine.stargazing_state['skipped'],0)
        self.assertIsNone(engine.stargazing_return)

    def test_final_kill_receipt_during_wait_counts_even_before_completion_popup(self):
        engine,world=setup(True)
        self.reject_until_fallback(engine,world)
        world['scene']['run'].update(status='settling',completion_confirmed=True)
        self.assertIsNone(engine.next_action(world))
        self.assertEqual(engine.repeat_completed,1)
        self.assertEqual(engine.stargazing_state['skipped'],0)

    def test_fallback_rechecks_high_value_and_unknown_plan(self):
        for items in ([{'kind':'gem'}],[{'kind':'unknown'}]):
            engine,world=setup(True)
            self.reject_until_fallback(engine,world)
            world['loot_plan']=plan(world,items)
            self.assertIsNone(engine.next_action(world))
            self.assertEqual(engine.stargazing_state['skipped'],0)
            if items[0]['kind']=='gem': self.assertIsNone(engine.stargazing_return)

    def test_rewards_arriving_during_fallback_are_collected_in_town_before_entry(self):
        engine,world=setup(True)
        self.reject_until_fallback(engine,world)
        world['carriage']['items']=[equipment('must-pick',container='carriage')]
        action=engine.next_action(world)
        self.assertEqual(action['kind'],'return_town')
        verified(engine,action)
        world['scene']['in_town']=True
        self.assertEqual(engine.next_action(world)['kind'],'collect_carriage')
        self.assertEqual(engine.repeat_completed,0)

    def test_changed_difficulty_requires_town_instead_of_combat_entry(self):
        engine, world=setup(True);engine.repeat_maps[1]['difficulty']='Nightmare'
        self.assertEqual(engine.next_action(world)['kind'],'return_town')

    def test_present_actual_rewards_return_for_collection_and_unknown_ground_waits(self):
        for container in ('ground','carriage'):
            engine,world=setup(True);world[container]['items']=[equipment('actual')]
            action=engine.next_action(world)
            self.assertEqual(action['kind'],'return_town')
            self.assertEqual(engine.stargazing_state['verdict'],'skip')
            verified(engine,action)
            world['scene']['in_town']=True
            self.assertEqual(engine.next_action(world)['kind'],'collect_'+container)
            self.assertEqual(engine.repeat_completed,0)
        engine,world=setup(True);world['carriage']['complete']=False
        self.assertIsNone(engine.next_action(world))
        self.assertNotIn('run1',engine.stargazing_seen)
        world['carriage']['complete']=True
        self.assertEqual(engine.next_action(world)['kind'],'enter_dungeon')

    def test_native_repeat_gets_a_new_decision_and_planned_items_never_enter_drop_statistics(self):
        engine,world=setup(True)
        world['loot_plan']=plan(world,[{'kind':'gem','name':'计划中的宝石'}])
        self.assertIsNone(engine.next_action(world))
        world['scene']['run'].update(status='settling',completion_confirmed=True)
        self.assertIsNone(engine.next_action(world));self.assertEqual(engine.repeat_completed,1)
        world['scene']['run']={'id':'run2','status':'running'};world['loot_plan']=plan(world)
        self.assertEqual(engine.next_action(world)['kind'],'enter_dungeon')
        self.assertEqual(engine.metrics.state()['gems'],[])

    def test_push_and_disabled_observation_never_skip(self):
        engine,world=setup();engine.settings['farming']['stargazing']['enabled']=False
        self.assertIsNone(engine.next_action(world))
        engine,world=setup();engine.settings['farming']['mode']='push'
        self.assertIsNone(engine.next_action(world))

    def test_finishing_or_full_bag_always_returns_for_cleanup(self):
        engine,world=setup(True);engine.request_finish()
        self.assertEqual(engine.next_action(world)['kind'],'return_town')
        engine,world=setup(True);world['counts']['inventory']['occupied']=40
        self.assertEqual(engine.next_action(world)['kind'],'return_town')
        self.assertEqual(engine.stargazing_state['skipped'],0)

    def test_only_success_counts_and_early_returns_never_advance_two_map_quota(self):
        engine,world=setup(True)
        world['scene']['run']['status']='failed'
        self.assertEqual(engine.next_action(world)['kind'],'return_town')
        self.assertEqual((engine.repeat_index,engine.repeat_completed),(0,0))

    def test_prototype_fingerprint_ignores_identity_but_changes_with_reward_contents(self):
        _,world=setup()
        first=decide(plan(world,[{'kind':'gem','name':'甲'}]),world,DEFAULT_STARGAZING)
        world['scene']['run']['id']='run2'
        same=decide(plan(world,[{'kind':'gem','name':'乙'}]),world,DEFAULT_STARGAZING)
        changed=decide(plan(world,[{'kind':'rune','rarity':2}]),world,DEFAULT_STARGAZING)
        self.assertEqual(first['content_fingerprint'],same['content_fingerprint'])
        self.assertNotEqual(first['content_fingerprint'],changed['content_fingerprint'])
