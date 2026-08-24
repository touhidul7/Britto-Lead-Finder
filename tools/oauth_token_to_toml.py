import json
from pathlib import Path


def toml_value(value):
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    return json.dumps(value)


token_path = Path("credentials/oauth_token.json")
if not token_path.exists():
    raise SystemExit("Missing credentials/oauth_token.json. Run local OAuth authorization first.")

data = json.loads(token_path.read_text(encoding="utf-8"))
print("[GOOGLE_OAUTH_TOKEN_INFO]")
for key, value in data.items():
    print(f"{key} = {toml_value(value)}")
