"""Hide only the known utcnow flood. Keep other warnings visible."""
import warnings


def test_only_utcnow_deprecation_is_filtered():
    with warnings.catch_warnings(record=True) as recorded:
        warnings.warn("datetime.datetime.utcnow() is deprecated and scheduled for removal", DeprecationWarning)
        warnings.warn("A new synthetic deprecation", DeprecationWarning)
        warnings.warn("A new synthetic warning", UserWarning)
    assert [str(warning.message) for warning in recorded] == [
        "A new synthetic deprecation", "A new synthetic warning",
    ]
