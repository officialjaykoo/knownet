import os

from knownet_agent import KnowNetClient


with KnowNetClient.from_env() as client:
    client.require_scopes(["reviews:create", "pages:read"])

    if client.token_expires_soon():
        print("Token expires soon; rotate it before a long review.")

    pages = client.read_context_for_review(max_pages=5)
    print(f"Loaded {len(pages)} pages for review context.")

    markdown = os.environ.get(
        "KNOWNET_REVIEW_MARKDOWN",
        """### Finding

Severity: info
Area: Docs

Evidence:
Replace this example evidence with a scoped KnowNet observation.

Proposed change:
Replace this example proposal with the suggested change.
""",
    )

    result = client.dry_run_then_submit_review(markdown, source_agent="example-agent")
    if result.meta.get("warning"):
        print(f"Review was not submitted: {result.meta['warning']}")
    else:
        print(result.data)
