"""執行時設定 API：Ollama 模型、數字人引擎與角色。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp import web

from src.avatars.builder import uploads_dir
from src.avatars.catalog import resolve_preview_path
from src.server.import_jobs import VIDEO_EXTS, get_job, start_import_job
from src.server.runtime_settings import (
    SettingsError,
    apply_avatar,
    apply_llm_model,
    apply_stt_settings,
    apply_tts_settings,
    apply_vad_settings,
    current_snapshot,
    fetch_llm_catalog,
    vad_snapshot,
    speech_snapshot,
)
from src.server.state import state
from src.utils.logging import logger


def _json(payload: dict, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps(payload, ensure_ascii=False),
    )


def _active_session_count() -> int:
    return sum(1 for stream in state.avatar_streams.values() if stream is not None)


async def get_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    data = current_snapshot(state.config)
    data["session_count"] = _active_session_count()
    data["switching"] = bool(getattr(state, "switching", False))
    data["ready"] = bool(state.server_ready)
    data["model_ready"] = bool(getattr(state, "model_ready", False))
    return _json({"code": 0, "data": data})


async def list_llm_models(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    result = await fetch_llm_catalog(state.config)
    return _json({"code": 0, "data": result})


async def set_llm_model(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: apply_llm_model(
                state.config,
                params.get("model", ""),
                params.get("provider", ""),
                params.get("system_prompt"),
            ),
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換 LLM 模型失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def get_vad_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": vad_snapshot(state.config)})


async def set_vad_settings(request):
    """更新 Silero VAD 端點引數。"""
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        loop = asyncio.get_event_loop()
        # 切 silero 會載入模型，別卡住事件迴圈
        result = await loop.run_in_executor(
            None, lambda: apply_vad_settings(state.config, params)
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換 VAD 設定失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def get_speech_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": speech_snapshot(state.config)})


async def set_stt_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: apply_stt_settings(
                state.config, params, session_count=_active_session_count()
            ),
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換 STT 失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def set_tts_settings(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: apply_tts_settings(
                state.config, params, session_count=_active_session_count()
            ),
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換 TTS 失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def set_avatar(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        result = apply_avatar(
            state.config,
            params.get("type", ""),
            params.get("avatar_id", ""),
            session_count=_active_session_count(),
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換數字人失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def avatar_preview(request):
    avatar_id = request.match_info.get("avatar_id", "")
    preview = resolve_preview_path(avatar_id)
    if preview is None or not preview.is_file():
        return _json({"code": -1, "msg": "預覽圖不存在"}, status=404)
    return web.FileResponse(preview)


async def import_avatar(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        reader = await request.multipart()
        engine = ""
        avatar_id = ""
        overwrite = False
        video_path = None
        original_name = "upload.mp4"

        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "type":
                engine = (await part.text()).strip()
            elif part.name == "avatar_id":
                avatar_id = (await part.text()).strip()
            elif part.name == "overwrite":
                overwrite = (await part.text()).strip().lower() in {"1", "true", "yes"}
            elif part.name == "video":
                original_name = part.filename or original_name
                suffix = Path(original_name).suffix.lower() or ".mp4"
                if suffix not in VIDEO_EXTS:
                    return _json({"code": -1, "msg": "請上傳 mp4 / mov / webm / avi 影片"}, status=400)
                dest_dir = uploads_dir() / uuid4_name()
                dest_dir.mkdir(parents=True, exist_ok=True)
                video_path = dest_dir / f"source{suffix}"
                with video_path.open("wb") as handle:
                    while True:
                        chunk = await part.read_chunk()
                        if not chunk:
                            break
                        handle.write(chunk)

        if video_path is None or not video_path.is_file() or video_path.stat().st_size == 0:
            return _json({"code": -1, "msg": "請選擇要匯入的影片"}, status=400)

        job = start_import_job(
            engine=engine,
            video_path=video_path,
            original_name=original_name,
            avatar_id=avatar_id,
            overwrite=overwrite,
            session_count=_active_session_count(),
        )
        return _json({"code": 0, "msg": "ok", "data": job.to_dict()})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("匯入數字人失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def import_avatar_status(request):
    job_id = request.match_info.get("job_id", "")
    job = get_job(job_id)
    if job is None:
        return _json({"code": -1, "msg": "找不到製作任務"}, status=404)
    return _json({"code": 0, "data": job.to_dict()})


def uuid4_name() -> str:
    import uuid

    return uuid.uuid4().hex[:12]
