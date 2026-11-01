from .crates import Crates


async def setup(bot):
    await bot.add_cog(Crates(bot))
