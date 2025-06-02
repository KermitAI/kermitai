from .fivebells import fivebells

async def setup(bot):
    await bot.add_cog(fivebells(bot))
