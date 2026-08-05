"""PCIP — PassQual Creative Intelligence Platform.

The creative operating system for the Pascual enterprise. PCIP treats Canva as
one component of an enterprise workflow rather than the workflow itself:

- **Connect**   — authenticated Canva Connect API client (designs, folders,
                  Brand Kits, brand templates, licensed assets, exports).
- **Respect**   — a licensing policy engine that only moves premium content
                  through Canva-supported workflows (export / autofill), never
                  by extraction or bypass.
- **Know**      — a searchable knowledge graph of every visual asset created
                  or licensed, with full-text search and typed relationships.
- **Generate**  — orchestrated AI copy, image, and video generation alongside
                  Canva-native generation.
- **Assemble**  — declarative pipelines that produce presentations, podcast
                  kits, blog graphics, social campaigns, patient education
                  materials, and marketing assets — each with review gates.
- **Publish**   — gated publishing to passqual.com (WordPress) and social
                  channels, with every publication recorded in the graph.

Usage (CLI)::

    python -m pcip init
    python -m pcip sync
    python -m pcip search "diabetes education carousel"
    python -m pcip run social_campaign --brief brief.json
    python -m pcip approve <run_id> --gate brand_review
    python -m pcip publish <run_id> --channel wordpress
"""

from __future__ import annotations

__version__ = "0.1.0"

from pcip.config import PCIPConfig, load_config
from pcip.licensing import LicensePolicy, LicensingError
from pcip.models import (
    Asset,
    Brief,
    Channel,
    EdgeKind,
    License,
    LicenseType,
    NodeKind,
    Publication,
)

__all__ = [
    "__version__",
    "PCIPConfig",
    "load_config",
    "LicensePolicy",
    "LicensingError",
    "Asset",
    "Brief",
    "Channel",
    "EdgeKind",
    "License",
    "LicenseType",
    "NodeKind",
    "Publication",
]
