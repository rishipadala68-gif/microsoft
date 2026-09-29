from app.core.redact import redact


def test_redact_aws_key():
    text = "Error accessing S3 with key AKIAIOSFODNN7EXAMPLE in us-east-1"
    assert redact(text) == "Error accessing S3 with key <redacted> in us-east-1"


def test_redact_slack_token():
    text = "Notification bot initialized with xoxb-1234567890-abcdefg12345"
    assert redact(text) == "Notification bot initialized with <redacted>"


def test_redact_github_token():
    text = "Deployment script using ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
    assert redact(text) == "Deployment script using <redacted>"


def test_redact_bearer_token():
    text = "Authorization: Bearer mySecretLongToken1234567890"
    assert redact(text) == "Authorization: Bearer <redacted>"


def test_redact_password_and_secret():
    text = "Connecting with password=super_secret_pass and api_key: 'topsecretkey123'"
    assert "password=<redacted>" in redact(text)
    assert "api_key=<redacted>" in redact(text)


def test_redact_email_and_phone():
    text = "Oncall responder: engineer@example.com, phone: 415-555-2671"
    assert redact(text) == "Oncall responder: <redacted>, phone: <redacted>"


def test_redact_private_key():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    assert redact(text) == "<redacted>"
