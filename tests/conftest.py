"""Shared fixtures. Seam B (spec Testing Decisions): one session-scoped Spark session per
pytest process (~9 s), skipping (never failing) when no JVM is found."""
import pytest


@pytest.fixture(scope="session")
def spark():
    from raincheck.spark import java_home, session  # pyspark import cost only when a test asks

    if java_home() is None:
        pytest.skip("no JVM found: set JAVA_HOME (see Makefile) or brew install openjdk@17")
    s = session()
    yield s
    s.stop()
