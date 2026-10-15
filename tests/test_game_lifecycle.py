"""No process enumeration, Steam launch or game shutdown in these tests."""
import threading
import unittest
from unittest.mock import Mock

from deskrawl_assistant.game_lifecycle import GameLifecycle
from deskrawl_assistant.web_service import AssistantService
from deskrawl_assistant.models import ValidationError


class GameLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.backend=Mock();self.backend.instances.return_value=[]
        self.now=0
        self.game=GameLifecycle(self.backend,clock=lambda:self.now)
        self.target={'pid':42,'instance':'42:1234'}

    def test_steam_launch_waits_for_process_and_disallows_duplicate_start(self):
        self.assertTrue(self.game.state()['can_start'])
        self.assertEqual(self.game.start()['status'],'starting')
        with self.assertRaises(ValueError):self.game.start()
        self.backend.launch.assert_called_once_with()
        self.backend.instances.return_value=[self.target]
        state=self.game.state(fresh=True)
        self.assertEqual(state['status'],'running')
        self.assertTrue(state['can_close']);self.assertFalse(state['can_start'])
        self.assertEqual(state['target'],self.target)

    def test_unknown_or_multiple_processes_cannot_be_closed(self):
        self.backend.instances.side_effect=PermissionError('access denied')
        state=self.game.state(fresh=True)
        self.assertEqual(state['status'],'unknown')
        self.assertFalse(state['can_start']);self.assertFalse(state['can_close'])
        with self.assertRaises(ValueError):self.game.start()
        self.backend.launch.assert_not_called()
        self.backend.instances.side_effect=None
        self.backend.instances.return_value=[self.target,{'pid':43,'instance':'43:12'}]
        with self.assertRaises(ValueError):self.game.close(self.target)
        self.backend.close.assert_not_called()

    def test_close_rechecks_process_identity_and_waits_for_exit(self):
        self.backend.instances.return_value=[self.target]
        self.assertTrue(self.game.state()['can_close'])
        self.backend.instances.return_value=[dict(self.target,instance='42:5678')]
        with self.assertRaisesRegex(ValueError,'变化'):self.game.close(self.target)
        self.backend.close.assert_not_called()
        self.backend.instances.return_value=[self.target]
        self.assertEqual(self.game.close(self.target)['status'],'closing')
        self.backend.close.assert_called_once_with(self.target)
        self.assertFalse(self.game.state()['can_close'])
        self.backend.instances.return_value=[]
        self.assertEqual(self.game.state(fresh=True)['status'],'stopped')

    def test_failed_transition_expires_with_retry_and_error(self):
        self.game.start();self.now=61
        state=self.game.state()
        self.assertTrue(state['can_start']);self.assertIn('Steam',state['error'])
        self.backend.instances.return_value=[self.target]
        self.game.close(self.target);self.now+=21
        state=self.game.state()
        self.assertTrue(state['can_close']);self.assertIn('尚未退出',state['error'])


class GameActionServiceTests(unittest.TestCase):
    def setUp(self):
        self.service=object.__new__(AssistantService)
        s=self.service
        s.guard=threading.RLock();s.closed=threading.Event()
        s.updating=False;s.game_transition=False;s.busy=False;s.worker=None
        s.stop=Mock();s.journal=Mock();s.game_lifecycle=Mock()
        self.target={'pid':42,'instance':'42:1234'}
        s.game_lifecycle.state.return_value={'can_close':True,'target':self.target,'status':'running'}

    def test_close_requires_confirmation_and_current_process_before_stopping(self):
        for payload in ({},{'confirmed':False,'target':self.target},
                        {'confirmed':True,'target':dict(self.target,instance='42:old')}):
            with self.assertRaises(ValidationError):self.service.game_action('close',payload)
        self.service.stop.assert_not_called();self.service.game_lifecycle.close.assert_not_called()

    def test_close_stops_writers_then_uses_normal_close(self):
        calls=[];s=self.service
        s.stop.side_effect=lambda:calls.append(('stop',s.game_transition))
        s.game_lifecycle.close.side_effect=lambda target:calls.append(('close',target)) or {'status':'closing'}
        self.assertEqual(s.game_action('close',{'confirmed':True,'target':self.target}),{'status':'closing'})
        self.assertEqual(calls,[('stop',True),('close',self.target)])
        self.assertFalse(s.game_transition)
        s.game_lifecycle.state.return_value={'status':'closing'}
        self.assertTrue(s.game_actions_blocked())

    def test_inflight_writer_prevents_close_and_releases_transition_flag(self):
        self.service.busy=True
        with self.assertRaisesRegex(ValidationError,'尚未结束'):
            self.service.game_action('close',{'confirmed':True,'target':self.target})
        self.service.game_lifecycle.close.assert_not_called()
        self.assertFalse(self.service.game_transition)

    def test_start_does_not_require_game_connection(self):
        self.service.game_action('start',{})
        self.service.game_lifecycle.start.assert_called_once_with()
        self.service.stop.assert_not_called()
        with self.assertRaises(ValidationError):self.service.game_action('start',{'pid':42})


if __name__=='__main__':unittest.main()
