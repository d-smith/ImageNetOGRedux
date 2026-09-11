"""Auth property tests (task 23.1) — Property 3: JWT validation correctness.

Property 3 states: a well-formed JWT with a valid signature, non-expired
``exp``, and matching ``iss`` / ``aud`` is allowed; a token failing any check
(bad signature, expired, wrong issuer/audience, missing ``Authorization``
header, non-Bearer scheme) is rejected with HTTP 401.

Why there is no unit/property test to run here
-----------------------------------------------
In this system, JWT validation is performed **entirely by the API Gateway
Cognito authorizer** (``aws_api_gateway_authorizer`` of type
``COGNITO_USER_POOLS`` in ``terraform/modules/api/apigw.tf``). It is an
AWS-managed component: API Gateway verifies the token signature against the
Cognito JWKS endpoint and checks ``exp`` / ``iss`` / ``aud`` before the request
ever reaches the ``api_handler`` Lambda.

The application code contains **no JWT parsing, signature verification, or JWKS
handling** — a deliberate design choice (see design.md "Cognito JWT Authorizer"
and the ``api_handler`` responsibilities, which start at "route validation",
after auth). Confirmed: the only auth-related reference in ``src/`` is the
``COGNITO_USER_POOL_ID`` config value, which is passed through for context and
is not used to validate tokens.

Consequently, Property 3 cannot be meaningfully expressed as a Hypothesis +
moto unit test: there is no in-repo function that accepts a token and returns
allow/reject. A test that fabricated its own JWKS-verification routine would be
testing invented logic, not the system's actual behaviour — which would be
misleading rather than useful.

Where Property 3 IS verified
----------------------------
Against the **deployed** API Gateway, via the integration test in task 25.1
(``tests/integration/test_auth_integration.py``): assert the live endpoint
returns 401 with the structured JSON error body for missing / malformed /
expired / wrong-audience tokens, and 200 for a valid token. That is the correct
layer to exercise an AWS-managed authorizer.

This module is intentionally a documented skip so the decision is explicit and
discoverable rather than a silently-missing test.
"""

import pytest

pytest.skip(
    "Property 3 (JWT validation) is enforced by the AWS-managed API Gateway "
    "Cognito authorizer; there is no in-application code to unit-test. It is "
    "verified by the deployed-environment integration test in task 25.1.",
    allow_module_level=True,
)
