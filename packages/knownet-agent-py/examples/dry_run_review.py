from knownet_agent import KnowNetClient


client = KnowNetClient.from_env()

markdown = """### Finding

Severity: info
Area: Docs

Evidence:
The agent can parse this review.

Proposed change:
Keep the format stable.
"""

print(client.dry_run_review(markdown, source_agent="example-agent").data)
