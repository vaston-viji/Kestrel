"""AnthropicSynthesizer — calls the Claude API with retries and defensive parsing."""
from __future__ import annotations
import json
import logging
import re
import ssl
from pathlib import Path

from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt,
    wait_exponential, before_sleep_log,
)

from kestrel.models import Classification, ItemNarrative, RawItem, ScoredItem, Taxonomy

log = logging.getLogger(__name__)


def _build_ssl_context(project_root: Path) -> ssl.SSLContext | None:
    """Return an SSLContext that trusts a corporate CA bundle, or None to use certifi default."""
    ca_bundle = project_root / "config" / "quantrim_ca_bundle.pem"
    if not ca_bundle.exists():
        return None
    ctx = ssl.create_default_context(cafile=str(ca_bundle))
    # Netskope CA does not mark BasicConstraints as critical — relax strict X.509 checking.
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    log.debug("Using corporate CA bundle for Anthropic API SSL: %s", ca_bundle)
    return ctx


def _load_prompt(name: str, project_root: Path) -> str:
    p = project_root / "config" / "prompts" / f"{name}.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _load_style(project_root: Path) -> str:
    p = project_root / "config" / "writing_style.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _item_context(item: ScoredItem | RawItem) -> str:
    title = getattr(item, "title", "")
    url = getattr(item, "canonical_url", getattr(item, "url", ""))
    snippet = getattr(item, "snippet", "")
    source = getattr(item, "source_name", "")
    return f"Headline: {title}\nSource: {source}\nURL: {url}\nSnippet: {snippet}"


def _extract_json(text: str) -> dict:
    """Find first JSON object in model output."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"No JSON in response: {text[:200]}")


class AnthropicSynthesizer:
    def __init__(self, model: str, max_retries: int, project_root: Path) -> None:
        import anthropic
        import httpx

        ssl_ctx = _build_ssl_context(project_root)
        http_client = httpx.Client(verify=ssl_ctx) if ssl_ctx is not None else None

        # max_retries=0 disables the SDK's own retry layer — tenacity handles all retries below
        self._client = anthropic.Anthropic(
            max_retries=0,
            **({"http_client": http_client} if http_client is not None else {}),
        )
        self._model = model
        self._max_retries = max_retries
        self._root = project_root
        self._style = _load_style(project_root)
        # Set True on first APIConnectionError so all remaining calls skip the API immediately.
        # Prevents 39-min classify drain when a corporate proxy blocks api.anthropic.com.
        self._proxy_blocked = False

    def _call(self, prompt: str, max_tokens: int = 1024) -> str:
        import anthropic as _anthropic

        if self._proxy_blocked:
            raise RuntimeError("Anthropic API unreachable — skipping (proxy-blocked fast-fail)")

        # Only retry on transient server-side errors. Connection errors are NOT retried here
        # because corporate proxy blocks are persistent — retrying wastes time with no benefit.
        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            retry=retry_if_exception_type((
                _anthropic.RateLimitError,
                _anthropic.APITimeoutError,
                _anthropic.InternalServerError,
            )),
            before_sleep=before_sleep_log(log, logging.DEBUG),
            reraise=True,
        )
        def _inner():
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
                timeout=30.0,
            )
            return resp.content[0].text

        try:
            return _inner()
        except _anthropic.APIConnectionError:
            self._proxy_blocked = True
            log.warning(
                "Anthropic API unreachable (corporate proxy?) — "
                "fast-failing all remaining synthesis calls"
            )
            raise

    def classify(self, item: RawItem, taxonomy: Taxonomy) -> Classification:
        template = _load_prompt("classify", self._root)
        prompt = template.replace("{{KESTREL_TAGS}}", str(taxonomy.kestrel_tags)) \
                         .replace("{{DOMAIN_TAGS}}", str(taxonomy.domain_tags)) \
                         .replace("{{ITEM}}", _item_context(item))
        try:
            raw = self._call(prompt, max_tokens=256)
            data = _extract_json(raw)
            return Classification(
                kestrel_tags=[t for t in data.get("kestrel_tags", []) if t in taxonomy.kestrel_tags],
                domain_tags=[t for t in data.get("domain_tags", []) if t in taxonomy.domain_tags],
                impact_score=float(data.get("impact_score", 2)),
                kestrel_sentiment=float(data.get("kestrel_sentiment", 0)),
                primary_section=data.get("primary_section", "policy"),
            )
        except Exception as exc:
            log.warning("classify fallback for '%s': %s", item.title[:60], exc)
            from kestrel.synthesis.fallback import FallbackSynthesizer
            return FallbackSynthesizer().classify(item, taxonomy)

    def top_line(self, items: list[ScoredItem], style: str, max_words: int) -> list[str]:
        template = _load_prompt("top_line", self._root)
        items_text = "\n---\n".join(_item_context(i) for i in items[:10])
        prompt = template.replace("{{WRITING_STYLE}}", style) \
                         .replace("{{ITEMS}}", items_text)
        try:
            raw = self._call(prompt, max_tokens=400)
            bullets = [ln.strip() for ln in raw.strip().splitlines()
                       if ln.strip().startswith("-")]
            return bullets[:5] if bullets else [f"- {raw.strip()[:200]}"]
        except Exception as exc:
            log.warning("top_line API error: %s", exc)
            from kestrel.synthesis.fallback import FallbackSynthesizer
            return FallbackSynthesizer().top_line(items, style, max_words)

    def enrich_item(self, item: ScoredItem, style: str) -> ItemNarrative:
        template = _load_prompt("priority_item", self._root)
        prompt = template.replace("{{WRITING_STYLE}}", style) \
                         .replace("{{ITEM}}", _item_context(item))
        try:
            raw = self._call(prompt, max_tokens=512)
            data = _extract_json(raw)
            return ItemNarrative(
                what_happened=str(data.get("what_happened", item.snippet or item.title)),
                why_it_matters=str(data.get("why_it_matters", "")),
                kestrel_angle=str(data.get("kestrel_angle", "")),
            )
        except Exception as exc:
            log.warning("enrich_item fallback for '%s': %s", item.title[:60], exc)
            from kestrel.synthesis.fallback import FallbackSynthesizer
            return FallbackSynthesizer().enrich_item(item, style)

    def watchpoints(self, items: list[ScoredItem], style: str) -> list[str]:
        template = _load_prompt("watchpoints", self._root)
        items_text = "\n---\n".join(_item_context(i) for i in items[:15])
        prompt = template.replace("{{WRITING_STYLE}}", style) \
                         .replace("{{ITEMS}}", items_text)
        try:
            raw = self._call(prompt, max_tokens=400)
            bullets = [ln.strip() for ln in raw.strip().splitlines()
                       if ln.strip().startswith("-")]
            return bullets[:5] if bullets else [f"- {raw.strip()[:200]}"]
        except Exception as exc:
            log.warning("watchpoints API error: %s", exc)
            from kestrel.synthesis.fallback import FallbackSynthesizer
            return FallbackSynthesizer().watchpoints(items, style)


def make_synthesizer(provider: str, model: str, max_retries: int, project_root: Path):
    """Factory — returns the correct Synthesizer implementation."""
    if provider == "anthropic":
        import os
        if not os.environ.get("ANTHROPIC_API_KEY"):
            log.warning("provider=anthropic but ANTHROPIC_API_KEY not set; using fallback")
            from kestrel.synthesis.fallback import FallbackSynthesizer
            return FallbackSynthesizer()
        return AnthropicSynthesizer(model=model, max_retries=max_retries, project_root=project_root)
    from kestrel.synthesis.fallback import FallbackSynthesizer
    return FallbackSynthesizer()
