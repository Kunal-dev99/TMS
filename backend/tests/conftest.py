"""A seeded book in a throwaway database, per test.

Every test gets its own file, so a test that supersedes a limit or books a
deal cannot change what the next one sees. The schema comes from the models
rather than from the migrations, because `test_phase0.py` already asserts
that the migrations build the same thing from empty.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app import seed_data as s  # noqa: E402
from app.db import get_session  # noqa: E402
from app.models import Base  # noqa: E402
from app.repo import policy as policy_repo  # noqa: E402
from app.services.check_engine import CheckEngine  # noqa: E402
from seed.seed import load  # noqa: E402


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch):
    """The suite never reaches the network.

    A developer with a real key in their environment would otherwise have a
    test suite whose result depends on somebody else's endpoint being up. The
    tests that care about the model inject a ranker instead.
    """
    monkeypatch.delenv("TREASURY_MODEL_API_KEY", raising=False)


@pytest.fixture
def session(tmp_path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    db = factory()
    load(db)
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def engine_for(session: Session):
    """A CheckEngine against the seeded book, on the seeded clock date.

    Takes the policy version in force at call time, so a test that supersedes
    the policy gets an engine reading the new one.
    """

    def build(as_of: str | None = None) -> CheckEngine:
        policy = policy_repo.current_policy(session, s.TENANT_ID)
        assert policy is not None, "The seed did not load a policy version."
        return CheckEngine(
            session=session,
            tenant_id=s.TENANT_ID,
            as_of_date=as_of or s.CLOCK_DATE,
            policy=policy,
        )

    return build


@pytest.fixture
def anonymous(session: Session):
    """The API with no token. Everything except signing in is refused."""
    from fastapi.testclient import TestClient

    from app.main import app

    def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def sign_in(test_client, email: str, password: str = "treasury") -> str:
    response = test_client.post(
        "/api/v1/auth/token", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


@pytest.fixture
def client(anonymous):
    """Signed in as A. Whitfield, who holds ANALYST.

    Most tests propose rather than sign, and the one that proposes is the one
    that must not also approve. Tests that need a signature use `signer`.
    """
    token = sign_in(anonymous, "a.whitfield@northgate.example")
    anonymous.headers.update({"Authorization": f"Bearer {token}"})
    return anonymous


@pytest.fixture
def signer(session: Session):
    """A second client, signed in as M. Doran, who holds HEAD_OF_TREASURY.

    A separate client rather than a second token on the same one, because
    segregation of duties is the point and two people sharing a session
    would quietly defeat it in the tests as well as in the product.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as test_client:
        token = sign_in(test_client, "m.doran@northgate.example")
        test_client.headers.update({"Authorization": f"Bearer {token}"})
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def cfo(session: Session):
    """R. Sethi, who holds CFO and nothing else."""
    from fastapi.testclient import TestClient

    from app.main import app

    def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as test_client:
        token = sign_in(test_client, "r.sethi@northgate.example")
        test_client.headers.update({"Authorization": f"Bearer {token}"})
        yield test_client
    app.dependency_overrides.clear()
