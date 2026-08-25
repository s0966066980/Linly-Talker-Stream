"""聊天相關路由"""
import json
from aiohttp import web
import asyncio

from src.llm.service import clear_session_history, llm_response
from src.utils.logging import logger
from src.server.state import state


async def human(request):
    """處理文本對話請求"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', 0)
        
        if params.get('interrupt'):
            state.avatar_streams[sessionid].flush_talk()

        if params['type'] == 'echo':
            state.avatar_streams[sessionid].put_msg_txt(params['text'])
            response_text = params['text']
        elif params['type'] == 'chat':
            # 放到執行緒池，避免阻塞事件迴圈
            llm_config = state.config.llm if state.config else None
            logger.info(f'[CHAT] LLM 配置: {llm_config}')
            response_text = await asyncio.get_event_loop().run_in_executor(
                None,
                llm_response,
                params['text'],
                state.avatar_streams[sessionid],
                llm_config.api_key if llm_config else None,
                llm_config.base_url if llm_config else "https://dashscope.aliyuncs.com/compatible-mode/v1",
                llm_config.model if llm_config else "qwen-plus"
            )

        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": 0, "msg": "ok", "response": response_text}
            ),
        )
    except Exception as e:
        logger.exception('exception:')
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": str(e)}
            ),
        )


async def interrupt_talk(request):
    """中斷當前對話"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', 0)
        state.avatar_streams[sessionid].flush_talk()
        
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": 0, "msg": "ok"}
            ),
        )
    except Exception as e:
        logger.exception('exception:')
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": str(e)}
            ),
        )


async def is_speaking(request):
    """查詢是否正在說話"""
    params = await request.json()
    sessionid = params.get('sessionid', 0)
    
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "data": state.avatar_streams[sessionid].is_speaking()}
        ),
    )


async def clear_history(request):
    """清空對話歷史"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', 0)
        
        clear_session_history(sessionid)
        
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": 0, "msg": "對話歷史已清空"}
            ),
        )
    except Exception as e:
        logger.exception('清空歷史失敗:')
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": str(e)}
            ),
        )
