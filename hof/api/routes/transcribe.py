"""Streaming speech-to-text via OpenAI Realtime API (WebRTC).

The browser POSTs an SDP offer; this forwards it to OpenAI and returns the SDP
answer. Audio and transcription events flow over WebRTC after handshake.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from openai import AsyncOpenAI

from hof.agent.stream import _resolve_openai_api_key
from hof.api.auth import verify_auth

logger = logging.getLogger(__name__)

router = APIRouter()

SESSION_CONFIG = {
    "type": "realtime",
    "model": "gpt-4o-mini-realtime-preview",
    "output_modalities": ["text"],
    "instructions": (
        "You are a transcription assistant. "
        "Transcribe exactly what the user says verbatim. "
        "Do not translate, summarize, or rephrase. "
        "Keep the original language of the speaker."
    ),
}


@router.post(
    "/session",
    response_class=Response,
    responses={200: {"content": {"application/sdp": {}}}},
)
async def create_webrtc_session(
    request: Request,
    _user: str = Depends(verify_auth),
):
    """Exchange WebRTC SDP with OpenAI Realtime API."""
    api_key = _resolve_openai_api_key()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI API key is not configured.",
        )

    sdp_offer = (await request.body()).decode()
    if not sdp_offer.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SDP offer body is required.",
        )

    logger.info("[transcribe] Forwarding SDP offer to OpenAI Realtime API")

    try:
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.realtime.calls.create(
            sdp=sdp_offer,
            session=SESSION_CONFIG,  # type: ignore[arg-type]
        )
        sdp_answer = resp.text
    except Exception as exc:
        logger.error("[transcribe] OpenAI SDK error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI Realtime API error: {str(exc)[:300]}",
        ) from exc

    logger.info("[transcribe] Got SDP answer from OpenAI, returning to browser")
    return Response(
        content=sdp_answer,
        media_type="application/sdp",
    )
