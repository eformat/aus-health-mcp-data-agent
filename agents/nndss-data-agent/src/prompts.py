"""Prompt definitions with MLflow Prompt Registry integration.

Prompts are defined as hardcoded defaults loaded from prompts/system.md.
When MLflow is available (MLFLOW_TRACKING_URI set), they are registered
in the MLflow Prompt Registry (versioned, editable via UI) and loaded
from there at runtime with 60s cache. If MLflow is unavailable the
hardcoded defaults are used as-is.

Pattern adapted from bank-voice-agent/ai-voice-agent/backend/src/prompts.py.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Load hardcoded default from prompts/system.md
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _read_prompt_file(name: str) -> str:
    """Read a prompt file, stripping YAML frontmatter."""
    fpath = _PROMPTS_DIR / f"{name}.md"
    if not fpath.exists():
        return ""
    text = fpath.read_text()
    # Strip YAML frontmatter (between --- markers)
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:].strip()
    return text


_SYSTEM_PROMPT_DEFAULT = _read_prompt_file("system")

# ---------------------------------------------------------------------------
# MLflow Prompt Registry integration
# ---------------------------------------------------------------------------

# Prompt name → (mlflow_name, hardcoded_default, has_template_variable)
# Template variables use {var} in code, {{var}} in MLflow template syntax
_PROMPT_REGISTRY = {
    "system": ("nndss-agent.system", _SYSTEM_PROMPT_DEFAULT, True),
}

_mlflow_prompts_enabled = False


def _register_prompts():
    """Register hardcoded prompts in MLflow if not already present."""
    global _mlflow_prompts_enabled
    mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    if not mlflow_uri:
        return

    try:
        import mlflow

        for key, (name, template, has_vars) in _PROMPT_REGISTRY.items():
            # Convert {DOMAIN} → {{DOMAIN}} for MLflow template syntax
            mlflow_template = template
            if has_vars:
                mlflow_template = template.replace(
                    "{DOMAIN}", "{{DOMAIN}}"
                )
            try:
                existing = mlflow.genai.load_prompt(
                    name, version=1, allow_missing=True
                )
                if existing is None:
                    mlflow.genai.register_prompt(
                        name=name,
                        template=mlflow_template,
                        commit_message="Initial registration from prompts.py",
                        tags={"agent": key, "source": "prompts.py"},
                    )
                    mlflow.genai.set_prompt_alias(
                        name, alias="production", version=1
                    )
                    print(
                        f"[prompts] Registered '{name}' v1 in MLflow",
                        flush=True,
                    )
                else:
                    print(
                        f"[prompts] '{name}' already exists in MLflow "
                        f"(v{existing.version})",
                        flush=True,
                    )
            except Exception as exc:
                print(
                    f"[prompts] Failed to register '{name}': {exc}",
                    flush=True,
                )

        _mlflow_prompts_enabled = True
        print("[prompts] MLflow prompt registry enabled", flush=True)
    except Exception as exc:
        print(
            f"[prompts] MLflow prompt registry unavailable: {exc}",
            flush=True,
        )


def _load_prompt(key: str) -> str:
    """Load a prompt from MLflow (production alias), falling back to hardcoded."""
    name, default, has_vars = _PROMPT_REGISTRY[key]
    if not _mlflow_prompts_enabled:
        return default

    try:
        import mlflow

        prompt = mlflow.genai.load_prompt(
            f"prompts:/{name}@production",
            allow_missing=True,
            cache_ttl_seconds=60,
        )
        if prompt is None:
            return default
        template = prompt.template
        # Convert {{DOMAIN}} back to {DOMAIN} for .format() compatibility
        if has_vars:
            template = template.replace("{{DOMAIN}}", "{DOMAIN}")
        return template
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Public API — lazy loading from MLflow on each access
# ---------------------------------------------------------------------------


class _PromptAccessor:
    """Lazy prompt loader that reads from MLflow on each access."""

    @property
    def SYSTEM_PROMPT(self) -> str:
        return _load_prompt("system")


_accessor = _PromptAccessor()


def __getattr__(name: str):
    """Module-level __getattr__ for lazy prompt loading.

    Allows `from src.prompts import SYSTEM_PROMPT` to work while
    routing reads through the MLflow-backed _PromptAccessor.
    """
    if hasattr(_accessor, name):
        return getattr(_accessor, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
