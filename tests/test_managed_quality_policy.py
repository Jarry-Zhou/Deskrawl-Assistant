from copy import deepcopy
import unittest

from deskrawl_assistant.managed_mode import (ManagedMode, validate_settings, equipment_policy,
    DISPOSABLE_BUCKETS, EQUIPMENT_BUCKETS, BUCKET_LABELS)
from deskrawl_assistant.managed_service import required_capabilities
from deskrawl_assistant.models import ValidationError
from test_managed_mode import settings, observation, equipment, verified


def mixed_settings(**changes):
    result=settings(**changes)
    result['cleanup']['equipment_policies']={k:{'action':'sell' if k in ('normal','uncommon') else 'salvage',
        'fallback':'sell' if k in ('normal','uncommon') else 'salvage'} for k in DISPOSABLE_BUCKETS}
    return result


class QualityPolicyTests(unittest.TestCase):
    def test_old_config_migrates_preserving_preferences_and_alias_isolation(self):
        raw=settings(equipment_action='salvage',equipment_fallback='sell')
        del raw['cleanup']['equipment_policies']
        validated=validate_settings(raw)
        for policy in validated['cleanup']['equipment_policies'].values():
            self.assertEqual(policy,{'action':'salvage','fallback':'sell'})
        validated['cleanup']['equipment_policies']['rare']['action']='store'
        self.assertEqual(validated['cleanup']['equipment_policies']['normal']['action'],'salvage')
        self.assertEqual(raw['cleanup']['equipment_action'],'salvage')
        self.assertEqual(validate_settings(validated),validated)

    def test_validation_rejects_protected_unknown_qualities_and_bad_fallbacks(self):
        for policies in ({'black_mist':{'action':'sell','fallback':'sell'}}, {'divine':{'action':'salvage','fallback':'sell'}},
                         {'unknown':{'action':'store','fallback':'sell'}}, {'rare':{'action':'sell','fallback':'store'}},
                         {'rare':{'action':'destroy','fallback':'sell'}}, {'rare':{'action':'sell'}}, None):
            with self.subTest(policies=policies),self.assertRaises(ValidationError):
                raw=settings();raw['cleanup']['equipment_policies']=policies;validate_settings(raw)

    def test_direct_cleaning_uses_each_equipment_quality(self):
        rows=[equipment(str(n),slot=n,rarity=rarity,is_ancient=ancient)
              for n,(rarity,ancient) in enumerate(((0,False),(1,False),(2,False),(3,False),(3,True)))]
        engine=ManagedMode(mixed_settings());world=observation(rows,town=True);engine.start(world)
        kinds=[]
        for _ in range(5):
            action=engine.next_action(world);kinds.append(action['kind'])
            uid=action['item']['item_uid'];verified(engine,action)
            rows=[r for r in rows if r['item_uid']!=uid];world=observation(rows,town=True)
        self.assertEqual(kinds,['sell','sell','salvage','salvage','salvage'])

    def test_protection_precedes_quality_policy_for_ancient_matched_and_locked_items(self):
        for extra in ({'rarity':4},{'is_black_mist':True},{'is_ancient':True,'matches':True},{'rarity':0,'matches':True},
                      {'rarity':1,'locked':True}):
            with self.subTest(extra=extra):
                row=equipment('keep',**extra);world=observation([row],town=True)
                engine=ManagedMode(mixed_settings());engine.start(world)
                action=engine.next_action(world)
                self.assertIn(action['kind'],('lock','transfer'))
                if action['kind']=='lock':
                    verified(engine,action);row['locked']=True;action=engine.next_action(observation([row],town=True))
                self.assertEqual((action['kind'],action['target']),('transfer','storage'))

    def test_full_storage_and_bag_space_fallback_use_the_disposed_items_quality(self):
        engine=ManagedMode(mixed_settings())
        junk=equipment('junk',container='storage',rarity=2)
        for rarity,expected in ((0,'sell'),(1,'sell'),(2,'salvage'),(3,'salvage')):
            with self.subTest(rarity=rarity):
                row=equipment('bag',rarity=rarity)
                world=observation([row,junk],town=True,allowed=[0])
                action=engine._storage_transfer(world,row,[1],[row,junk])
                self.assertEqual(action['kind'],expected)
                self.assertEqual(action['reason_code'],'equipment_fallback')
        keep=equipment('keep',slot=1,rarity=4,locked=True)
        ordinary=equipment('ordinary',rarity=0)
        world=observation([ordinary,keep,junk],town=True,capacity=2,allowed=[0])
        action=engine._storage_transfer(world,keep,[1],[ordinary,keep,junk],mandatory=True)
        self.assertEqual((action['kind'],action['item']['item_uid']),('sell','ordinary'))

    def test_evicted_warehouse_junk_uses_its_quality_fallback_after_transfer(self):
        engine=ManagedMode(mixed_settings())
        keep=equipment('keep',rarity=4,locked=True)
        junk=equipment('junk',container='storage',rarity=2)
        world=observation([keep,junk],town=True,allowed=[0]);engine.start(world)
        action=engine.next_action(world)
        self.assertEqual(action['reason_code'],'warehouse_eviction')
        verified(engine,action);junk.update(container='inventory',slot_index=1)
        action=engine.next_action(observation([keep,junk],town=True,allowed=[0]))
        self.assertEqual((action['kind'],action['item']['item_uid']),('salvage','junk'))

    def test_store_can_be_selected_per_quality_and_mixed_capabilities_are_required(self):
        s=mixed_settings();s['cleanup']['equipment_policies']['ancient']['action']='store'
        keep=equipment('ancient',is_ancient=True)
        engine=ManagedMode(s);world=observation([keep],town=True);engine.start(world)
        action=engine.next_action(world)
        self.assertEqual((action['kind'],action['target']),('transfer','storage'))
        self.assertTrue({'sell','salvage'} <= required_capabilities(engine.settings))
        with self.assertRaises(ValidationError):equipment_policy(engine.settings['cleanup'],{'rarity':4})
        self.assertEqual(list(ManagedMode(s).metrics.state()['equipment']),list(EQUIPMENT_BUCKETS))
        self.assertEqual([BUCKET_LABELS[k] for k in EQUIPMENT_BUCKETS],['神圣','黑雾传说','远古传说','普通传说','稀有','优秀','普通'])


if __name__=='__main__':unittest.main()
