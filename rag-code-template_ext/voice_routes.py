"""X3 음성 질의: 음성 → 텍스트(STT) → 기존 /rag-query → 텍스트 → 음성(TTS).

교재 voice-ai_code 예제와 같은 흐름이지만, 질의는 우리 RAG(/rag-query)가 맡고 여기서는 변환만 한다.
- STT: OpenAI gpt-4o-mini-transcribe (예제의 로컬 faster-whisper 대신 API. whisper-1보다 입찰 용어를 덜 틀림)
- TTS: OpenAI tts-1 (예제와 같은 모델)
- 올린 음성은 디스크에 저장하지 않고 메모리에서만 처리한다 (예제는 uploads/에 저장)
화면(5번 QaView): POST /stt (multipart 필드 audio) → {text}, POST /tts {text} → 오디오(mp3).
"""
import io
import logging
import os

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(tags=["음성 질의 (X3)"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024     # 질문 한 마디면 충분. 큰 파일로 비용이 새는 것을 막는다
MAX_TTS_CHARS = 1500                   # 답변 읽기용. OpenAI 한도(4096자)보다 짧게 잘라 응답 시간을 줄인다
STT_MODEL = os.getenv("STT_MODEL", "gpt-4o-mini-transcribe")  # whisper-1보다 정확 · 빠름 (eval/MODEL_COMPARISON.md)
TTS_MODEL = os.getenv("TTS_MODEL", "tts-1")
TTS_VOICE = os.getenv("TTS_VOICE", "nova")
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mpeg", "audio/mp3", "audio/mp4", "audio/m4a", "audio/x-m4a",
               "audio/wav", "audio/x-wav", "audio/wave", "video/webm"}  # 크롬 MediaRecorder는 video/webm으로 보내기도 함


def _client():
    from openai import OpenAI
    return OpenAI(timeout=60, max_retries=1)


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


@router.post("/stt", summary="음성 → 텍스트 (질문 받아쓰기)")
def speech_to_text(audio: UploadFile = File(...)):
    # 동기 함수로 두어 OpenAI 호출을 기다리는 동안 다른 요청이 막히지 않게 한다 (FastAPI가 스레드에서 실행)
    content_type = (audio.content_type or "").split(";")[0].strip().lower()
    if content_type and content_type not in AUDIO_TYPES:
        raise HTTPException(status_code=415, detail=f"지원하지 않는 음성 형식입니다: {content_type}")
    data = audio.file.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="녹음된 음성이 없습니다.")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="음성 파일은 10MB 이하로 보내 주세요.")
    buffer = io.BytesIO(data)
    buffer.name = audio.filename or "question.webm"   # 확장자로 형식을 판별하므로 이름이 필요
    try:
        result = _client().audio.transcriptions.create(model=STT_MODEL, file=buffer, language="ko")
    except Exception as error:   # 원문에 키 · 요청 내용이 섞일 수 있어 종류만 남긴다
        logger.warning("STT 실패: %s", type(error).__name__)
        raise HTTPException(status_code=502, detail="음성 인식에 실패했습니다. 다시 말씀해 주세요.") from None
    text = (result.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="말소리를 알아듣지 못했습니다. 다시 말씀해 주세요.")
    return {"text": text}


@router.post("/tts", summary="텍스트 → 음성 (답변 읽어 주기, mp3)")
def text_to_speech(request: TtsRequest):
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="읽을 내용이 없습니다.")
    if len(text) > MAX_TTS_CHARS:
        text = text[:MAX_TTS_CHARS].rsplit(" ", 1)[0] + " 이하 내용은 화면에서 확인해 주세요."
    try:
        speech = _client().audio.speech.create(model=TTS_MODEL, voice=TTS_VOICE, input=text, response_format="mp3")
        audio = speech.read() if hasattr(speech, "read") else speech.content
    except Exception as error:
        logger.warning("TTS 실패: %s", type(error).__name__)
        raise HTTPException(status_code=502, detail="음성 합성에 실패했습니다.") from None
    return Response(content=audio, media_type="audio/mpeg")
