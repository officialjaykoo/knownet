import os

from knownet_agent import KnowNetClient


client = KnowNetClient(
    base_url=os.getenv("KNOWNET_BASE_URL", "http://127.0.0.1:8000"),
    token=os.environ["KNOWNET_AGENT_TOKEN"],
)

markdown = """### Finding

Severity: info
Area: Docs

Evidence:
The agent can parse this review.

Proposed change:
Keep the format stable.
"""

print(client.dry_run_review(markdown, source_agent="example-agent").data)
