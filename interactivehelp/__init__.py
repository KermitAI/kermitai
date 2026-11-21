from .interactivehelp import InteractiveHelp


async def setup(bot):
    await bot.add_cog(InteractiveHelp(bot))

