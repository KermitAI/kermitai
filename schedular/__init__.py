from .schedular import Schedular

__red_end_user_data_statement__ = "Stores server announcement messages, channel IDs and schedules. No member-specific data is stored."


async def setup(bot):
    await bot.add_cog(Schedular(bot))
