#!/usr/bin/env python3
import sys, os, json, time, base64, uuid, logging, threading, re
from flask import Flask, request, jsonify, Response, stream_with_context
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deepseek_client as ds
from token_manager import get_active_token, invalidate_token, rotate_account, prelogin_all_accounts, get_account_password
from config import API_KEY, PORT, resolve_model

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger("deepocr")

_session = None
_session_lock = threading.Lock()

def get_session():
    global _session
    with _session_lock:
        if _session is None:
            logger.info("Initializing browser session...")
            _session = ds.get_default_session()
        return _session

MIME_EXT_MAP = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
    "image/webp": ".webp", "image/bmp": ".bmp", "image/svg+xml": ".svg",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/plain": ".txt", "text/csv": ".csv",
}

def ext_for_mime(mime: str) -> str:
    return MIME_EXT_MAP.get(mime.split(";")[0].strip(), ".bin")

def require_auth():
    key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if key != API_KEY:
        return jsonify({"error": {"message": "Invalid API key", "type": "authentication_error"}}), 401
    return None

def upload_file(tok, data_bytes, fname, session_id=None):
    session = get_session()
    b64 = base64.b64encode(data_bytes).decode()
    mime = ds.get_mime_type(fname)
    is_img = mime.startswith("image/")
    logger.info(f"Upload: {fname} ({len(data_bytes)} bytes, {mime}, session={session_id})")

    pow_data = session.post_json(
        ds.CREATE_POW_URL,
        extra_headers={"authorization": f"Bearer {tok}"},
        payload={"target_path": "/api/v0/file/upload_file"}
    )
    if pow_data.get("code") != 0:
        raise RuntimeError(f"PoW failed: {pow_data.get('msg')}")
    challenge = pow_data.get("data", {}).get("biz_data", {}).get("challenge", {})
    if not challenge:
        raise RuntimeError(f"PoW challenge empty: {pow_data}")
    pow_hdr = session.solve_pow_in_browser(challenge)

    headers = {"authorization": f"Bearer {tok}", "x-ds-pow-response": pow_hdr}
    resp = session.upload_file(ds.UPLOAD_URL, headers, b64, fname, session_id=session_id)
    if resp.get("code") != 0:
        raise RuntimeError(f"Upload API error: {resp.get('msg')} (code={resp.get('code')})")
    file_id = resp["data"]["biz_data"]["id"]
    logger.info(f"Upload OK: {file_id}")

    session.wait_for_file_ready(tok, file_id)
    logger.info(f"File ready: {file_id}")
    return file_id

def download_url(url: str) -> tuple:
    import requests as _req
    resp = _req.get(url, timeout=30)
    resp.raise_for_status()
    ct = resp.headers.get("content-type", "application/octet-stream")
    data = resp.content
    parsed = urlparse(url)
    fname = os.path.basename(parsed.path) or f"file{ext_for_mime(ct)}"
    return data, fname

def extract_files_from_messages(tok, msgs, session_id):
    refs = []
    for msg in msgs:
        content = msg.get("content", "")
        if isinstance(content, list):
            for item in content:
                item_type = item.get("type", "")
                if item_type == "image_url":
                    url = item.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        mime = url.split(";")[0].split(":")[1] if ";" in url else "image/png"
                        ext = ext_for_mime(mime)
                        _, b64data = url.split(",", 1)
                        data = base64.b64decode(b64data)
                        fname = f"img_{uuid.uuid4().hex[:8]}{ext}"
                        fid = upload_file(tok, data, fname, session_id=session_id)
                        refs.append(fid)
                        item["_uploaded"] = True
                    elif url.startswith("http"):
                        try:
                            data, fname = download_url(url)
                            fid = upload_file(tok, data, fname, session_id=session_id)
                            refs.append(fid)
                            item["_uploaded"] = True
                        except Exception as e:
                            logger.warning(f"Download failed: {url} - {e}")
                elif item_type == "file":
                    file_data = item.get("file", {})
                    fname = file_data.get("filename", f"file_{uuid.uuid4().hex[:8]}")
                    b64data = file_data.get("file_data", "")
                    if b64data:
                        data = base64.b64decode(b64data)
                        fid = upload_file(tok, data, fname, session_id=session_id)
                        refs.append(fid)
                        item["_uploaded"] = True
                elif item_type == "file_url":
                    url = item.get("file_url", {}).get("url", "")
                    fname = item.get("file_url", {}).get("name", f"file_{uuid.uuid4().hex[:8]}")
                    if url:
                        try:
                            data, _ = download_url(url)
                            fid = upload_file(tok, data, fname, session_id=session_id)
                            refs.append(fid)
                            item["_uploaded"] = True
                        except Exception as e:
                            logger.warning(f"Download failed: {url} - {e}")
    return refs

OCR_INSTRUCTION = (
    "Hãy OCR toàn bộ nội dung từ (các) file đính kèm. "
    "Trích xuất chính xác tất cả văn bản, số liệu, ký tự đặc biệt có trong ảnh/tài liệu. "
    "Nếu có bảng biểu hãy giữ nguyên cấu trúc bảng. "
    "Sau đó trả lời câu hỏi của người dùng dựa trên nội dung đã OCR."
)

