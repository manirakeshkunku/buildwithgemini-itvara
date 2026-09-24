"""Minimal FastAPI proxy for a deployed A2A agent (Agent Runtime, agents-cli 1.1.0+).

The browser talks ONLY to this proxy (same origin, no CORS, no GCP creds in the
browser). The proxy authenticates with Application Default Credentials and
forwards chat to the deployed agent over the A2A protocol, returning replies as
structured parts the chat UI knows how to show:

  * {"kind": "text", "text": ...}  -> a normal chat bubble
  * {"kind": "a2ui", "data": ...}  -> one A2UI message (beginRendering /
    surfaceUpdate); static/index.html renders these as a card.

Why A2A: agents-cli 1.1.0 (GA) deploys ADK agents to Agent Runtime as A2A agents
and no longer registers the reasoning-engine operation schema the old
`agent_engines.get(...).stream_query()` path relied on (operation_schemas() comes
back empty). The container serves the A2A protocol over the Agent Engine HTTP
passthrough, so this proxy fetches the agent's card and sends messages with the
a2a-sdk client (the same path `agents-cli run --mode a2a` uses). This works for
both A2A and plain ADK 1.1.0 deployments (the container serves A2A either way).

Run:
  pip install -r requirements.txt
  export AGENT_ENGINE_RESOURCE_NAME="projects/.../locations/.../reasoningEngines/..."
  export AGENT_DIRECTORY="app"   # your agent's app directory (agents-cli-manifest.yaml)
  python main.py                 # -> http://localhost:8080
"""

import os
import uuid

import google.auth
import google.auth.transport.requests
import httpx
from a2a.client import ClientConfig, ClientFactory
import a2a.types as a2a_types

AgentCard = getattr(a2a_types, "AgentCard", None)
Message = getattr(a2a_types, "Message", None)
Part = getattr(a2a_types, "Part", None)
Role = getattr(a2a_types, "Role", None)
TaskArtifactUpdateEvent = getattr(a2a_types, "TaskArtifactUpdateEvent", None)
TransportProtocol = getattr(a2a_types, "TransportProtocol", None)
TextPart = getattr(a2a_types, "TextPart", None)
FilePart = getattr(a2a_types, "FilePart", None)
DataPart = getattr(a2a_types, "DataPart", None)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

RESOURCE = os.environ["AGENT_ENGINE_RESOURCE_NAME"]
# The agent's app directory (matches agent_directory in agents-cli-manifest.yaml).
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")
# Location is embedded in the resource name: projects/<p>/locations/<loc>/reasoningEngines/<id>.
LOCATION = RESOURCE.split("/locations/")[1].split("/")[0]

# A2A endpoint for an Agent Runtime deployment, via the Agent Engine HTTP
# passthrough. The card lives at the well-known path under this base.
A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)
A2A_CARD_URL = f"{A2A_BASE}/.well-known/agent-card.json"

# The agent tags its A2UI data parts with this mime type.
_A2UI_MIME = "application/json+a2ui"

# One set of ADC credentials, refreshed per request (access tokens expire ~1h).
_creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)


def _auth_headers() -> dict[str, str]:
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


app = FastAPI()


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    # Always return JSON so the browser never receives a plain-text 500 page
    # (which shows up in the chat as "Unexpected token 'I', "Internal S"... is
    # not valid JSON"). Any server-side failure now surfaces as a readable
    # message in the chat bubble instead.
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )


# Reuse ONE A2A context per user so the agent remembers the conversation.
_contexts: dict[str, str] = {}
# Cache the agent card after the first fetch.
_card: AgentCard | None = None


async def _get_card(client: httpx.AsyncClient) -> AgentCard:
    global _card
    if _card is None:
        resp = await client.get(A2A_CARD_URL)
        resp.raise_for_status()
        card = AgentCard(**resp.json())
        # Agent Runtime does not serve a public card URL, so point the client at
        # the passthrough base for message sends.
        card.url = A2A_BASE
        _card = card
    return _card


import base64
import json
import re


def _decode_bytes_str(raw: str | bytes) -> str:
    if isinstance(raw, bytes):
        raw_str = raw.decode("utf-8", errors="ignore")
    else:
        raw_str = str(raw)

    if raw_str.startswith("<a2a_datapart_json>") or "<a2a_datapart_json>" in raw_str:
        return raw_str
    try:
        decoded = base64.b64decode(raw_str).decode("utf-8", errors="ignore")
        return decoded
    except Exception:
        return raw_str


def _parse_a2a_datapart_json(raw_str: str) -> list[dict]:
    out: list[dict] = []
    matches = re.findall(r"<a2a_datapart_json>(.*?)(?:</a2a_datapart_json>|<a2a_datapart_json>)", raw_str, re.DOTALL)
    for m in matches:
        content = m.strip()
        parsed = None
        for candidate in [content, content.replace('\\"', '"').replace('\\\\', '\\')]:
            try:
                parsed = json.loads(candidate)
                break
            except Exception:
                pass
        if not parsed or not isinstance(parsed, dict):
            continue
        meta = parsed.get("metadata") or {}
        mime = meta.get("mimeType") if isinstance(meta, dict) else None
        if (mime == _A2UI_MIME or "data" in parsed) and "data" in parsed:
            out.append({"kind": "a2ui", "data": parsed["data"]})
        elif "text" in parsed:
            out.append({"kind": "text", "text": parsed["text"]})
    return out


