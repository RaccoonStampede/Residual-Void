import residual_void_hyperdrive as hyperdrive
from residual_void import ResidualVoid


def test_hyperdrive_module_exports_runtime():
    assert hyperdrive.ResidualVoid is ResidualVoid
