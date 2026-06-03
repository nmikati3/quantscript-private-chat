from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import asyncio
import json
import logging
from app.engine.deep_research.deep_research import deep_research_workflow
from app.core.sanitization import sanitize_messages
from app.api.models import DeepResearchRequest
from app.api.routes import limiter
from app.engine.llm.inference import initialize_llama

logger = logging.getLogger(__name__)

router = APIRouter(tags=["deep_research"])

@router.post("/deep_research_response")
@limiter.limit("5/minute")
async def deep_research_response(request: Request, body: DeepResearchRequest):

    messages = sanitize_messages(body.messages)

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()
        done = asyncio.Event()
        result_container = {}
        loop = asyncio.get_running_loop()

        def progress_callback(msg: str):
            if msg:
                asyncio.run_coroutine_threadsafe(
                    queue.put({"type": "progress", "content": str(msg)}),
                    loop,
                )

        def run_workflow_sync():
            try:
                initialize_llama(deep_research=True)
                progress_callback("🚀 Starting deep research workflow...")
                result = asyncio.run(
                    deep_research_workflow(
                        messages,
                        progress_callback=progress_callback,
                    )
                )
                result_container["result"] = result
            except Exception as e:
                logger.error(f"Error in deep_research_response workflow: {e}", exc_info=True)
                result_container["result"] = {"error": "An unexpected error occurred"}
                progress_callback(f"❌ Error: An unexpected error occurred")
            finally:
                initialize_llama(deep_research=False)
                loop.call_soon_threadsafe(done.set)

        # Run research in background thread
        asyncio.create_task(asyncio.to_thread(run_workflow_sync))

        # Stream progress
        while not done.is_set() or not queue.empty():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.1)
                yield f"data: {json.dumps(item)}\n\n"
            except asyncio.TimeoutError:
                pass

        result = result_container.get("result", {})

        # Final payload
        if result.get("final_report"):
            yield f"data: {json.dumps({'type': 'final_report', 'final_report': result['final_report']})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'message', 'error': result.get('error')})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )