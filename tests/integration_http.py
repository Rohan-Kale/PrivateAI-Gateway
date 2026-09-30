"""Black-box smoke tests against a running stack. Uses generated keys, never prints them."""
import json
import os
import time
import unittest
import urllib.error
import urllib.request

BASE = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080")
KEYS = json.loads(os.environ["API_KEYS"])
KEY = next(k for k, v in KEYS.items() if v == "demo")
ADMIN = os.environ["ADMIN_KEY"]


def call(path, body=None, key=KEY, method=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=65) as response:
            raw = response.read().decode()
            return response.status, raw if "text/event-stream" in response.headers.get("Content-Type", "") else json.loads(raw)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.loads(error.read())


def prompt(text, stream=False):
    return {"model": "mock", "messages": [{"role": "user", "content": text}], "stream": stream}


class Integration(unittest.TestCase):
    def setUp(self):
        status, self.original = call("/v1/policy")
        self.assertEqual(status, 200)

    def tearDown(self):
        status, current = call("/v1/policy")
        if status == 200:
            self.original["version"] = current["version"]
            self.assertEqual(call("/admin/policies/demo", self.original, ADMIN, "PUT")[0], 200)

    def policy(self, action, restore=True, cache=60):
        _, current = call("/v1/policy")
        current.update(default="redact", rules={"SECRET": "block", "EMAIL": action}, restore=restore, cache_seconds=cache)
        self.assertEqual(call("/admin/policies/demo", current, ADMIN, "PUT")[0], 200)

    def test_actions_and_secret_block(self):
        for action, expected in [("allow", "alice@example.com"), ("redact", "[REDACTED_EMAIL]"), ("tokenize", "alice@example.com")]:
            self.policy(action)
            status, response = call("/v1/chat/completions", prompt("🌍 alice@example.com"))
            self.assertEqual(status, 200)
            self.assertIn(expected, response["choices"][0]["message"]["content"])
        self.policy("block")
        self.assertEqual(call("/v1/chat/completions", prompt("alice@example.com"))[0], 403)
        self.assertEqual(call("/v1/chat/completions", prompt("sk-" + "a" * 24))[0], 403)

    def test_no_restore_and_stream_roundtrip(self):
        self.policy("tokenize", restore=False)
        status, response = call("/v1/chat/completions", prompt("alice@example.com"))
        self.assertEqual(status, 200)
        content = response["choices"][0]["message"]["content"]
        self.assertIn("<PAI_", content)
        self.assertNotIn("alice@", content)
        self.policy("tokenize")
        status, stream = call("/v1/chat/completions", prompt("🌍 alice@example.com", True))
        self.assertEqual(status, 200)
        self.assertIn("data: [DONE]", stream)
        chunks = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
        self.assertEqual("".join(x["choices"][0]["delta"].get("content", "") for x in chunks), "Echo: 🌍 alice@example.com")

    def test_cache_policy_change_and_auth(self):
        self.policy("allow")
        body = prompt("hello cache")
        self.assertFalse(call("/v1/chat/completions", body)[1]["cached"])
        self.assertTrue(call("/v1/chat/completions", body)[1]["cached"])
        self.policy("redact")
        self.assertFalse(call("/v1/chat/completions", body)[1]["cached"])
        self.assertEqual(call("/v1/chat/completions", body, "invalid")[0], 401)
        self.assertEqual(call("/admin/policies/demo", self.original, KEY, "PUT")[0], 401)
        self.assertEqual(call("/admin/policies/demo", self.original, ADMIN, "PUT")[0], 409)
        bad = dict(body, tools=[])
        self.assertEqual(call("/v1/chat/completions", bad)[0], 400)

    @unittest.skipUnless(os.environ.get("TEST_QUEUE") == "1", "requires Redis queue and worker")
    def test_queue_and_tenant_isolation(self):
        status, job = call("/v1/jobs", prompt("queue hello"))
        self.assertEqual(status, 202)
        other = next(k for k, v in KEYS.items() if v == "other")
        self.assertEqual(call("/v1/jobs/" + job["id"], key=other)[0], 404)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status, result = call("/v1/jobs/" + job["id"])
            if result["status"] != "queued":
                break
            time.sleep(0.1)
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["content"], "Echo: queue hello")


if __name__ == "__main__":
    unittest.main(verbosity=2)
