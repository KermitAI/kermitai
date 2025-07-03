from .harem import harem

async def setup(bot):
    await bot.add_cog(harem(bot))