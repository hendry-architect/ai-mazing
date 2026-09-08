"""Image and video generation provider implementations.

The two interfaces the architecture calls for — ``ImageGenerationProvider``
and ``VideoGenerationProvider`` — with one implementation per vendor:

    images: OpenAI Images (default) · Google Imagen (photorealism) ·
            Ideogram (typography) · Flux/BFL (self-host/open ecosystem)
    video:  Google Veo (premium cinematic) · Runway (production) ·
            Pika (fast social clips) · Luma Dream Machine (stylized motion)

Selection is never by vendor name in business logic — the capability
registry (pcip/generate/capabilities.py) ranks whichever of these are
configured against a MediaSpec. Every provider:

- reports ``available()`` from its own credentials, so unconfigured vendors
  simply drop out of routing;
- attaches ``LicensePolicy.ai_license(provider)`` to every generated asset
  so the publish router can clear it;
- returns assets with either a download URL or a local file path.

Endpoint paths/versions follow each vendor's current public docs (linked in
pcip/SETUP.md); vendors do rev these — if a call 404s, check the doc link
and bump the path here, nothing else in the platform changes.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from pcip.generate.providers import (
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderNotConfigured,
    register_provider,
)
from pcip.licensing import LicensePolicy
from pcip.models import Asset, new_id


class ImageGenerationProvider(GenerationProvider):
    """Interface for image generation vendors (IImageGenerationProvider)."""

    capabilities = ["image"]
    terms_url = ""

    def _asset(self, name: str, *, url: str = "", local_path: str = "",
               metadata: Optional[Dict[str, Any]] = None) -> Asset:
        return Asset(
            name=name, kind="image", url=url, local_path=local_path,
            license=LicensePolicy.ai_license(self.name, self.terms_url),
            metadata=metadata or {},
        )

    def _save_b64(self, b64_data: str, suffix: str = "png") -> str:
        self.cfg.ensure_dirs()
        path = Path(self.cfg.exports_dir) / f"{new_id('gen')}.{suffix}"
        path.write_bytes(base64.b64decode(b64_data))
        return str(path)


class VideoGenerationProvider(GenerationProvider):
    """Interface for video generation vendors (IVideoGenerationProvider)."""

    capabilities = ["video"]
    terms_url = ""

    def _asset(self, name: str, *, url: str = "", local_path: str = "",
               metadata: Optional[Dict[str, Any]] = None) -> Asset:
        return Asset(
            name=name, kind="video", url=url, local_path=local_path,
            license=LicensePolicy.ai_license(self.name, self.terms_url),
            metadata=metadata or {},
        )


def _check(resp: requests.Response, what: str) -> Dict[str, Any]:
    if resp.status_code >= 400:
        raise RuntimeError(f"{what} → {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _poll(fn, *, what: str, interval: float = 4.0, timeout: float = 600.0):
    """Poll ``fn()`` until it returns non-None; raise on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result is not None:
            return result
        time.sleep(interval)
    raise RuntimeError(f"{what}: generation timed out after {timeout:.0f}s")


def _size_str(request: GenerationRequest, default: str = "1024x1024") -> str:
    w = request.params.get("width", 0)
    h = request.params.get("height", 0)
    return f"{w}x{h}" if w and h else default


# ─── Image providers ─────────────────────────────────────────────────────────


@register_provider
class OpenAIImageProvider(ImageGenerationProvider):
    """OpenAI Images (GPT Image) — the default image provider."""

    name = "openai-images"
    terms_url = "https://openai.com/policies/terms-of-use/"

    def available(self) -> bool:
        return bool(self.cfg.openai_api_key)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        data = _check(
            requests.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {self.cfg.openai_api_key}"},
                json={
                    "model": self.cfg.openai_image_model,
                    "prompt": request.prompt,
                    "size": request.params.get("size", "auto"),
                    "n": 1,
                },
                timeout=self.cfg.request_timeout * 3,
            ),
            "openai images",
        )
        item = data["data"][0]
        if item.get("b64_json"):
            asset = self._asset(request.prompt[:60],
                                local_path=self._save_b64(item["b64_json"]))
        else:
            asset = self._asset(request.prompt[:60], url=item.get("url", ""))
        return GenerationResult(provider=self.name, capability="image",
                                assets=[asset],
                                metadata={"model": self.cfg.openai_image_model})