def convert_messages_to_prompt(msgs, has_refs=False):
    parts = []
    ocr_injected = False
    for msg in msgs:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            texts = []
            for item in content:
                if item.get("_uploaded"):
                    continue
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif item.get("type") == "image_url":
                    texts.append("[Image attached]")
                elif item.get("type") == "file":
                    texts.append(f"[File: {item.get('file', {}).get('filename', 'unknown')}]")
            content = "\n".join(texts)
        if has_refs and role == "user" and not ocr_injected:
            content = f"{OCR_INSTRUCTION}\n\n{content}" if content.strip() else OCR_INSTRUCTION
            ocr_injected = True
        parts.append(f"{role}: {content}")
    return "\n\n".join(parts) + "\n\nAssistant:"

app = Flask(__name__)

@app.route("/v1/chat/completions", methods=["POST"])
def completions():
    err = require_auth()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    msgs = body.get("messages", [])
    if not msgs:
        return jsonify({"error": {"message": "messages required", "type": "invalid_request_error"}}), 400

    stream = body.get("stream", False)
    model = body.get("model", "deepseek-chat")
    resolved_model = resolve_model(model)
    thinking = body.get("thinking", body.get("thinking_enabled", False))
    search = body.get("search", body.get("search_enabled", False))

    rotate_account()
    tok, email = get_active_token()
    if not tok:
        return jsonify({"error": {"message": "No active token"}}), 500
    logger.info(f"Using: {email}, model={resolved_model}")

    session = get_session()
    sid = ds.create_session(tok, session=session)
    logger.info(f"Session: {sid}")

    refs = []
    refs.extend(extract_files_from_messages(tok, msgs, sid))
    if refs:
        logger.info(f"Uploaded {len(refs)} file(s): {refs}")

    for f in body.get("files", []):
        fname = f.get("name", f"file_{uuid.uuid4().hex[:8]}")
        b64data = f.get("data", "")
        if b64data:
            data = base64.b64decode(b64data)
            fid = upload_file(tok, data, fname, session_id=sid)
            refs.append(fid)

    prompt = convert_messages_to_prompt(msgs, has_refs=bool(refs))
    logger.debug(f"Prompt: {prompt[:100]}..., refs={refs}")

    def do_chat():
        pow_resp = ds.get_pow(tok, session=session)
        return ds.call_completion(
            token=tok, session_id=sid, prompt=prompt,
            model=resolved_model, thinking=thinking, search=search,
            pow_response=pow_resp, http_session=session,
            ref_file_ids=refs
        )

    def stream_response(lines):
        try:
            role_sent = False
            for parsed in ds.parse_sse_lines(lines):
                if parsed.get("response_message_id"):
                    continue
                p = parsed.get("p", "")
                v = parsed.get("v", "")
                if "thinking" in p.lower():
                    if not role_sent:
                        yield f'data: {json.dumps({"choices":[{"delta":{"role":"assistant"},"index":0}]})}\n\n'
                        role_sent = True
                    yield f'data: {json.dumps({"choices":[{"delta":{"content":"","thinking":v},"index":0}]})}\n\n'
                elif "content" in p or p == "":
                    if not role_sent:
                        yield f'data: {json.dumps({"choices":[{"delta":{"role":"assistant"},"index":0}]})}\n\n'
                        role_sent = True
                    yield f'data: {json.dumps({"choices":[{"delta":{"content":v},"index":0}]})}\n\n'
                elif "status" in p and v == "FINISHED":
                    break
            yield f'data: {json.dumps({"choices":[{"delta":{},"finish_reason":"stop","index":0}]})}\n\n'
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f'data: {json.dumps({"error":{"message":str(e),"type":"server_error"}})}\n\n'
            yield "data: [DONE]\n\n"

    def collect_text(lines):
        try:
            full_text = ""
            for parsed in ds.parse_sse_lines(lines):
                if parsed.get("response_message_id"):
                    continue
                p = parsed.get("p", "")
                v = parsed.get("v", "")
                if "thinking" in p.lower():
                    full_text += v
                elif "content" in p or p == "":
                    full_text += v
                elif "status" in p and v == "FINISHED":
                    break
            if not full_text:
                raise RuntimeError("DeepSeek returned empty response")
            return full_text
        except Exception as e:
            err_str = str(e)
            if "muted" in err_str.lower():
                invalidate_token(tok)
            raise

    try:
        lines = do_chat()
        if stream:
            return Response(stream_with_context(stream_response(lines)),
                            mimetype="text/event-stream",
                            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
        else:
            text = collect_text(lines)
            return jsonify({
                "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "account": email,
            })
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"error": {"message": str(e), "type": "server_error"}}), 500

@app.route("/v1/models", methods=["GET"])
def list_models():
    err = require_auth()
    if err:
        return err
    models = [{"id": m, "object": "model", "created": int(time.time()), "owned_by": "deepocr"} for m in ds.MODEL_MAP]
    return jsonify({"object": "list", "data": models})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "deepocr"})

if __name__ == "__main__":
    prelogin_all_accounts()
    logger.info(f"DeepOCR gateway on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
