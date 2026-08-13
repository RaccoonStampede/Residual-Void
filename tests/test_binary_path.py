"""Test binary residual imprint path."""
import base64
from src.residual_void.geometry import ResidualGeometry
from src.residual_void.mind import ResidualFieldMind


def test_binary_storage(geometry):
    """Verify that binary data is stored and retrieved correctly."""
    binary_data = b"\x00\x01\x02\x03\xff\xfe\xfd"
    expected_encoded = base64.b64encode(binary_data).decode("ascii")
    
    # Store encoded binary payload
    rid = geometry.store(
        expected_encoded,
        coherence=0.80,
        domain="binary",
        imprint_layer="medium",
    )
    
    # Retrieve and check
    stored = geometry._data[rid]
    assert stored["value"] is not None, "Binary not stored"
    
    assert stored["value"] == expected_encoded, "Binary encoding mismatch"


def test_mind_ingest_binary(mind):
    """Verify that mind.ingest_binary works end-to-end."""
    binary_data = b"Test binary payload"
    
    rid = mind.ingest_binary(binary_data)
    assert rid is not None, "Binary ingestion failed"
    assert rid in mind.geometry._data, "Binary not stored in geometry"
    
    item = mind.geometry._data[rid]
    assert item["domain"] == "binary", "Binary not marked as binary domain"
    assert item["imprint_layer"] == "medium", "Binary should use medium layer"
