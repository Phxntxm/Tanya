from custom_models import Context
from discord.ext import commands


class ErrorHandler(commands.Cog):
    @commands.Cog.listener()
    async def on_command_error(self, ctx: Context, error: commands.CommandError):
        error = getattr(error, "original", error)
        ignored_errors = (
            commands.CommandNotFound,
            commands.DisabledCommand,
            commands.CheckFailure,
        )
        # return await ctx.bot.log_error(error, ctx.bot, ctx)
        if isinstance(error, ignored_errors):
            return

        if isinstance(error, commands.BadArgument):
            fmt = f"Please provide a valid argument to pass to the command: {error}"
            await ctx.send(fmt)
        elif isinstance(
            error, (commands.CommandOnCooldown, commands.MaxConcurrencyReached)
        ):
            await ctx.message.add_reaction("\U0000274c")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("This command must be ran in a guild")
        else:
            await ctx.log_error(error)


def setup(bot):
    bot.add_cog(ErrorHandler())
