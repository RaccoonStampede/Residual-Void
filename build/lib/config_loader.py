"""
config_loader.py — Residual-Void configuration loader and validator.

Usage:
    cp config/residualvoid.example.yaml config/residualvoid.yaml
    python src/config_loader.py --validate config/residualvoid.yaml

Environment variables:
    APP_ENV                          development | staging | production (default: development)
    RESIDUALVOID_NODE_ID             Overrides node_id
    RESIDUALVOID_SECRET_KEY          Overrides security.secret_key
    RESIDUALVOID_SIGNING_KEY         Overrides security.signing_key
    RESIDUALVOID_PREVIOUS_SIGNING_KEY Overrides security.previous_signing_key
    RESIDUALVOID_DB_URL              Overrides persistence.db_url
    RESIDUALVOID_NONCE_REDIS_URL     Overrides security.nonce_cache_redis_url

Non-breaking design:
    - All config keys have safe defaults that preserve development behaviour.
    - Production validation is only enforced when APP_ENV=production.
    - Existing callers that do not set APP_ENV continue to work without changes.
"""

import argparse
import hashlib
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# PyYAML is the only non-stdlib dependency.  A stub is provided for
# environments where it is not installed so that the module remains importable.
try:
    import yaml  # type: ignore
    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore
    _YAML_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Known placeholder values that must never appear as real secrets in production.
KNOWN_PLACEHOLDERS: frozenset = frozenset(
    {
        "CHANGE_ME",
        "changeme",
        "change_me",
        "placeholder",
        "secret",
        "todo",
        "xxx",
        "your-secret",
        "default",
        "password",
        "letmein",
    }
)

MINIMUM_SECRET_LENGTH = 32  # characters

VALID_ENVIRONMENTS = frozenset({"development", "staging", "production"})


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def _default_config() -> Dict[str, Any]:
    """Return the full default configuration tree."""
    return {
        "environment": "development",
        "node_id": "",
        "log_level": "info",
        "security": {
            "secret_key": "",
            "signing_key": "",
            "previous_signing_key": "",
            "key_rotation_grace_seconds": 300,
            "token_ttl_seconds": 30,
            "max_clock_skew_seconds": 10,
            "nonce_cache_backend": "memory",
            "nonce_cache_redis_url": "",
        },
        "network": {
            "listen_address": "0.0.0.0",
            "listen_port": 7700,
            "seed_peers": [],
            "tls_cert_file": "",
            "tls_key_file": "",
            "tls_ca_file": "",
            "blocked_peers": [],
            "connection_timeout_seconds": 5,
        },
        "coherence": {
            "quorum_size": 2,
            "epoch_timeout_seconds": 60,
            "heartbeat_interval_seconds": 5,
        },
        "persistence": {
            "db_url": "sqlite:///./data/residualvoid.db",
            "snapshot_dir": "./data/snapshots/",
            "snapshot_interval_seconds": 300,
            "snapshot_retain_count": 10,
            "snapshot_restore_path": "",
            "wal_checkpoint_interval": 1000,
        },
        "fieldmind": {
            "model_artifact_dir": "./data/models/",
            "inference_timeout_seconds": 10,
            "policy_update_interval_seconds": 30,
        },
    }


# ---------------------------------------------------------------------------
# Deep merge utility
# ---------------------------------------------------------------------------

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

def _load_yaml(path: str) -> Dict[str, Any]:
    """Load a YAML file and return its content as a dict."""
    if not _YAML_AVAILABLE:
        raise RuntimeError(
            "PyYAML is required to load YAML configuration files. "
            "Install it with: pip install pyyaml"
        )
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file {path!r} must be a YAML mapping, got {type(data).__name__}")
    return data


# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------

