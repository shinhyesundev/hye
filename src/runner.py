import asyncio
from components.studio_component import StudioComponent
from components.memory_component import MemoryComponent

async def main() -> None:
    studio_instance = StudioComponent()
    memory_instance = MemoryComponent(mongoose_uri="mongodb+srv://swansonbuisness:root@cluster0.aaimd.mongodb.net/")

    await studio_instance.connect()
    print("Studio Connected")

    await studio_instance.request_authentication_token()
    await studio_instance.request_authentication()
    print("Studio Authenticated")

    while True:
        await asyncio.sleep(60)

if __name__ == '__main__':
    asyncio.run(main())