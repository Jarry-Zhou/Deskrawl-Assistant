"""Retired reports must not sample the game or alter existing reporting data."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from deskrawl_assistant import features
from deskrawl_assistant.runtime_client import RuntimeClient
from deskrawl_assistant.web_service import AssistantService


class DisabledReportingTests(unittest.TestCase):
    def test_startup_creates_no_report_worker_or_database_and_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            archives=[root/'experience.sqlite3',root/'recommendations.sqlite3']
            for archive in archives:archive.write_bytes(b'existing-report-data')
            client=SimpleNamespace(connected=False,close=Mock(),
                experience_snapshot=Mock(side_effect=AssertionError('experience sampled')),
                recommendation_snapshot=Mock(side_effect=AssertionError('recommendation sampled')))
            with patch('deskrawl_assistant.web_service.ExperienceBook',side_effect=AssertionError('opened experience database')), \
                 patch('deskrawl_assistant.web_service.RecommendationBook',side_effect=AssertionError('opened recommendation database')):
                service=AssistantService(client,root/'rules.json')
                try:
                    self.assertFalse(features.REPORTING_ENABLED)
                    self.assertIsNone(service.experience)
                    self.assertIsNone(service.recommendations)
                    self.assertIsNone(service.recommendation_thread)
                    self.assertTrue(service.experience_live()['disabled'])
                    self.assertTrue(service.experience_page()['disabled'])
                    self.assertTrue(service._observe_recommendation()['disabled'])
                    self.assertTrue(service.recommendation_page()['disabled'])
                    service._recommendation_loop()
                    for action in ('start','sample','finish','delete','cancel'):
                        with self.assertRaisesRegex(ValueError,'已停用'):
                            service.experience_action(action,{})
                    with self.assertRaisesRegex(ValueError,'已停用'):service.recommendation_settings({})
                    with self.assertRaisesRegex(ValueError,'已停用'):service.recommendation_reset()
                finally:service.close()
            for archive in archives:self.assertEqual(archive.read_bytes(),b'existing-report-data')
            client.experience_snapshot.assert_not_called()
            client.recommendation_snapshot.assert_not_called()

    def test_runtime_report_entry_points_return_before_any_game_access(self):
        client=RuntimeClient.__new__(RuntimeClient)
        with patch('deskrawl_assistant.experience_reader.read_experience') as xp, \
             patch('deskrawl_assistant.recommendation_reader.read_recommendation') as reports:
            self.assertTrue(client.experience_snapshot()['disabled'])
            self.assertTrue(client.recommendation_snapshot()['disabled'])
        xp.assert_not_called();reports.assert_not_called()


if __name__=='__main__':unittest.main()
