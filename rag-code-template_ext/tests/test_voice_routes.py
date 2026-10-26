"""X3 음성 API(/stt, /tts) 검증. OpenAI 호출은 가짜로 바꿔 비용 · 네트워크 없음."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import voice_routes
except ImportError:
    voice_routes = None


class FakeOpenAI:
    def __init__(self, text="이 공고의 마감 일시는 언제야?"):
        self.sent = {}
        outer = self

        class Transcriptions:
            def create(self, **kw):
                outer.sent["stt"] = kw
                return type("R", (), {"text": text})()

        class Speech:
            def create(self, **kw):
                outer.sent["tts"] = kw
                return type("S", (), {"read": lambda self: b"ID3fake-mp3"})()

        self.audio = type("A", (), {"transcriptions": Transcriptions(), "speech": Speech()})()


@unittest.skipIf(voice_routes is None, "FastAPI 미설치")
class VoiceRoutesTest(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(voice_routes.router)
        self.client = TestClient(app)

    def test_stt_returns_text_without_saving_file(self):
        fake = FakeOpenAI()
        with mock.patch.object(voice_routes, "_client", return_value=fake):
            r = self.client.post("/stt", files={"audio": ("question.webm", b"webm-bytes", "audio/webm;codecs=opus")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"text": "이 공고의 마감 일시는 언제야?"})
        self.assertEqual(fake.sent["stt"]["language"], "ko")
        self.assertEqual(fake.sent["stt"]["file"].name, "question.webm")   # 메모리 버퍼 (디스크 저장 없음)

    def test_stt_rejects_bad_input(self):
        with mock.patch.object(voice_routes, "_client", return_value=FakeOpenAI(text="  ")):
            self.assertEqual(self.client.post("/stt", files={"audio": ("q.webm", b"", "audio/webm")}).status_code, 422)
            self.assertEqual(self.client.post("/stt", files={"audio": ("q.txt", b"x", "text/plain")}).status_code, 415)
            self.assertEqual(self.client.post("/stt", files={"audio": ("q.webm", b"x", "audio/webm")}).status_code, 422)
            big = b"0" * (voice_routes.MAX_AUDIO_BYTES + 1)
            self.assertEqual(self.client.post("/stt", files={"audio": ("q.webm", big, "audio/webm")}).status_code, 413)

    def test_tts_returns_mp3_and_trims_long_text(self):
        fake = FakeOpenAI()
        with mock.patch.object(voice_routes, "_client", return_value=fake):
            r = self.client.post("/tts", json={"text": "가 " * 2000})
        self.assertEqual((r.status_code, r.headers["content-type"], r.content), (200, "audio/mpeg", b"ID3fake-mp3"))
        self.assertLessEqual(len(fake.sent["tts"]["input"]), voice_routes.MAX_TTS_CHARS + 40)
        self.assertEqual(self.client.post("/tts", json={"text": ""}).status_code, 422)

    def test_provider_error_is_502_without_details(self):
        broken = mock.Mock()
        broken.audio.transcriptions.create.side_effect = RuntimeError("sk-secret in message")
        with mock.patch.object(voice_routes, "_client", return_value=broken):
            r = self.client.post("/stt", files={"audio": ("q.webm", b"x", "audio/webm")})
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("sk-secret", r.text)


if __name__ == "__main__":
    unittest.main()
