import os

from config_loader import ConfigValidationError, load_config, validate_config


def test_default_environment_is_development() -> None:
    config = load_config()
    assert config["environment"] == "development"


def test_placeholder_secret_rejected_in_production() -> None:
    config = load_config()
    config["environment"] = "production"
    config["security"]["secret_key"] = "CHANGE_ME"
    config["security"]["signing_key"] = "supersecureproductionkey1234567890"
    config["network"]["seed_peers"] = ["https://seed.example"]
    config["network"]["tls_cert_file"] = "/tmp/cert.pem"
    config["network"]["tls_key_file"] = "/tmp/key.pem"
    config["network"]["tls_ca_file"] = "/tmp/ca.pem"
    try:
        validate_config(config)
    except ConfigValidationError:
        return
    raise AssertionError("Expected ConfigValidationError for placeholder secret in production")


def test_app_env_overrides_file() -> None:
    original = os.environ.get("APP_ENV")
    os.environ["APP_ENV"] = "production"
    try:
        config = load_config()
        assert config["environment"] == "production"
    finally:
        if original is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = original
