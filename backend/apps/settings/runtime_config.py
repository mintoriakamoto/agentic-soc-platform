import logging
from functools import lru_cache

from django.core.cache import cache

logger = logging.getLogger(__name__)

# Shared counter every process watches. A settings change bumps it; other processes notice the
# change on their next refresh_if_stale() and drop their own caches.
GENERATION_KEY = "runtime-config:generation:v1"
_local_generation = None


@lru_cache(maxsize=1)
def get_llm_configs():
    from .models import LLMProviderConfig

    return [
        {
            "name": provider.name,
            "api_key": provider.api_key,
            "base_url": provider.base_url.rstrip("/"),
            "model": provider.model,
            "proxy": provider.proxy,
            "tags": provider.tags or [],
        }
        for provider in LLMProviderConfig.objects.filter(enabled=True).order_by("priority", "name", "created_at")
    ]


@lru_cache(maxsize=1)
def get_otx_config():
    from .models import ThreatIntelAlienVaultOTXConfig

    config = ThreatIntelAlienVaultOTXConfig.get_current()
    return {
        "enabled": config.enabled,
        "api_key": config.api_key,
        "base_url": config.base_url.rstrip("/"),
        "proxy": config.proxy,
    }


@lru_cache(maxsize=1)
def get_opencti_config():
    from .models import ThreatIntelOpenCTIConfig

    config = ThreatIntelOpenCTIConfig.get_current()
    return {
        "enabled": config.enabled,
        "url": config.url.rstrip("/"),
        "token": config.token,
        "ssl_verify": config.ssl_verify,
        "proxy": config.proxy,
    }


@lru_cache(maxsize=1)
def get_splunk_config():
    from .models import SiemSplunkConfig

    config = SiemSplunkConfig.get_current()
    return {
        "host": config.host,
        "port": config.port,
        "username": config.username,
        "password": config.password,
        "scheme": config.scheme,
        "verify": config.verify,
    }


@lru_cache(maxsize=1)
def get_elk_config():
    from .models import SiemElkConfig

    config = SiemElkConfig.get_current()
    return {
        "host": config.host.rstrip("/"),
        "api_key": config.api_key,
        "verify_certs": config.verify_certs,
        "process_alert_from_index_enabled": config.process_alert_from_index_enabled,
        "action_index": config.action_index,
        "action_poll_interval_seconds": config.action_poll_interval_seconds,
        "action_size": config.action_size,
    }


@lru_cache(maxsize=1)
def get_ldap_config():
    from .models import LdapConfig

    config = LdapConfig.get_current()
    return {
        "enabled": config.enabled,
        "server_uri": config.server_uri,
        "domain": config.domain,
        "bind_dn": config.bind_dn,
        "bind_password": config.bind_password,
        "user_search_base_dn": config.user_search_base_dn,
        "user_login_attr": config.user_login_attr,
    }


@lru_cache(maxsize=1)
def get_runtime_config():
    from .models import RuntimeConfig

    config = RuntimeConfig.get_current()
    return {
        "prompt_language": config.prompt_language,
        "stream_maxlen": config.stream_maxlen,
        "dashboard_refresh_interval_seconds": config.dashboard_refresh_interval_seconds,
    }


def get_prompt_language():
    return get_runtime_config()["prompt_language"]


def get_stream_maxlen():
    try:
        return get_runtime_config()["stream_maxlen"]
    except Exception as exc:
        if exc.__class__.__name__ == "DatabaseOperationForbidden":
            return 10000
        raise


def get_dashboard_refresh_interval_seconds():
    return get_runtime_config()["dashboard_refresh_interval_seconds"]


def _clear_local(group=None):
    if group in {None, "llm"}:
        get_llm_configs.cache_clear()
    if group in {None, "threat_intel", "otx"}:
        get_otx_config.cache_clear()
    if group in {None, "threat_intel", "opencti"}:
        get_opencti_config.cache_clear()
    if group in {None, "siem", "splunk"}:
        get_splunk_config.cache_clear()
    if group in {None, "siem", "elk"}:
        get_elk_config.cache_clear()
    if group in {None, "siem", "splunk", "elk"}:
        # Connected clients hold the old host and credentials, so they have to go too.
        from integrations.siem.clients import reset_clients

        reset_clients()
    if group in {None, "ldap"}:
        get_ldap_config.cache_clear()
    if group in {None, "runtime"}:
        get_runtime_config.cache_clear()


def invalidate(group=None):
    """Drop this process's cached config and tell every other process to do the same.

    The caches above are per-process. Under gunicorn only the worker that served the settings
    change would otherwise notice it, leaving sibling workers serving stale credentials until
    they recycle. Bumping a shared generation counter closes that gap.
    """
    _clear_local(group)
    _bump_generation()


def _bump_generation():
    global _local_generation
    try:
        _local_generation = cache.incr(GENERATION_KEY)
    except ValueError:
        # Key absent (first write, or evicted): seed it and adopt the seeded value.
        cache.set(GENERATION_KEY, 1, timeout=None)
        _local_generation = 1
    except Exception:
        logger.warning("Could not publish a runtime config invalidation; other processes may lag.")


def refresh_if_stale():
    """Adopt configuration changes made by another process.

    Cheap enough to call on every request and every worker iteration: one Redis read, and a local
    cache clear only when the generation actually moved.
    """
    global _local_generation
    try:
        current = cache.get(GENERATION_KEY)
    except Exception:
        logger.warning("Could not read the runtime config generation; serving locally cached values.")
        return False

    if current is None or current == _local_generation:
        return False

    _local_generation = current
    _clear_local()
    return True
