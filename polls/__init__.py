from .polls import Polls

__red_end_user_data_statement__ = 'Stores member IDs and selected options until results delivery, poll deletion or user data deletion. Retains completed poll and results message locations until poll deletion. Published results remain in Discord unless deleted with polldelete.'


async def setup(bot):
    await bot.add_cog(Polls(bot))
