from .onboarder import Onboarder

__red_end_user_data_statement__ = (
    "Stores active questionnaires, respondent IDs, answers, and message IDs until submission or cancellation. "
    "Submitted responses remain in the configured Discord channel."
)


async def setup(bot):
    await bot.add_cog(Onboarder(bot))
