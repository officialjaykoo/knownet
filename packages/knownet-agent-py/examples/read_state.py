from knownet_agent import KnowNetClient


client = KnowNetClient.from_env()

print(client.me().data)
print(client.state_summary().data)
