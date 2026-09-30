import unittest
from experiments.corpus import build
from experiments.secrets import exposed,wilson

class SecretExperimentTests(unittest.TestCase):
    def test_deterministic_labeled_corpus(self):
        data=build(13,2)
        self.assertEqual(data,build(13,2))
        self.assertEqual(len(data["cases"]),36)
        self.assertEqual(len({c["id"] for c in data["cases"]}),36)
        for c in data["cases"]:
            self.assertEqual(bool(c["exposure_needles"]),c["label"]=="secret")
    def test_cross_message_exposure_is_counted(self):
        records=[{"messages":[{"content":"synthetic"},{"content":"secret"}]}]
        self.assertTrue(exposed(records,["syntheticsecret"]))
        self.assertFalse(exposed(records,["notpresent"]))
    def test_interval_does_not_treat_small_sample_as_proof(self):
        self.assertLess(wilson(10,10)[0],.99)
        self.assertIsNone(wilson(0,0))
