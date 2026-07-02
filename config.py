import sys, os

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("=", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip()
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    os.environ[key] = val

load_env()

API_KEY = os.environ.get("API_KEY", "sk-deepocr-key")
PORT = int(os.environ.get("PORT", 8080))

ACCOUNTS = []
accounts_env = os.environ.get("DEEPSEEK_ACCOUNTS", "")
if accounts_env:
    for acc_str in accounts_env.split(","):
        acc_str = acc_str.strip()
        if ":" in acc_str:
            parts = acc_str.split(":", 1)
            ACCOUNTS.append({"email": parts[0].strip(), "password": parts[1].strip(), "token": None})

if not ACCOUNTS:
    email = os.environ.get("DEEPSEEK_EMAIL", "").strip()
    password = os.environ.get("DEEPSEEK_PASSWORD", "").strip()
    if not email or not password:
        raise ValueError("Cấu hình DEEPSEEK_ACCOUNTS hoặc DEEPSEEK_EMAIL/PASSWORD trong .env!")
    ACCOUNTS.append({"email": email, "password": password, "token": None})

AVAILABLE_MODELS = [
    "deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat",
    "deepseek-reasoner", "deepseek-r1", "deepseek-v3",
    "deepseek-vision", "deepseek-vision-reasoner",
]

MODEL_ALIASES = {
    "gpt-4o": "deepseek-v4-flash", "gpt-4": "deepseek-v4-flash",
    "gpt-4o-mini": "deepseek-v4-flash", "gpt-3.5-turbo": "deepseek-v4-flash",
    "o3": "deepseek-v4-pro", "o1": "deepseek-reasoner",
    "gpt-4.1": "deepseek-v4-pro", "gpt-4.1-mini": "deepseek-v4-flash",
    "gpt-4.1-nano": "deepseek-v4-flash",
}

def resolve_model(model: str) -> str:
    return MODEL_ALIASES.get(model.strip().lower(), model.strip())
