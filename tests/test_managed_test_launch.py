"""Local opt-in wiring only; no processes, windows or game calls are started."""
import unittest
from unittest.mock import Mock, patch

from deskrawl_assistant.launcher import main
from deskrawl_assistant.runtime_client import RuntimeClient


class ManagedTestLaunchTests(unittest.TestCase):
    def test_regular_desktop_launch_leaves_test_mode_disabled(self):
        with patch('deskrawl_assistant.native_window.main') as desktop:
            main([])
        desktop.assert_called_once_with(18741,test_managed=False)

    def test_explicit_local_flag_reaches_desktop_host(self):
        with patch('deskrawl_assistant.native_window.main') as desktop:
            main(['--test-managed'])
        desktop.assert_called_once_with(18741,test_managed=True)

    def test_explicit_local_flag_reaches_headless_host(self):
        with patch('deskrawl_assistant.web_server.main') as serve:
            main(['--test-managed','--no-browser','--port','18742'])
        serve.assert_called_once_with(port=18742,open_browser=False,test_managed=True)

    def test_runtime_does_not_install_or_verify_until_explicit_action(self):
        for enabled in (False,True):
            with patch('deskrawl_assistant.game_actions.GameActions') as actions:
                client = RuntimeClient(managed_test_mode=enabled)
                actions.assert_not_called()
                client._reader = Mock()
                client._game_actions()
                actions.assert_called_once_with(client._reader,allow_unverified=enabled)
                actions.return_value.execute.assert_not_called()

    def test_runtime_rejects_non_boolean_local_flag(self):
        for invalid in ('true',1,None):
            with self.assertRaises(ValueError): RuntimeClient(managed_test_mode=invalid)


if __name__=='__main__': unittest.main()
