import base64
import json
import unittest
from urllib.parse import quote
from detector.core import detect


class RepresentationTests(unittest.TestCase):
    def test_encoded_secret_covers_original_utf8_span(self):
        secret="sk-" + "syntheticvalue"*3
        encodings=[quote(secret,safe="").replace("-","%2D"),base64.b64encode(secret.encode()).decode()]
        encodings.append(base64.b64encode(encodings[0].encode()).decode())
        for value in encodings:
            with self.subTest(value=value):
                text="🌍 " + value
                spans=detect(text)
                self.assertEqual(len(spans),1)
                self.assertEqual(spans[0]["kind"],"SECRET")
                self.assertEqual(text.encode()[spans[0]["start"]:spans[0]["end"]].decode(),value)

    def test_jwt_requires_json_header_and_payload(self):
        encode=lambda x:base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip("=")
        value=encode({"alg":"HS256"})+"."+encode({"sub":"synthetic"})+"."+"x"*32
        self.assertEqual(detect(value)[0]["kind"],"SECRET")
        self.assertEqual(detect("ordinary.segment.fragment"),[])

    def test_placeholders_do_not_exempt_real_neighbors(self):
        self.assertEqual(detect("Documentation: api_key=YOUR_API_KEY_HERE"),[])
        self.assertTrue(detect("api_key=YOUR_API_KEY_HERE password=actuallySensitive"))
        self.assertTrue(detect("api_key=YOUR_API_KEY_HERE_suffix"))

    def test_benign_encoded_data_and_opaque_identifiers(self):
        self.assertEqual(detect(base64.b64encode(b"ordinary project documentation").decode()),[])
        self.assertEqual(detect("Request identifier AbCdEf0123456789AbCdEf0123456789"),[])
