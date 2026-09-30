import unittest
from unittest.mock import patch
from experiments.corpus import build
from experiments.secrets import exposed,wilson
from experiments.triage import assignment,summarize
from experiments.summarize import memory_bytes
from experiments.run import restore_service

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

class TriageStudyTests(unittest.TestCase):
    def test_balanced_assignment_is_reproducible(self):
        cases=assignment("participant-a")
        self.assertEqual(cases,assignment("participant-a"))
        self.assertEqual(len(cases),24)
        for pair in range(12):
            self.assertEqual({c["mode"] for c in cases if c["pair"]==pair},{"manual","assisted"})
    def test_incomplete_study_cannot_claim_speedup(self):
        result=summarize([{"mode":"manual","seconds":10,"wrong_attempts":0}],False)
        self.assertNotIn("median_reduction_percent",result)
    def test_actual_medians_and_corrections(self):
        rows=[{"mode":m,"seconds":s,"wrong_attempts":1} for m,s in [("manual",10),("manual",20),("assisted",8),("assisted",10)]]
        self.assertEqual(summarize(rows,True)["median_reduction_percent"],40)
        self.assertEqual(summarize(rows,True)["wrong_attempts"],4)

class ResourceSummaryTests(unittest.TestCase):
    def test_docker_memory_units_are_not_confused(self):
        self.assertEqual(memory_bytes("1.5MiB"),1.5*1024**2)
        self.assertEqual(memory_bytes("1.5MB"),1500000)
        self.assertEqual(memory_bytes("2kB"),2000)
        with self.assertRaises(ValueError):memory_bytes("missing")

class FaultControllerTests(unittest.TestCase):
    def test_restore_does_not_scale_unselected_services(self):
        for service in ("worker","detector","postgres","redis"):
            with self.subTest(service=service), patch("experiments.run.command") as command, patch("experiments.run.ready") as ready:
                restore_service(service)
                args=command.call_args.args[0]
                self.assertEqual(args[-1],service)
                self.assertIn("--no-deps",args)
                self.assertEqual("--scale" in args,service=="worker")
                ready.assert_called_once()
