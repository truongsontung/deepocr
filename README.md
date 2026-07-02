# DeepOCR

OpenAI-compatible API gateway for DeepSeek web chat with OCR/file upload support.

## Features

- **OpenAI-compatible API** – `/v1/chat/completions` (streaming + non-streaming), `/v1/models`, `/health`
- **File upload** – images (JPG, PNG, GIF, WebP), documents (PDF, DOCX, XLSX, TXT, CSV) and more
- **Vision support** – upload images for OCR and visual understanding
- **Multi-account** – round-robin load balancing across multiple DeepSeek accounts
- **Auto file processing** – waits for files to be fully processed (PENDING → PARSING → SUCCESS)
- **Auto OCR instruction** – injects OCR prompt when files are attached
- **PoW solving** – built-in Proof-of-Work solver (browser-based Web Workers for speed)
- **Token management** – automatic login, refresh every 10 minutes

## Requirements

- Python 3.10+
- Chrome/Chromium (installed automatically by cloakbrowser)

## Quick Start

```bash
git clone git@github.com:truongsontung/deepocr.git
cd deepocr
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env
# Edit .env with your DeepSeek accounts
python3 deepocr.py
```

## Configuration

Edit `.env` file:

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | `sk-deepocr-key` | API key for authenticating requests |
| `PORT` | `8080` | Server port |
| `DEEPSEEK_ACCOUNTS` | – | Comma-separated `email:password` pairs |

### Example `.env`

```env
API_KEY=sk-deepocr-key
PORT=8080
DEEPSEEK_ACCOUNTS=user1@gmail.com:pass1,user2@gmail.com:pass2
```

## API Usage

### Chat Completion (with image)

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer sk-deepocr-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-chat",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "Describe this image"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
      ]
    }]
  }'
```

### Chat Completion (with file upload)

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer sk-deepocr-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "Analyze this file"}],
    "files": [{"name": "document.pdf", "data": "<base64>"}]
  }'
```

### Streaming

Add `"stream": true` to the request body.

### List Models

```bash
curl http://localhost:8080/v1/models \
  -H "Authorization: Bearer sk-deepocr-key"
```

### Health Check

```bash
curl http://localhost:8080/health
```

## Supported Models

| Model | Description |
|---|---|
| `deepseek-chat` / `deepseek-v4-flash` | Fast chat (default) |
| `deepseek-v4-pro` | Pro model |
| `deepseek-reasoner` / `deepseek-r1` | Reasoning model |

**Model aliases**: `gpt-4o` → `deepseek-v4-flash`, `gpt-4` → `deepseek-v4-flash`, `o1` → `deepseek-reasoner`, etc.

## Usage Policy

This project is intended **for research and educational purposes only**.

By using this software, you agree to:
- Use it solely for personal study, research, and learning about AI/API integration
- **Not** use it for commercial purposes, production services, or any revenue-generating activities
- **Not** abuse or spam the underlying services
- Comply with all applicable terms of service of DeepSeek and any other integrated platforms
- Respect rate limits and fair usage of the underlying platforms

The authors are not responsible for any misuse of this software. Use at your own risk.

## Project Structure

```
deepocr/
├── deepocr.py          # Main gateway server
├── deepseek_client.py  # DeepSeek API client + browser worker
├── token_manager.py    # Multi-account token rotation
├── config.py           # Configuration loader
├── pow_solver.py       # PoW solver (Python fallback)
├── .env                # Environment variables (secrets)
├── .env.sample         # Example env file
├── .gitignore          # Git ignore rules
├── requirements.txt    # Python dependencies
└── README.md           # This file
```
