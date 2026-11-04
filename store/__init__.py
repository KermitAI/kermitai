from .store import Store


async def setup(bot):
    await bot.add_cog(Store(bot))
