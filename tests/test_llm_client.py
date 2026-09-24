import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from voxlab.llm_client import _request


ROOT = Path(__file__).resolve().parents[1]


def _http_error(code, body=b'{"error": "boom"}'):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body))


class RetryTests(unittest.TestCase):

    @mock.patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"})
    def test_retries_on_5xx_then_succeeds(self):
        success = mock.MagicMock()
        success.__enter__.return_value.read.return_value = json.dumps({"ok": True}).encode()
        with mock.patch("voxlab.llm_client.urllib.request.urlopen",
                       side_effect=[_http_error(500), _http_error(502), success]) as mocked, \
             mock.patch("voxlab.llm_client.time.sleep"):
            result = _request(ROOT, "http://example", {"a": 1})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(mocked.call_count, 3)

    @mock.patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"})
    def test_retries_on_429_engine_overloaded(self):
        success = mock.MagicMock()
        success.__enter__.return_value.read.return_value = json.dumps({"ok": True}).encode()
        with mock.patch("voxlab.llm_client.urllib.request.urlopen",
                       side_effect=[_http_error(429), success]) as mocked, \
             mock.patch("voxlab.llm_client.time.sleep"):
            result = _request(ROOT, "http://example", {"a": 1})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(mocked.call_count, 2)

    @mock.patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"})
    def test_does_not_retry_on_4xx_client_error(self):
        with mock.patch("voxlab.llm_client.urllib.request.urlopen",
                       side_effect=_http_error(402)) as mocked, \
             mock.patch("voxlab.llm_client.time.sleep"):
            with self.assertRaises(RuntimeError):
                _request(ROOT, "http://example", {"a": 1})
        self.assertEqual(mocked.call_count, 1)

    @mock.patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"})
    def test_retries_on_timeout(self):
        success = mock.MagicMock()
        success.__enter__.return_value.read.return_value = json.dumps({"ok": True}).encode()
        with mock.patch("voxlab.llm_client.urllib.request.urlopen",
                       side_effect=[TimeoutError("slow"), success]) as mocked, \
             mock.patch("voxlab.llm_client.time.sleep"):
            result = _request(ROOT, "http://example", {"a": 1})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(mocked.call_count, 2)

    @mock.patch.dict("os.environ", {"DEEPINFRA_API_KEY": "test-key"})
    def test_gives_up_after_max_attempts(self):
        with mock.patch("voxlab.llm_client.urllib.request.urlopen",
                       side_effect=TimeoutError("slow")) as mocked, \
             mock.patch("voxlab.llm_client.time.sleep"):
            with self.assertRaises(RuntimeError):
                _request(ROOT, "http://example", {"a": 1})
        self.assertEqual(mocked.call_count, 6)

    def test_missing_api_key_raises_without_printing_env(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                _request(Path(tmp), "http://example", {"a": 1})


if __name__ == "__main__":
    unittest.main()
