import asyncio
import websockets
import json

async def test_connect():
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzgzNTMxMDMyLCJpYXQiOjE3ODM1MDIyMzIsImp0aSI6IjdhZDkzNDE3Mzk5NjRlMWI5MDU0MTkyYzUwNWQzNWE2IiwidXNlcl9pZCI6MTAsInRlbmFudF9zY2hlbWEiOiJkZW1vIn0.0iC6RujeyB6Ddrm3ZnoJrSGXSIUKGlZUtiTcE7NwGsA"
    url = f"ws://127.0.0.1:8000/ws/bus-tracking/?token={token}&schema=demo"
    
    print(f"Connecting to {url}...")
    try:
        async with websockets.connect(url) as ws:
            print("Connected successfully!")
            
            # Send track route (Route 2 is the seeded Route 1 - Wardha Road)
            payload = {"action": "track_route", "route_id": 2}
            print("Sending:", payload)
            await ws.send(json.dumps(payload))
            
            # Wait for response
            response = await ws.recv()
            print("Received response:", response)
            
            # Keep listening for updates
            print("Listening for updates...")
            for _ in range(3):
                msg = await ws.recv()
                print("Received update:", msg)
                
    except Exception as e:
        print(f"Connection failed: {e}")

asyncio.run(test_connect())
