"""Campaign/repeat plans against completed runs, without invoking the game."""
from copy import deepcopy
import unittest
from deskrawl_assistant.managed_mode import ManagedMode, validate_settings
from deskrawl_assistant.managed_service import highest_unlocked_map, full_campaign_route
from deskrawl_assistant.models import ValidationError
from test_managed_mode import observation, settings, verified


def scene(map_id, difficulty='Normal', status='running', run_id='initial', town=False):
    world=observation(town=town)
    world['scene'].update(dungeon_id=map_id,difficulty=difficulty,
        run=None if town else {'id':run_id,'dungeon_id':map_id,'difficulty':difficulty,'status':status})
    return world


class FarmingCycleTests(unittest.TestCase):
    def finish(self, engine, status, run_id):
        world=scene(engine.target_dungeon,engine.target_difficulty,status,run_id)
        action=engine.next_action(world)
        self.assertEqual(action['kind'],'return_town');verified(engine,action)
        # Re-reading the same result during return cannot advance twice.
        target=(engine.target_dungeon,engine.target_difficulty,engine.repeat_completed)
        self.assertIsNone(engine.next_action(world));self.assertEqual(target,
            (engine.target_dungeon,engine.target_difficulty,engine.repeat_completed))
        town=scene(None,world['scene']['difficulty'],town=True)
        action=engine.next_action(town)
        if action['kind']=='switch_difficulty':
            verified(engine,action);town['scene']['difficulty']=action['difficulty'];action=engine.next_action(town)
        self.assertEqual(action['kind'],'enter_dungeon');verified(engine,action)
        self.assertIsNone(engine.next_action(scene(engine.target_dungeon,engine.target_difficulty,run_id=run_id+'-next')))

    def test_push_repeatedly_retries_failed_map_instead_of_permanent_fallback(self):
        cfg=settings();cfg['farming'].update(mode='push',dungeon_id='b',difficulty='Normal')
        engine=ManagedMode(cfg);engine.start(scene('b'))
        for status,expected in [('failed','a'),('success','b'),('failed','a'),('success','b'),('success','c')]:
            self.finish(engine,status,str(len(engine.handled_runs)))
            self.assertEqual(engine.target_dungeon,expected);self.assertTrue(engine.running)

    def test_first_attempt_failure_knows_previous_map_without_session_success(self):
        cfg=settings();cfg['farming'].update(mode='push',dungeon_id='b',difficulty='Normal')
        engine=ManagedMode(cfg);engine.start(scene('b'));self.finish(engine,'failed','b-first')
        self.assertEqual(engine.target_dungeon,'a')

    def test_cross_tier_failure_retreats_then_retries_and_campaign_end_repeats(self):
        cfg=settings();cfg['farming'].update(mode='push',difficulty='Normal',dungeon_id='b',
            progression=[{'dungeon_id':m,'difficulty':d} for d in ('Normal','Nightmare','Inferno') for m in ('a','b')])
        engine=ManagedMode(cfg);engine.start(scene('b'))
        self.finish(engine,'success','normal-end');self.assertEqual(engine.target_difficulty,'Nightmare')
        self.finish(engine,'failed','nightmare-first');self.assertEqual((engine.target_dungeon,engine.target_difficulty),('b','Normal'))
        self.finish(engine,'success','normal-retry');self.assertEqual((engine.target_dungeon,engine.target_difficulty),('a','Nightmare'))
        for i in range(4):self.finish(engine,'success',str(i))
        self.assertEqual((engine.target_dungeon,engine.target_difficulty),('b','Inferno'))

    def test_two_maps_count_only_successful_runs_and_cycle_with_difficulty(self):
        cfg=settings();cfg['farming']['repeat_maps']=[{'dungeon_id':'a','difficulty':'current','runs':2},
                                                     {'dungeon_id':'b','difficulty':'Nightmare','runs':3}]
        engine=ManagedMode(cfg);engine.start(scene('a'))
        for n in range(20):self.assertIsNone(engine.next_action(scene('a',run_id='same-running')))
        self.assertEqual(engine.repeat_completed,0)
        for i,expected in enumerate([('a','Normal',1),('b','Nightmare',0),('b','Nightmare',1),('b','Nightmare',1),('b','Nightmare',2),('a','Normal',0)]):
            self.finish(engine,'failed' if i==3 else 'success','run-'+str(i))
            self.assertEqual((engine.target_dungeon,engine.target_difficulty,engine.repeat_completed),expected)

    def test_mid_run_inventory_return_and_pause_keep_partial_repeat_count(self):
        cfg=settings();cfg['farming']['repeat_maps']=[{'dungeon_id':'a','difficulty':'current','runs':3}]
        engine=ManagedMode(cfg);engine.start(scene('a'));self.finish(engine,'success','run-1')
        full=scene('a');full['counts']['inventory']['occupied']=39
        action=engine.next_action(full);self.assertEqual(action['kind'],'return_town');verified(engine,action)
        self.assertEqual(engine.repeat_completed,1)
        engine.pause();engine.resume(scene(None,'Normal',town=True));self.assertEqual(engine.repeat_completed,1)

    def test_unrelated_run_at_startup_is_not_counted(self):
        engine=ManagedMode(settings());engine.start(scene('b'))
        engine.next_action(scene('b',status='success',run_id='old-b'))
        self.assertEqual(engine.repeat_completed,0);self.assertIsNone(engine.last_success)

    def test_legacy_single_map_migrates_without_modifying_input(self):
        old=settings();old['farming'].pop('repeat_maps');before=deepcopy(old)
        cfg=validate_settings(old)
        self.assertEqual(cfg['farming']['repeat_maps'],[{'dungeon_id':'a','difficulty':'current','runs':1}])
        self.assertEqual(old,before)
        for rows in (None,[{'dungeon_id':'a','difficulty':'Normal','runs':0}],
                     [{'dungeon_id':'a','difficulty':'Normal','runs':True}],
                     [{'dungeon_id':'a','difficulty':'Normal','runs':1}]*2):
            bad=settings();bad['farming']['repeat_maps']=rows
            with self.assertRaises(ValidationError):validate_settings(bad)

    def test_automatic_push_uses_highest_native_unlock_and_full_backward_route(self):
        maps=[{'id':'a','map_type':0,'prerequisite':None},{'id':'b','map_type':0,'prerequisite':'a'},
              {'id':'c','map_type':0,'prerequisite':'b'},{'id':'side','map_type':1,'prerequisite':'c'}]
        control={'difficulties':[{'id':d,'unlocked':d!='Inferno'} for d in ('Normal','Nightmare','Inferno')],
                 'maps_by_difficulty':{d:[{'id':k,'unlocked':k!='c' or d=='Normal'} for k in ('a','b','c','side')]
                                       for d in ('Normal','Nightmare','Inferno')}}
        target=highest_unlocked_map(maps,control);self.assertEqual(target,{'dungeon_id':'b','difficulty':'Nightmare'})
        cfg=settings();cfg['farming'].update(mode='push',progression=full_campaign_route(maps))
        world=scene('a');world['farming_start']=target
        engine=ManagedMode(cfg);engine.start(world);self.assertEqual((engine.target_dungeon,engine.target_difficulty),('b','Nightmare'))


if __name__=='__main__':unittest.main()
