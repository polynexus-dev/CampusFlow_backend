import os, django, asyncio
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
django.setup()

from channels.layers import get_channel_layer

async def test_redis():
    channel_layer = get_channel_layer()
    print("Channel layer:", channel_layer)
    if channel_layer is None:
        print("Channel layer is not configured.")
        return
        
    try:
        print("Adding channel to group...")
        await channel_layer.group_add("test_group", "test_channel")
        print("Successfully added to group!")
        
        print("Sending message to group...")
        await channel_layer.group_send("test_group", {"type": "test_message", "text": "hello"})
        print("Successfully sent message!")
        
    except Exception as e:
        print(f"Redis Channel Layer Error: {e}")

asyncio.run(test_redis())
