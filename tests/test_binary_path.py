"""Test binary residual imprint path."""
import base64
from residual_void.geometry import ResidualGeometry
from residual_void.mind import ResidualFieldMind


def test_binary_storage(geometry):
    """Verify that binary data is stored as base64-encoded text."""
    binary_data = b"\x00\x01\x02\x03\xff\xfe\xfd"
    # Encode to base64 first (as the implementation does)
    text_data = base64.b64encode(binary_data).decode("ascii")
    
    # Store the base64-encoded text
    rid = geometry.store(
        text_data,
        coherence=0.80,
        imprint_layer="medium",
    )
    
    # Retrieve and verify
    stored = geometry._data[rid]
    assert stored["value"] is not None, "Binary data not stored"
    assert isinstance(stored["value"], str), "Stored value should be string"
    assert stored["value"] == text_data, "Base64 encoding mismatch"


def test_mind_ingest_binary(mind):
    """Verify that mind.ingest_binary works end-to-end."""
    binary_data = b"Test binary payload"
    
    rid = mind.ingest_binary(binary_data)
    assert rid is not None, "Binary ingestion failed"
    assert rid in mind.geometry._data, "Binary not stored in geometry"
    
    item = mind.geometry._data[rid]
    assert item["domain"] == "binary", "Binary not marked as binary domain"
    assert item["imprint_layer"] == "medium", "Binary should use medium layer"
    
    # Verify it was base64 encoded
    expected_text = base64.b64encode(binary_data).decode("ascii")
    assert item["value"] == expected_text, "Binary not properly base64 encoded"
