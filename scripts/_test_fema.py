import asyncio, aiohttp, traceback

async def test():
    try:
        params = {"$filter": "contains(info/area/areaDesc, 'CA')", "$top": "5"}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.get("https://www.fema.gov/api/open/v1/IpawsArchivedAlerts", params=params) as r:
                print("Status:", r.status)
                text = await r.text()
                print(text[:800])
    except Exception as e:
        traceback.print_exc()

asyncio.run(test())