@register_provider
class GoogleImagenProvider(ImageGenerationProvider):
    """Google Imagen via the Gemini API — photorealistic work."""

    name = "imagen"
    terms_url = "https://ai.google.dev/gemini-api/terms"
    MODEL = "imagen-3.0-generate-002"

    def available(self) -> bool:
        return bool(self.cfg.google_ai_api_key)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        data = _check(
            requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.MODEL}:predict",
                headers={"x-goog-api-key": self.cfg.google_ai_api_key},
                json={
                    "instances": [{"prompt": request.prompt}],
                    "parameters": {
                        "sampleCount": 1,
                        "aspectRatio": request.params.get("aspect_ratio", "1:1"),
                    },
                },
                timeout=self.cfg.request_timeout * 3,
            ),
            "imagen",
        )
        b64 = data["predictions"][0]["bytesBase64Encoded"]
        asset = self._asset(request.prompt[:60], local_path=self._save_b64(b64))
        return GenerationResult(provider=self.name, capability="image",
                                assets=[asset], metadata={"model": self.MODEL})


@register_provider
class IdeogramProvider(ImageGenerationProvider):
    """Ideogram — best-in-class typography inside images."""

    name = "ideogram"
    terms_url = "https://about.ideogram.ai/legal/api-tos"

    def available(self) -> bool:
        return bool(self.cfg.ideogram_api_key)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        data = _check(
            requests.post(
                "https://api.ideogram.ai/v1/ideogram-v3/generate",
                headers={"Api-Key": self.cfg.ideogram_api_key},
                json={
                    "prompt": request.prompt,
                    "aspect_ratio": request.params.get("aspect_ratio", "1x1"),
                    "rendering_speed": request.params.get("rendering_speed", "DEFAULT"),
                },
                timeout=self.cfg.request_timeout * 3,
            ),
            "ideogram",
        )
        url = data["data"][0]["url"]
        return GenerationResult(provider=self.name, capability="image",
                                assets=[self._asset(request.prompt[:60], url=url)])


@register_provider
class FluxProvider(ImageGenerationProvider):
    """Flux (Black Forest Labs) — open ecosystem / self-hostable.
    FLUX_ENDPOINT may point at api.bfl.ml or your own deployment."""

    name = "flux"
    terms_url = "https://blackforestlabs.ai/terms-of-service/"

    def available(self) -> bool:
        return bool(self.cfg.bfl_api_key)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        headers = {"x-key": self.cfg.bfl_api_key}
        job = _check(
            requests.post(
                f"{self.cfg.flux_endpoint}/v1/flux-pro-1.1",
                headers=headers,
                json={
                    "prompt": request.prompt,
                    "width": request.params.get("width", 1024),
                    "height": request.params.get("height", 1024),
                },
                timeout=self.cfg.request_timeout,
            ),
            "flux submit",
        )
        poll_url = job.get("polling_url") or f"{self.cfg.flux_endpoint}/v1/get_result?id={job['id']}"

        def check():
            r = _check(requests.get(poll_url, headers=headers,
                                    timeout=self.cfg.request_timeout), "flux poll")
            if r.get("status") == "Ready":
                return r["result"]["sample"]
            if r.get("status") in ("Error", "Failed"):
                raise RuntimeError(f"flux generation failed: {r}")
            return None

        url = _poll(check, what="flux")
        return GenerationResult(provider=self.name, capability="image",
                                assets=[self._asset(request.prompt[:60], url=url)])


# ─── Video providers ─────────────────────────────────────────────────────────


