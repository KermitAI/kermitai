from .forms import Forms

__red_end_user_data_statement__ = "Stores member IDs and form drafts until submission, cancellation, or data deletion. Submitted answers remain in the destination channel."

async def setup(bot):
    await bot.add_cog(Forms(bot))
