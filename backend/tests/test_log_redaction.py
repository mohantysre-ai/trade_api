import logging

from app.utils.log_redaction import SecretRedactionFilter, redact_secrets


def test_redacts_smartapi_error_headers():
    message = (
        "Headers: {'X-PrivateKey': 'do-not-print', 'Authorization': 'Bearer token', "
        "'Accept': 'application/json'}"
    )

    redacted = redact_secrets(message)

    assert "do-not-print" not in redacted
    assert "Bearer token" not in redacted
    assert redacted.count("[REDACTED]") == 2
    assert "application/json" in redacted


def test_filter_redacts_formatted_log_arguments():
    record = logging.LogRecord("vendor", logging.ERROR, __file__, 1, "api_key=%s", ("secret",), None)

    assert SecretRedactionFilter().filter(record) is True
    assert record.getMessage() == "api_key=[REDACTED]"
