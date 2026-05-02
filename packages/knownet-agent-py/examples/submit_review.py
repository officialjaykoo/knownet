import os

from knownet_agent import KnowNetClient


client = KnowNetClient(
    base_url=os.getenv("KNOWNET_BASE_URL", "http://127.0.0.1:8000"),
    token=os.environ["KNOWNET_AGENT_TOKEN"],
)

markdown = os.environ["KNOWNET_REVIEW_MARKDOWN"]
print(client.submit_review(markdown, source_agent="example-agent").data)
