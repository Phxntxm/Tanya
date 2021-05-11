from discord.ext import commands


class ErrorHandler(commands.Cog):
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        error = error.original if hasattr(error, "original") else error
        ignored_errors = (
            commands.CommandNotFound,
            commands.DisabledCommand,
            commands.CheckFailure,
            commands.CommandOnCooldown,
            commands.MaxConcurrencyReached,
        )
        # return await ctx.bot.log_error(error, ctx.bot, ctx)
        if isinstance(error, ignored_errors):
            return
        else:
            await ctx.bot.log_error(error, ctx.bot, ctx)


def setup(bot):
    bot.add_cog(ErrorHandler())
