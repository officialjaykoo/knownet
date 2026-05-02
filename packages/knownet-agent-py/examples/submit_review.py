from knownet_agent import KnowNetClient


client = KnowNetClient.from_env()

markdown = os.environ["KNOWNET_REVIEW_MARKDOWN"]
print(client.submit_review(markdown, source_agent="example-agent").data)
