"""Hybrid publishing decision engine tests.

Immediate posts prefer direct platform APIs; scheduled campaigns prefer the
scheduler (Buffer); each falls back to the other when its preferred mode
isn't configured.
"""

from pcip.config import PCIPConfig
from pcip.connectors.social import (
    BufferAdapter,
    MetaAdapter,
    ThreadsAdapter,
    XAdapter,
    adapter_for,
    adapters_for,
)
from pcip.graph.store import KnowledgeGraph
from pcip.models import Channel
from pcip.publish.router import PublishRouter


def cfg_with(**kwargs) -> PCIPConfig:
    return PCIPConfig(**kwargs)


def test_immediate_prefers_direct_api():
    cfg = cfg_with(buffer_token="b", meta_page_token="m")
    order = adapters_for(Channel.FACEBOOK, cfg, prefer="direct")
    assert isinstance(order[0], MetaAdapter)
    assert isinstance(order[-1], BufferAdapter)


def test_scheduled_prefers_buffer():
    cfg = cfg_with(buffer_token="b", meta_page_token="m")
    order = adapters_for(Channel.FACEBOOK, cfg, prefer="scheduler")
    assert isinstance(order[0], BufferAdapter)


def test_fallback_when_preferred_mode_unconfigured():
    # Urgent post, no native Meta token → Buffer still carries it.
    cfg = cfg_with(buffer_token="b")
    assert isinstance(adapter_for(Channel.FACEBOOK, cfg, prefer="direct"), BufferAdapter)
    # Scheduled post, no Buffer → direct API still carries it.
    cfg = cfg_with(meta_page_token="m")
    assert isinstance(adapter_for(Channel.FACEBOOK, cfg, prefer="scheduler"), MetaAdapter)


def test_new_direct_channels_available_when_configured():
    cfg = cfg_with(x_user_token="x", threads_token="t", threads_user_id="1")
    assert isinstance(adapter_for(Channel.X, cfg), XAdapter)
    assert isinstance(adapter_for(Channel.THREADS, cfg), ThreadsAdapter)


def test_threads_needs_both_token_and_user_id():
    cfg = cfg_with(threads_token="t")
    assert not ThreadsAdapter(cfg).available()


def test_route_plan_reports_decision():
    cfg = cfg_with(buffer_token="b", meta_page_token="m")
    router = PublishRouter(cfg, KnowledgeGraph(":memory:"))
    immediate = router.route_plan("facebook", scheduled=False)
    scheduled = router.route_plan("facebook", scheduled=True)
    assert immediate["order"][0].startswith("MetaAdapter")
    assert scheduled["order"][0].startswith("BufferAdapter")
    assert immediate["preferred_mode"] == "direct"
    assert scheduled["preferred_mode"] == "scheduler"