@register_provider
class VeoProvider(VideoGenerationProvider):
    """Google Veo via the Gemini API — premium cinematic video."""

    name = "veo"
    terms_url = "https://ai.google.dev/gemini-api/terms"
    MODEL = "veo-3.0-generate-001"
    API = "https://generativelanguage.googleapis.com/v1beta"

    def available(self) -> bool:
        return bool(self.cfg.google_ai_api_key)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        headers = {"x-goog-api-key": self.cfg.google_ai_api_key}
        op = _check(
            requests.post(
                f"{self.API}/models/{self.MODEL}:predictLongRunning",
                headers=headers,
                json={"instances": [{"prompt": request.prompt}]},
                timeout=self.cfg.request_timeout,
            ),
            "veo submit",
        )

        def check():
            r = _check(requests.get(f"{self.API}/{op['name']}", headers=headers,
                                    timeout=self.cfg.request_timeout), "veo poll")
            if not r.get("done"):
                return None
            if "error" in r:
                raise RuntimeError(f"veo generation failed: {r['error']}")
            videos = (r.get("response", {})
                       .get("generateVideoResponse", {})
                       .get("generatedSamples", []))
            return videos[0]["video"]["uri"] if videos else ""

        url = _poll(check, what="veo", timeout=900)
        return GenerationResult(provider=self.name, capability="video",
                                assets=[self._asset(request.prompt[:60], url=url)],
                                metadata={"model": self.MODEL})


@register_provider
class RunwayProvider(VideoGenerationProvider):
    """Runway — mature production API. Runway's video generation is
    image-to-video: pass params.image_url (e.g. a Canva-exported frame)."""

    name = "runway"
    terms_url = "https://runwayml.com/terms-of-use"
    API = "https://api.dev.runwayml.com/v1"
    VERSION = "2024-11-06"

    def available(self) -> bool:
        return bool(self.cfg.runway_api_key)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        image_url = request.params.get("image_url", "")
        if not image_url:
            raise ProviderNotConfigured(
                "Runway is image-to-video: supply params.image_url (a Canva "
                "export or generated image works well as the seed frame)."
            )
        headers = {
            "Authorization": f"Bearer {self.cfg.runway_api_key}",
            "X-Runway-Version": self.VERSION,
        }
        task = _check(
            requests.post(
                f"{self.API}/image_to_video",
                headers=headers,
                json={
                    "model": request.params.get("model", "gen4_turbo"),
                    "promptImage": image_url,
                    "promptText": request.prompt,
                    "ratio": request.params.get("ratio", "1280:720"),
                    "duration": int(request.params.get("duration_s", 5)),
                },
                timeout=self.cfg.request_timeout,
            ),
            "runway submit",
        )

        def check():
            r = _check(requests.get(f"{self.API}/tasks/{task['id']}",
                                    headers=headers,
                                    timeout=self.cfg.request_timeout), "runway poll")
            if r.get("status") == "SUCCEEDED":
                return (r.get("output") or [""])[0]
            if r.get("status") == "FAILED":
                raise RuntimeError(f"runway generation failed: {r.get('failure')}")
            return None

        url = _poll(check, what="runway")
        return GenerationResult(provider=self.name, capability="video",
                                assets=[self._asset(request.prompt[:60], url=url)])


