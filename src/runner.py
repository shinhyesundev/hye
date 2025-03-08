import asyncio
from components.studio_component import StudioComponent

async def main() -> None:
    studio_instance = StudioComponent()

    await studio_instance.connect()
    print("Studio Connected")

    await studio_instance.request_authentication_token()
    await studio_instance.request_authentication()
    print("Studio Authenticated")

if __name__ == '__main__':
    asyncio.run(main())