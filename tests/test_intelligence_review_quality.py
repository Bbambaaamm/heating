"""Regression: November candidate had 1/5 timely warnings and 40/40 false positives."""
from copy import deepcopy
import unittest

from custom_components.heating_observer.intelligence import HeatingIntelligenceAgent, review_failures
from custom_components.heating_observer.permissions import PermissionManifest


GOOD = dict(fault_incidents=5, detected=5, timely=5, missed=0, late=0,
            normal_controls=40, warned_normal=4, warned_normal_rate=0.1)


class ReviewQualityTests(unittest.TestCase):
    def test_november_candidate_fails_both_timeliness_and_noise(self):
        failures = review_failures(dict(GOOD, timely=1, late=4, warned_normal=40, warned_normal_rate=1))
        self.assertIn("not_all_faults_detected_in_time", failures)
        self.assertIn("warned_normal_rate_above_10_percent", failures)

    def test_late_only_and_false_positive_only_each_fail(self):
        self.assertTrue(review_failures(dict(GOOD, timely=4, late=1)))
        self.assertTrue(review_failures(dict(GOOD, warned_normal=5)))
        self.assertEqual(review_failures(GOOD), [])

    def test_invalid_missing_inconsistent_and_cached_rates_cannot_bypass_gate(self):
        for metrics in ({}, [1], True, dict(GOOD, timely=float('nan')), dict(GOOD, timely=True),
                        dict(GOOD, warned_normal=-1), dict(GOOD, normal_controls=9),
                        dict(GOOD, detected=4), dict(GOOD, warned_normal=40, warned_normal_rate=0)):
            self.assertTrue(review_failures(metrics), metrics)

    def test_failed_validation_does_not_select_another_rule_using_holdout(self):
        rule = {"rule":"evidence_winner", "description":"candidate", "evidence":{},
                "validation":dict(GOOD, timely=1, late=4, warned_normal=40)}
        second = deepcopy(rule)
        second.update(rule="holdout_winner", validation=GOOD)
        replay = {"enough_for_candidate_review":True, "rules":[rule,second],
                  "descriptive_rule_order":["evidence_winner","holdout_winner"]}
        result = HeatingIntelligenceAgent(PermissionManifest.load_default()).propose(replay)
        self.assertEqual(result["candidate_rule"], "evidence_winner")
        self.assertEqual(result["status"], "VALIDATION_FAILED_OR_INCOMPLETE")
        self.assertFalse(result["deployment_allowed"])
        self.assertFalse(result["active_policy_changed"])