@register_provider
class PikaProvider(VideoGenerationProvider):
    """Pika — fast short-form social clips. Pika's API is offered through
    hosting partners; set PIKA_ENDPOINT to your partner endpoint (and
    PIKA_API_KEY) — the request/response shape below matches the common
    partner convention (POST prompt → job → poll for video url)."""

    name = "pika"
    terms_url = "https://pika.art/terms-of-service"

    def available(self) -> bool:
        return bool(self.cfg.pika_api_key and self.cfg.pika_endpoint)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        headers = {"Authorization": f"Key {self.cfg.pika_api_key}"}
        job = _check(
            requests.post(
                self.cfg.pika_endpoint, headers=headers,
                json={"prompt": request.prompt,
                      "aspect_ratio": request.params.get("aspect_ratio", "9:16"),
                      "duration": request.params.get("duration_s", 5)},
                timeout=self.cfg.request_timeout,
            ),
            "pika submit",
        )
        if job.get("video", {}).get("url"):        # synchronous partner response
            url = job["video"]["url"]
        else:
            status_url = job.get("status_url") or f"{self.cfg.pika_endpoint}/{job.get('id', '')}"

            def check():
                r = _check(requests.get(status_url, headers=headers,
                                        timeout=self.cfg.request_timeout), "pika poll")
                if r.get("status") in ("completed", "COMPLETED"):
                    return r.get("video", {}).get("url", "")
                if r.get("status") in ("failed", "FAILED"):
                    raise RuntimeError(f"pika generation failed: {r}")
                return None

            url = _poll(check, what="pika")
        return GenerationResult(provider=self.name, capability="video",
                                assets=[self._asset(request.prompt[:60], url=url)])


@register_provider
class LumaProvider(VideoGenerationProvider):
    """Luma Dream Machine — stylized and cinematic motion."""

    name = "luma"
    terms_url = "https://lumalabs.ai/legal/tos"
    API = "https://api.lumalabs.ai/dream-machine/v1"

    def available(self) -> bool:
        return bool(self.cfg.luma_api_key)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        headers = {"Authorization": f"Bearer {self.cfg.luma_api_key}"}
        gen = _check(
            requests.post(
                f"{self.API}/generations",
                headers=headers,
                json={"prompt": request.prompt,
                      "model": request.params.get("model", "ray-2"),
                      "resolution": request.params.get("resolution", "720p"),
                      "duration": f"{int(request.params.get('duration_s', 5))}s"},
                timeout=self.cfg.request_timeout,
            ),
            "luma submit",
        )

        def check():
            r = _check(requests.get(f"{self.API}/generations/{gen['id']}",
                                    headers=headers,
                                    timeout=self.cfg.request_timeout), "luma poll")
            if r.get("state") == "completed":
                return r.get("assets", {}).get("video", "")
            if r.get("state") == "failed":
                raise RuntimeError(f"luma generation failed: {r.get('failure_reason')}")
            return None

        url = _poll(check, what="luma")
        return GenerationResult(provider=self.name, capability="video",
                                assets=[self._asset(request.prompt[:60], url=url)])


@register_provider
class CanvaImageProvider(GenerationProvider):
    """Imagery sourced through Canva instead of a separate paid image API.

    The account already pays for Canva, whose stock library and Magic Media
    cover what an article hero needs, and whose licence permits that imagery to
    leave only through a design export — which is the path PCIP already
    enforces. Buying a second image API to produce what the existing
    subscription produces is a cost with no capability behind it.

    Canva's generation is not reachable from the Connect API, so this provider
    pauses the run and asks the agent session holding the Canva connector to do
    it, exactly as assembly does. That makes it unsuitable for unattended runs
    — an external API provider ranks ahead of it whenever one is configured —
    but it means an operator-driven run needs no extra vendor at all.
    """

    name = "canva-images"
    capabilities = ["image"]

    def available(self) -> bool:
        # Only when an agent session can actually service the handoff.
        return self.cfg.canva_mode == "mcp"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        from pcip.pipelines.base import HandoffRequired

        raise HandoffRequired("imagery", {
            "prompt": request.prompt,
            "brand": request.brand,
            "language": request.language,
            "width": request.params.get("width", 0),
            "height": request.params.get("height", 0),
            "how": (
                "Source the image in Canva rather than an external generator "
                "(MCP: generate-design for Magic Media, or place a stock image "
                "in the design), export it, and attach the file:\n"
                "  pcip attach <run_id> --export-file <path>\n\n"
                "Premium Canva content leaves only through the official export "
                "workflow — that is what makes this licence-clean."
            ),
        })