def _extract_parts(parts: list) -> list[dict]:
    out: list[dict] = []
    for p in parts:
        root = getattr(p, "root", p)
        if TextPart and isinstance(root, TextPart) and getattr(root, "text", None):
            txt = root.text
            parsed = _parse_a2a_datapart_json(txt)
            if parsed:
                out.extend(parsed)
            else:
                out.append({"kind": "text", "text": txt})
        elif FilePart and isinstance(root, FilePart):
            file_obj = getattr(root, "file", None)
            raw_bytes = getattr(file_obj, "bytes", None) if file_obj else None
            if raw_bytes:
                decoded = _decode_bytes_str(raw_bytes)
                parsed = _parse_a2a_datapart_json(decoded)
                if parsed:
                    out.extend(parsed)
                elif decoded:
                    out.append({"kind": "text", "text": decoded})
            elif getattr(file_obj, "uri", None):
                out.append({"kind": "text", "text": file_obj.uri})
        elif getattr(root, "data", None) is not None:
            meta = getattr(root, "metadata", None) or {}
            mime = meta.get("mimeType") if isinstance(meta, dict) else (getattr(meta, "mime_type", None) or getattr(meta, "mimeType", None))
            if mime == _A2UI_MIME:
                out.append({"kind": "a2ui", "data": root.data})
            elif isinstance(root.data, (dict, list)):
                out.append({"kind": "a2ui", "data": root.data})
        elif ((TextPart and isinstance(root, TextPart)) or hasattr(root, "text")) and getattr(root, "text", None):
            txt = getattr(root, "text")
            parsed = _parse_a2a_datapart_json(txt)
            if parsed:
                out.extend(parsed)
            else:
                out.append({"kind": "text", "text": txt})
    return out


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "")
    user_id = body.get("user_id") or "web-user"
    parts: list[dict] = []

    async with httpx.AsyncClient(headers=_auth_headers(), timeout=120) as client:
        card = await _get_card(client)
        jsonrpc_tp = getattr(TransportProtocol, "jsonrpc", "jsonrpc") if TransportProtocol else "jsonrpc"
        http_json_tp = getattr(TransportProtocol, "http_json", "http_json") if TransportProtocol else "http_json"
        user_role = getattr(Role, "user", "user") if Role else "user"

        factory = ClientFactory(
            ClientConfig(
                supported_transports=[
                    jsonrpc_tp,
                    http_json_tp,
                ],
                httpx_client=client,
            )
        )
        a2a_client = factory.create(card)

        part_root = TextPart(text=message) if TextPart else {"text": message}
        part_obj = Part(root=part_root) if Part else part_root
        msg = Message(
            message_id=str(uuid.uuid4()),
            role=user_role,
            parts=[part_obj],
            context_id=_contexts.get(user_id),
        )



        last_task = None
        got_artifact_update = False
        async for event in a2a_client.send_message(msg):
            if not isinstance(event, tuple):
                continue
            task, update = event
            if task is not None:
                last_task = task
                if getattr(task, "context_id", None):
                    _contexts[user_id] = task.context_id
            if isinstance(update, TaskArtifactUpdateEvent):
                got_artifact_update = True
                parts.extend(_extract_parts(update.artifact.parts))
            elif hasattr(update, "artifact") and getattr(update, "artifact", None):
                got_artifact_update = True
                parts.extend(_extract_parts(update.artifact.parts))
            elif hasattr(update, "parts") and getattr(update, "parts", None):
                got_artifact_update = True
                parts.extend(_extract_parts(update.parts))
            elif isinstance(update, Message):
                got_artifact_update = True
                parts.extend(_extract_parts(update.parts))
            elif hasattr(update, "status") and getattr(update, "status", None):
                # Status update event
                st = update.status
                if hasattr(st, "message") and st.message:
                    got_artifact_update = True
                    parts.extend(_extract_parts(st.message.parts))

        # Non-streaming fallback: pull parts from the final task's artifacts or status.
        if not got_artifact_update and last_task is not None:
            for artifact in getattr(last_task, "artifacts", None) or []:
                parts.extend(_extract_parts(artifact.parts))

    # Deduplicate parts so identical messages or cards are never emitted twice
    deduped_parts = []
    seen_keys = set()
    for p in parts:
        if p.get("kind") == "text":
            key = ("text", p.get("text", "").strip())
        elif p.get("kind") == "a2ui":
            key = ("a2ui", json.dumps(p.get("data", {}), sort_keys=True))
        else:
            key = None

        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        deduped_parts.append(p)

    parts = deduped_parts if deduped_parts else parts

    if not parts:
        # The turn produced no text or UI (e.g. the agent only ran tools, or a
        # tool stalled). Be honest rather than silent.
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]
    return JSONResponse({"parts": parts})


static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
