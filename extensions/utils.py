import discord
from discord.ext import commands
import re
import traceback


def get_mafia_player(game, arg):
    if not game:
        raise commands.BadArgument(
            "No game playing for this guild, cannot grab players"
        )

    players = game.players
    match = re.match(r"([0-9]{15,20})$", arg) or re.match(r"<@!?([0-9]{15,20})>$", arg)
    if match is None:
        result = discord.utils.get(players, member__name=arg)
        if not result:
            result = discord.utils.get(players, member__display_name=arg)
    else:
        user_id = int(match.group(1))
        result = discord.utils.get(players, member__id=user_id)

    if not result:
        raise commands.MemberNotFound(arg)

    return result


def to_keycap(i):
    return f"{i}\N{variation selector-16}\N{combining enclosing keycap}"


def min_max_check(ctx, min, max):
    def check(m):
        if m.channel != ctx.channel:
            return False
        if m.author != ctx.author:
            return False
        try:
            amt = int(m.content)
        except ValueError:
            return False
        else:
            return min <= amt <= max

    return check


def nomination_check(game, nominations, channel, mafia=False):
    if mafia:
        noms_needed = 1 if game.total_mafia else 2
    else:
        noms_needed = 2

    def check(m: discord.Message):
        # Ignore if not in channel we want
        if m.channel != channel:
            return False
        # Ignore if not player of game (admins, bots)
        if m.author not in [p.member for p in game.players]:
            return False
        # Ignore if not the right type of message
        if not m.content.startswith(">>nominate "):
            return False
        # Try to get the player
        try:
            content = m.content.split(">>nominate ")[1]
            player = game.ctx.bot.get_mafia_player(game, content)
        except commands.MemberNotFound:
            return False
        else:
            # Increment their nomination
            nominations[player] = nominations.get(player, 0) + 1
            # If their nomination meets what's needed, set the player
            if nominations[player] == noms_needed:
                nominations["nomination"] = player
                return True
            # Otherwise mention need one more
            else:
                game.ctx.bot.loop.create_task(
                    m.channel.send(
                        f"{player.member.display_name} nominated, need one more"
                    )
                )

    return check


async def log_error(error, bot, ctx=None):
    # Format the error message
    fmt = f"""```
{''.join(traceback.format_tb(error.__traceback__)).strip()}
{error.__class__.__name__}: {error}```"""
    # Add the command if ctx is given
    if ctx is not None:
        fmt = f"Command = {discord.utils.escape_markdown(ctx.message.clean_content).strip()}\n{fmt}"
    # If the channel has been set, use it
    if isinstance(bot.error_channel, discord.TextChannel):
        await bot.error_channel.send(fmt)
    # Otherwise if it hasn't been set yet, try to set it
    if isinstance(bot.error_channel, int):
        channel = bot.get_channel(bot.error_channel)
        if channel is not None:
            bot.error_channel = channel
            await bot.error_channel.send(fmt)
        # If we can't find the channel yet (before ready) just send to file
        else:
            fmt = fmt.strip("`")
            with open("error_log", "a") as f:
                print(fmt, file=f)
    # Otherwise just send to file
    else:
        fmt = fmt.strip("`")
        with open("error_log", "a") as f:
            print(fmt, file=f)


def setup(bot):
    bot.log_error = log_error
    bot.min_max_check = min_max_check
    bot.to_keycap = to_keycap
    bot.get_mafia_player = get_mafia_player
    bot.nomination_check = nomination_check


def teardown(bot):
    del bot.log_error
    del bot.min_max_check
    del bot.to_keycap
    del bot.get_mafia_player
    del bot.nomination_check
