from .polls import Polls

__red_end_user_data_statement__ = "Stores member IDs and selected options for active polls. Voting records are removed after final results delivery or on a data deletion request. Published results remain in Discord."


async def setup(bot):
    await bot.add_cog(Polls(bot))