def _apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment variable overrides to *config* in-place and return it."""
    env_map = {
        "APP_ENV": ("environment",),
        "RESIDUALVOID_NODE_ID": ("node_id",),
        "RESIDUALVOID_SECRET_KEY": ("security", "secret_key"),
        "RESIDUALVOID_SIGNING_KEY": ("security", "signing_key"),
        "RESIDUALVOID_PREVIOUS_SIGNING_KEY": ("security", "previous_signing_key"),
        "RESIDUALVOID_DB_URL": ("persistence", "db_url"),
        "RESIDUALVOID_NONCE_REDIS_URL": ("security", "nonce_cache_redis_url"),
    }
    for env_var, key_path in env_map.items():
        value = os.environ.get(env_var)
        if value is not None:
            node = config
            for part in key_path[:-1]:
                node = node.setdefault(part, {})
            node[key_path[-1]] = value
    return config


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _is_placeholder(value: str) -> bool:
    """Return True if *value* looks like a placeholder secret."""
    return value.strip().upper() in {p.upper() for p in KNOWN_PLACEHOLDERS} or not value.strip()


def derive_kid(signing_key: str) -> str:
    """Derive a key ID from the signing key using a SHA-256 prefix."""
    return hashlib.sha256(signing_key.encode()).hexdigest()[:16]


class ConfigValidationError(Exception):
    """Raised when the configuration fails validation."""


def _collect_validation_errors(config: Dict[str, Any], environment: str) -> List[str]:
    """
    Collect all validation errors for *config* given *environment*.

    Returns a (possibly empty) list of human-readable error strings.
    """
    errors: List[str] = []
    is_production = environment == "production"

    # --- environment value ---
    if environment not in VALID_ENVIRONMENTS:
        errors.append(
            f"Invalid environment {environment!r}. "
            f"Must be one of: {', '.join(sorted(VALID_ENVIRONMENTS))}"
        )

    security = config.get("security", {})

    # --- secret_key ---
    secret_key: str = security.get("secret_key", "")
    if is_production:
        if _is_placeholder(secret_key):
            errors.append(
                "security.secret_key is a placeholder or empty. "
                "Set a real secret via RESIDUALVOID_SECRET_KEY before running in production."
            )
        elif len(secret_key) < MINIMUM_SECRET_LENGTH:
            errors.append(
                f"security.secret_key is too short (minimum {MINIMUM_SECRET_LENGTH} characters required in production)."
            )

    # --- signing_key ---
    signing_key: str = security.get("signing_key", "")
    if is_production:
        if _is_placeholder(signing_key):
            errors.append(
                "security.signing_key is a placeholder or empty. "
                "Set a real secret via RESIDUALVOID_SIGNING_KEY before running in production."
            )
        elif len(signing_key) < MINIMUM_SECRET_LENGTH:
            errors.append(
                f"security.signing_key is too short (minimum {MINIMUM_SECRET_LENGTH} characters required in production)."
            )

    # --- nonce cache backend ---
    nonce_backend: str = security.get("nonce_cache_backend", "memory")
    if nonce_backend not in ("memory", "redis"):
        errors.append(
            f"security.nonce_cache_backend must be 'memory' or 'redis', got {nonce_backend!r}."
        )
    if nonce_backend == "redis" and not security.get("nonce_cache_redis_url", "").strip():
        errors.append(
            "security.nonce_cache_redis_url must be set when nonce_cache_backend=redis."
        )

    # --- replay protection parameters ---
    ttl = security.get("token_ttl_seconds", 30)
    skew = security.get("max_clock_skew_seconds", 10)
    if not isinstance(ttl, (int, float)) or ttl <= 0:
        errors.append("security.token_ttl_seconds must be a positive number.")
    if not isinstance(skew, (int, float)) or skew < 0:
        errors.append("security.max_clock_skew_seconds must be a non-negative number.")

    # --- key rotation ---
    grace = security.get("key_rotation_grace_seconds", 300)
    if not isinstance(grace, (int, float)) or grace < 0:
        errors.append("security.key_rotation_grace_seconds must be a non-negative number.")

    # --- persistence ---
    persistence = config.get("persistence", {})
    db_url: str = persistence.get("db_url", "")
    if is_production and not db_url.strip():
        errors.append(
            "persistence.db_url is empty. Set RESIDUALVOID_DB_URL before running in production."
        )

    # --- network (production warnings) ---
    network = config.get("network", {})
    if is_production and not network.get("seed_peers"):
        errors.append(
            "network.seed_peers is empty. At least one seed peer is required in production."
        )
    if is_production and (
        not network.get("tls_cert_file")
        or not network.get("tls_key_file")
        or not network.get("tls_ca_file")
    ):
        errors.append(
            "network.tls_cert_file, tls_key_file, and tls_ca_file must all be set in production "
            "(mTLS required)."
        )

    return errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load, merge, and return the final configuration dict.

    Resolution order (later overrides earlier):
      1. Built-in defaults
      2. YAML file at *path* (if provided)
      3. Environment variable overrides

    This function does NOT raise on validation errors in non-production
    environments.  Call :func:`validate_config` explicitly if you need strict
    checks.

    Parameters
    ----------
    path:
        Path to a YAML configuration file.  May be None to use defaults only.

    Returns
    -------
    dict
        Fully merged configuration dictionary.
    """
    config = _default_config()

    if path:
        try:
            file_data = _load_yaml(path)
        except FileNotFoundError:
            logger.warning("Config file not found: %s — using defaults.", path)
            file_data = {}
        config = _deep_merge(config, file_data)

    config = _apply_env_overrides(config)

    # Normalize environment value from APP_ENV
    env = config.get("environment", "development")
    config["environment"] = env

    return config


