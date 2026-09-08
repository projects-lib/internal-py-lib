import httpx
import pytest

from internal_py_lib import ConfigServerClient


def test_build_url_with_label():
    c = ConfigServerClient(
        uri="http://cfg:8888/",
        application="svc",
        profile="sit",
        label="testing",
    )
    assert c._build_url() == "http://cfg:8888/svc/sit/testing"


def test_build_url_without_label():
    c = ConfigServerClient(uri="http://cfg:8888", application="svc", profile="sit")
    assert c._build_url() == "http://cfg:8888/svc/sit"


def test_reads_from_env(monkeypatch):
    monkeypatch.setenv("SPRING_CLOUD_CONFIG_URI", "http://cfg:8888")
    monkeypatch.setenv("APPLICATION_NAME", "vektor-creator-service")
    monkeypatch.setenv("SPRING_CLOUD_CONFIG_PROFILE", "sit")
    monkeypatch.setenv("LABEL", "testing")
    c = ConfigServerClient()
    assert c._build_url() == (
        "http://cfg:8888/vektor-creator-service/sit/testing"
    )


def test_merge_property_sources_first_wins():
    payload = {
        "propertySources": [
            {"name": "high", "source": {"a": 1, "b": 2}},
            {"name": "low", "source": {"b": 99, "c": 3}},
        ]
    }
    merged = ConfigServerClient._merge_property_sources(payload)
    assert merged == {"a": 1, "b": 2, "c": 3}


def test_fetch_fail_fast_raises(monkeypatch):
    def boom(self, url):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx.Client, "get", boom)
    c = ConfigServerClient(uri="http://cfg:8888", application="svc", profile="sit", fail_fast=True)
    with pytest.raises(RuntimeError):
        c.fetch()


def test_fetch_no_fail_fast_returns_empty(monkeypatch):
    def boom(self, url):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx.Client, "get", boom)
    c = ConfigServerClient(uri="http://cfg:8888", application="svc", profile="sit", fail_fast=False)
    assert c.fetch() == {}
