from knownet_agent import KnowNetClient


with KnowNetClient.from_env() as client:
    for page in client.iter_pages(limit=10, max_items=25):
        print(f"{page.id}\t{page.title or page.slug}")
