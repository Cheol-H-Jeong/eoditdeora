"""Remote endpoint presets.

For users running Eoditdeora on a laptop without a local inference
server, we offer a short list of provider templates. Picking a preset
fills in the URL and API style; the user still supplies their own API
key (we never ship keys).

Presets are an explicit opt-in path out of the localhost-only default.
The UI surfaces a "remote" warning whenever a role's base_url is not
a loopback address.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Preset:
    key: str
    display: str
    base_url: str
    api_kind: str
    requires_api_key: bool
    # Models to expose in the UI when the provider's /v1/models endpoint
    # is empty or unavailable (Anthropic has no catalog endpoint).
    default_models: tuple[str, ...]
    notes: str

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "display": self.display,
            "base_url": self.base_url,
            "api_kind": self.api_kind,
            "requires_api_key": self.requires_api_key,
            "default_models": list(self.default_models),
            "notes": self.notes,
            "remote": is_remote_url(self.base_url),
        }


PRESETS: tuple[Preset, ...] = (
    Preset(
        key="openai",
        display="OpenAI",
        base_url="https://api.openai.com/v1",
        api_kind="openai",
        requires_api_key=True,
        default_models=("gpt-4o-mini", "gpt-4o", "text-embedding-3-small"),
        notes="문서 내용이 OpenAI로 전송됩니다. 공무원·감사 환경은 비추천.",
    ),
    Preset(
        key="anthropic",
        display="Anthropic (Claude)",
        base_url="https://api.anthropic.com/v1",
        api_kind="openai",
        requires_api_key=True,
        default_models=(
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
        ),
        notes="OpenAI 호환 모드 필요. 임베딩 미제공.",
    ),
    Preset(
        key="groq",
        display="Groq (고속 추론)",
        base_url="https://api.groq.com/openai/v1",
        api_kind="openai",
        requires_api_key=True,
        default_models=("llama-3.3-70b-versatile", "mixtral-8x7b-32768"),
        notes="무료 쿼터 있음. 속도가 장점.",
    ),
    Preset(
        key="together",
        display="Together AI",
        base_url="https://api.together.xyz/v1",
        api_kind="openai",
        requires_api_key=True,
        default_models=(),
        notes="오픈소스 모델 호스팅. /v1/models 카탈로그 존재.",
    ),
    Preset(
        key="openrouter",
        display="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_kind="openai",
        requires_api_key=True,
        default_models=(),
        notes="여러 제공자 통합. 라우팅 규칙은 OpenRouter가 관리.",
    ),
    Preset(
        key="remote_llama_cpp",
        display="원격 llama.cpp 서버",
        base_url="http://your-server.local:8080",
        api_kind="openai",
        requires_api_key=False,
        default_models=(),
        notes="본인이 운영하는 원격 llama-server. Tailscale/VPN 권장.",
    ),
    Preset(
        key="remote_vllm",
        display="원격 vLLM 서버",
        base_url="http://your-server.local:8000/v1",
        api_kind="openai",
        requires_api_key=False,
        default_models=(),
        notes="본인이 운영하는 원격 vLLM. 인증을 켰다면 API key 입력.",
    ),
    Preset(
        key="remote_ollama",
        display="원격 Ollama",
        base_url="http://your-server.local:11434/v1",
        api_kind="openai",
        requires_api_key=False,
        default_models=(),
        notes="Ollama OpenAI 호환 경로. `/v1` 사용.",
    ),
    Preset(
        key="custom",
        display="사용자 정의",
        base_url="",
        api_kind="openai",
        requires_api_key=False,
        default_models=(),
        notes="직접 입력. 경로에 /v1 미포함이면 앱이 자동 추가.",
    ),
)


_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})


def is_remote_url(url: str) -> bool:
    """True if the URL points somewhere other than the local loopback.

    We treat `.local` mDNS and `*.tailscale` hostnames as *remote* for
    privacy-surface purposes — the point of the flag is to warn the user
    that document bytes will leave their machine.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return True
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    return host not in _LOCAL_HOSTS


def list_presets() -> list[dict[str, object]]:
    return [p.to_dict() for p in PRESETS]
