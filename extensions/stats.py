import collections
import typing

import asyncpg
import discord
from discord.ext import commands
from utils import Context

if typing.TYPE_CHECKING:
    from utils.custom_bot import MafiaBot


class Stats(commands.Cog):
    @commands.command("stats")
    async def stats(
        self,
        ctx: "Context",
        user: typing.Optional[discord.User] = None,
        only_this_server=False,
    ):
        user = user or ctx.author

        if only_this_server and not ctx.guild:
            return await ctx.reply(
                "You cannot get server stats in dms", mention_author=False
            )

        query = """
        SELECT
            games.id, guild_id, day_count, p.win, p.die, r.name AS role, r.alignment
        FROM games
        INNER JOIN players p ON 
            games.id = p.game_id AND p.user_id = $1
        INNER JOIN roles r ON
            r.id = p.role
        WHERE
            user_id = $1
        """
        async with ctx.acquire() as conn:
            games = await conn.fetch(query, user.id)

            query = """
            SELECT
                game_id, killer, killed, night, suicide
            FROM kills
            WHERE
                killer = $1 OR killed = $1
            """
            kills = await conn.fetch(query, user.id)

        if not games:
            return await ctx.reply(f"No stats for {user}", mention_author=False)

        if only_this_server:
            games = list(filter(lambda row: row["guild_id"] == ctx.guild.id, games))
            _game_ids = tuple(x["id"] for x in games)
            kills = list(filter(lambda row: row["game_id"] in _game_ids, kills))

        def condition(
            predicate: typing.Callable[[asyncpg.Record], bool], data: list
        ) -> int:
            return len(tuple(filter(predicate, data)))

        wins = condition(lambda row: row["win"], games)
        suicides = condition(lambda row: row["suicide"], kills)
        mafia = condition(lambda row: row["role"] == "Mafia", games)
        roles = collections.Counter([x["role"] for x in games])
        top_role = roles.most_common(1)[0]

        deaths = condition(lambda row: row["killed"] == user.id, kills)
        kills = condition(lambda row: row["killer"] == user.id, kills)

        apost = "'"  # stupid fstrings

        fmt = (
            f"{'You have' if user == ctx.author else f'{user} has'} played {len(games)} game{'s' if len(games) != 1 else ''}"
            f"{' in this server' if only_this_server else ''}, won {wins} game{'s' if wins != 1 else ''}, "
            f"killed {kills-suicides} {'people' if kills-suicides != 1 else 'person'}, died {deaths} time{'s' if deaths != 1 else ''}, committed suicide "
            f"{suicides} time{'s' if suicides != 1 else ''}, and been mafia {mafia} time{'s' if mafia != 1 else ''}.\n\n"
            f"{'Your' if user == ctx.author else f'{user.name}{apost}s'} most common role "
            f"{'here ' if only_this_server else ''}is {top_role[0]}, with {top_role[1]} game{'s' if top_role[1] != 1 else ''}."
        )
        await ctx.reply(fmt, mention_author=False)


def setup(bot: "MafiaBot"):
    bot.add_cog(Stats())
