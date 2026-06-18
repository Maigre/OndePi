import logging

from ondepi.logging_setup import configure_logging, resolve_level


def test_resolve_level_known_and_default():
    assert resolve_level("debug") == logging.DEBUG
    assert resolve_level("INFO") == logging.INFO
    assert resolve_level("warn") == logging.WARNING
    assert resolve_level(None) == logging.INFO
    assert resolve_level("nonsense") == logging.INFO


def test_configure_is_idempotent():
    flag = "_ondepi_handler"
    before = [h for h in logging.getLogger().handlers if getattr(h, flag, False)]
    for h in before:
        logging.getLogger().removeHandler(h)
    configure_logging("info")
    configure_logging("debug")
    handlers = [h for h in logging.getLogger().handlers if getattr(h, flag, False)]
    assert len(handlers) == 1


def test_package_level_applied_and_records_emitted():
    configure_logging("debug")
    assert logging.getLogger("ondepi").level == logging.DEBUG
    # An ondepi.* INFO record must reach handlers even though root stays WARNING.
    with __import__("unittest").TestCase().assertLogs("ondepi.sample", level="INFO"):
        logging.getLogger("ondepi.sample").info("hello")