def validate_config(config: Dict[str, Any]) -> None:
    """
    Validate *config* and raise :class:`ConfigValidationError` if any errors
    are found.

    In production (``config['environment'] == 'production'``), placeholder
    secrets and missing required values cause a hard failure.

    In non-production environments, only structural/type errors are raised;
    placeholder secrets produce warnings.

    Parameters
    ----------
    config:
        The merged config dict returned by :func:`load_config`.

    Raises
    ------
    ConfigValidationError
        If any validation errors are found (always in production; structural
        errors only in non-production).
    """
    environment: str = config.get("environment", "development")
    errors = _collect_validation_errors(config, environment)

    if errors:
        if environment == "production":
            message = (
                f"Configuration validation failed for environment={environment!r} "
                f"({len(errors)} error(s)):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )
            raise ConfigValidationError(message)
        else:
            # Non-production: log a count only; avoid logging any string derived
            # from config values to prevent accidental secret leakage in log files.
            logger.warning(
                "Config has %d validation warning(s) for environment=%r. "
                "Run with APP_ENV=production to enforce strict validation.",
                len(errors),
                environment,
            )


def get_replay_protection_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract and return replay-protection parameters from *config*.

    Returns
    -------
    dict with keys:
        token_ttl_seconds, max_clock_skew_seconds, nonce_cache_backend,
        nonce_cache_redis_url, nonce_cache_ttl_seconds
    """
    security = config.get("security", {})
    ttl = int(security.get("token_ttl_seconds", 30))
    skew = int(security.get("max_clock_skew_seconds", 10))
    return {
        "token_ttl_seconds": ttl,
        "max_clock_skew_seconds": skew,
        "nonce_cache_backend": security.get("nonce_cache_backend", "memory"),
        "nonce_cache_redis_url": security.get("nonce_cache_redis_url", ""),
        # Total window a nonce must be tracked
        "nonce_cache_ttl_seconds": ttl + 2 * skew,
    }


def get_key_rotation_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract and return key-rotation parameters from *config*.

    Returns
    -------
    dict with keys:
        active_key, previous_key, grace_seconds, active_kid, previous_kid
    """
    security = config.get("security", {})
    active_key: str = security.get("signing_key", "")
    previous_key: str = security.get("previous_signing_key", "")
    grace: int = int(security.get("key_rotation_grace_seconds", 300))
    return {
        "active_key": active_key,
        "previous_key": previous_key,
        "grace_seconds": grace,
        "active_kid": derive_kid(active_key) if active_key else "",
        "previous_kid": derive_kid(previous_key) if previous_key else "",
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _configure_logging(level: str = "info") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point.  Returns 0 on success, 1 on failure."""
    parser = argparse.ArgumentParser(
        description="Validate a Residual-Void configuration file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python src/config_loader.py --validate config/residualvoid.yaml\n"
            "  APP_ENV=production python src/config_loader.py --validate config/residualvoid.yaml\n"
        ),
    )
    parser.add_argument(
        "--validate",
        metavar="CONFIG_FILE",
        help="Path to the YAML config file to validate.",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Logging level (default: info).",
    )
    args = parser.parse_args(argv)

    _configure_logging(args.log_level)

    if not args.validate:
        parser.print_help()
        return 0

    try:
        config = load_config(args.validate)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.error("Failed to load config: %s", exc)
        return 1

    environment = config.get("environment", "development")
    logger.info("Loaded config for environment=%r", environment)

    try:
        validate_config(config)
    except ConfigValidationError as exc:
        logger.error("%s", exc)
        return 1

    logger.info("Configuration is valid.")

    # Display key rotation info (informational only)
    kr = get_key_rotation_config(config)
    if kr["active_kid"]:
        logger.info("Active key kid: %s", kr["active_kid"])
    if kr["previous_kid"]:
        logger.info("Previous key kid: %s (grace window: %ds)", kr["previous_kid"], kr["grace_seconds"])

    # Display replay protection params
    rp = get_replay_protection_config(config)
    logger.info(
        "Replay protection: TTL=%ds, skew=%ds, nonce_cache_ttl=%ds, backend=%s",
        rp["token_ttl_seconds"],
        rp["max_clock_skew_seconds"],
        rp["nonce_cache_ttl_seconds"],
        rp["nonce_cache_backend"],
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
