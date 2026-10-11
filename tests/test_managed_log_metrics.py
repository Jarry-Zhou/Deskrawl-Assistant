import unittest

from deskrawl_assistant.managed_mode import ManagedMetrics
import test_managed_mode as fixtures
from test_managed_mode import equipment, observation
from test_game_panel_log import packet, event


def disposal(id_,action='sell',rarity=0,name='CommonBow1',gold=100):
    return dict(event(id_),receipt={'action':action,'quantity':1,'gold':gold if action=='sell' else None,
        'item':{'kind':'equipment','is_equipment':True,'rarity':rarity,'name_key':name,'internal_name':name,'count':1}})


class LogMetricsTests(unittest.TestCase):
    def ledger(self,*args,**kwargs):return fixtures.MetricsTests().ledger(*args,**kwargs)

    def observe(self,metric,records=(),*,rows=(),ledger=None,**kwargs):
        world=observation(rows,system_log=packet(*records),loot_ledger=ledger or self.ledger())
        world.update(kwargs)
        metric.observe(world)
        return world

    def test_exact_log_counts_without_estimates_or_policy_dependency(self):
        metric=ManagedMetrics();old=disposal('old');self.observe(metric,[old])
        new=[old,disposal('one'),disposal('two'),disposal('salvage','salvage',2)]
        ledger=self.ledger({0:2,2:1},policy={'0':2,'2':0})
        self.observe(metric,new,ledger=ledger)
        self.assertEqual(metric.state()['equipment']['normal']['sold'],2)
        for _ in range(3):self.observe(metric,new,ledger=ledger)
        stats=metric.state();normal=stats['equipment']['normal'];rare=stats['equipment']['rare']
        self.assertEqual((normal['count'],normal['sold'],rare['salvaged']),(2,2,1))
        self.assertNotIn('estimated_sold',normal);self.assertNotIn('estimated_salvaged',rare)
        self.assertEqual(stats['game_log']['sale_gold'],200)
        self.assertEqual(stats['game_log']['confirmed_disposals'],3)

    def test_inventory_action_receipts_and_high_grade_ledger_remain_separate(self):
        metric=ManagedMetrics();self.observe(metric)
        row=equipment('new',rarity=0)
        self.observe(metric,rows=[row]);metric.committed('assistant-sale',row,'sell')
        native=self.ledger({0:1,3:1},[{'index':0,'action':'salvage','item':equipment('ancient',is_ancient=True)}])
        records=[disposal('native'),disposal('high-log','salvage',3,name='LegendaryNeck1')]
        self.observe(metric,records,ledger=native);self.observe(metric,records,ledger=native)
        values=metric.state()['equipment']
        self.assertEqual(values['normal']['sold'],2)
        self.assertEqual((values['ancient']['salvaged'],values['legendary']['salvaged']),(1,0))
        metric.committed('assistant-sale',row,'sell')
        self.assertEqual(metric.state()['equipment']['normal']['sold'],2)

    def test_initial_inventory_sale_not_counted_but_same_named_native_drop_is(self):
        row=equipment('initial',rarity=0,name_key='CommonBow1')
        metric=ManagedMetrics();self.observe(metric,rows=[row]);metric.committed('sell-initial',row,'sell')
        self.observe(metric,[disposal('native')]);self.observe(metric,[disposal('native')])
        self.assertEqual(metric.state()['equipment']['normal']['sold'],1)

    def test_initial_ground_disposal_excluded_even_if_log_and_sources_straddle_action(self):
        row=equipment('initial',rarity=0,name_key='CommonBow1',container='ground')
        metric=ManagedMetrics()
        ground={'complete':True,'available':True,'items':[row]}
        self.observe(metric,ground=ground)
        records=[disposal('initial-sale')]
        self.observe(metric,records,ground=ground)  # source read predates the log append
        self.observe(metric,records)
        self.assertEqual(metric.state()['equipment']['normal']['sold'],0)
        records.append(disposal('new-sale'))
        self.observe(metric,records);self.observe(metric,records)
        self.assertEqual(metric.state()['equipment']['normal']['sold'],1)

    def test_initial_ground_pickup_does_not_hide_later_same_named_native_disposal(self):
        row=equipment('initial',rarity=0,name_key='CommonBow1',container='ground')
        metric=ManagedMetrics();self.observe(metric,ground={'complete':True,'items':[row]})
        row['container']='inventory';self.observe(metric,rows=[row])
        self.observe(metric,[disposal('new-sale')],rows=[row]);self.observe(metric,[disposal('new-sale')],rows=[row])
        self.assertEqual(metric.state()['equipment']['normal']['sold'],1)

    def test_failed_read_recovers_without_estimate_double_count_and_coverage_loss_is_visible(self):
        metric=ManagedMetrics();self.observe(metric)
        ledger=self.ledger({0:2})
        metric.observe(observation(system_log={'available':False},loot_ledger=ledger))
        self.assertEqual(metric.state()['equipment']['normal']['sold'],0)
        records=[disposal('one'),disposal('two')]
        self.observe(metric,records,ledger=ledger);self.observe(metric,records,ledger=ledger)
        self.assertEqual(metric.state()['equipment']['normal']['sold'],2)
        self.assertFalse(metric.state()['game_log']['incomplete'])
        self.observe(metric,[disposal('three')],ledger=self.ledger({0:3}))
        self.observe(metric,[disposal('three')],ledger=self.ledger({0:3}))
        self.assertEqual(metric.state()['equipment']['normal']['sold'],3)
        self.assertTrue(metric.state()['game_log']['incomplete'])
        self.assertIn('可能不完整',metric.state()['note'])

    def test_unknown_disposal_is_flagged_and_no_inference_is_substituted(self):
        metric=ManagedMetrics();self.observe(metric)
        self.observe(metric,[event('unknown')],ledger=self.ledger({0:1}))
        self.observe(metric,[event('unknown')],ledger=self.ledger({0:1}))
        self.assertEqual(metric.state()['equipment']['normal']['sold'],0)
        self.assertEqual(metric.state()['game_log']['unparsed'],1)


if __name__=='__main__':unittest.main()
