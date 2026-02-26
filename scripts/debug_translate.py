import asyncio
from ipaws_research.translations import translate_with_gpt4o

async def main():
    res = await translate_with_gpt4o('Evacuate immediately due to wildfire. Life-threatening conditions.', 'es')
    print('Translation:', res['translation'][:200])
    print('Metadata:', res['metadata'])

if __name__ == '__main__':
    asyncio.run(main())
