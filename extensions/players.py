from __future__ import annotations

import asyncio
import random
import typing
from enum import Enum

import discord
from discord.ext import commands

if typing.TYPE_CHECKING:
    from extensions.game import MafiaGame


class AttackType(Enum):
    basic = 1
    powerful = 2
    unstoppable = 3

    def __gt__(self, other: DefenseType):
        return self.value > other.value

    def __lt__(self, other: DefenseType):
        return self.value < other.value

    def __gte__(self, other: DefenseType):
        return self.value >= other.value

    def __lte__(self, other: DefenseType):
        return self.value <= other.value


class DefenseType(Enum):
    basic = 1
    powerful = 2
    unstoppable = 3

    def __gt__(self, other: AttackType):
        return self.value > other.value

    def __lt__(self, other: AttackType):
        return self.value < other.value

    def __gte__(self, other: AttackType):
        return self.value >= other.value

    def __lte__(self, other: AttackType):
        return self.value <= other.value


class Player:
    # This ID will be used for our hex config representation
    id: int = None
    # Different bools to determine player type
    is_mafia: bool = False
    is_citizen: bool = False
    is_independent: bool = False
    is_godfather: bool = False
    is_jailer: bool = False

    channel: discord.TextChannel = None
    dead: bool = False
    # Players that affect this player
    killed_by: Player = None
    visited_by: typing.List[Player] = None
    protected_by: Player = None
    # Different bools for specific roles needed for each player
    doused: bool = False
    lynched: bool = False
    night_role_blocked: bool = False
    # Needed to check win condition for mafia during day, before they kill
    can_kill_mafia_at_night: bool = False
    # The amount that can be used per game
    limit: int = 0
    attack_type: AttackType = None
    defense_type: DefenseType = None

    def __init__(self, discord_member: discord.Member):
        self.member = discord_member

    def __str__(self) -> str:
        return self.__class__.__name__

    def win_condition(self, game: MafiaGame) -> bool:
        return False

    def cleanup_attrs(self):
        self.killed_by = None
        self.visited_by = []
        self.protected_by = None
        self.night_role_blocked = False

    def startup_channel_message(self, game: MafiaGame) -> str:
        return f"Your role is {self}\n{self.description}."

    def set_channel(self, channel: discord.TextChannel):
        self.channel = channel

    def protect(self, by: Player):
        self.protected_by = by
        self.visited_by.append(by)

    def kill(self, by: Player):
        self.killed_by = by
        self.visited_by.append(by)

    def visit(self, by: Player):
        self.visited_by.append(by)

    @classmethod
    async def convert(cls, ctx: commands.Context, arg: str) -> Player:
        cls = next(p for p in __special_roles__ if p.__name__.lower() == arg.lower())
        if cls:
            return cls(ctx.author)

        return commands.BadArgument(f"Could not find a role named {arg}")

    async def wait_for_player(
        self,
        game: MafiaGame,
        message: str,
        only_others: bool = True,
        only_alive: bool = True,
        choices: typing.List[Player] = None,
    ) -> Player:
        # Get available choices based on what options given
        if choices is None:
            choices = []
            for p in game.players:
                if p.dead and only_alive:
                    continue
                if p == self and only_others:
                    continue
                choices.append(p.member.name)
        # Turn into string
        choices = "\n".join(choices)
        await self.channel.send(message + f". Choices are:\n{choices}")

        msg = await game.ctx.bot.wait_for(
            "message",
            check=game.ctx.bot.private_channel_check(game, self, not only_others),
        )
        return game.ctx.bot.get_mafia_player(game, msg.content)

    async def lock_channel(self):
        if self.channel:
            await self.channel.set_permissions(
                self.channel.guild.default_role,
                read_messages=False,
                send_messages=False,
            )

    async def unlock_channel(self):
        if self.channel:
            await self.channel.set_permissions(
                self.channel.guild.default_role, read_messages=False, send_messages=True
            )

    async def day_task(self, game: MafiaGame):
        pass

    async def night_task(self, game: MafiaGame):
        pass

    async def post_night_task(self, game: MafiaGame):
        pass


class Citizen(Player):
    id = 0
    is_citizen = True
    description = "Your win condition is lynching all mafia, you do not have a special role during the night"

    def win_condition(self, game):
        return game.total_mafia == 0


class Doctor(Citizen):
    id = 1
    defense_type = DefenseType.powerful
    description = (
        "During the night you can choose one person to save. "
        "They cannot be killed by a basic attack during that night"
    )

    async def night_task(self, game):
        # Get everyone alive that isn't ourselves
        msg = "Please provide the name of one player you would like to save from being killed tonight"
        player = await self.wait_for_player(game, msg)
        player.save()
        await self.channel.send("\N{THUMBS UP SIGN}")


class Sheriff(Citizen):
    id = 2
    attack_type = AttackType.basic
    description = (
        "During the night you can choose one person to shoot. "
        "If they are mafia, they will die... however if they are a citizen, you die instead"
    )
    can_kill_mafia_at_night = True

    async def night_task(self, game):
        # Get everyone alive that isn't ourselves
        msg = "If you would like to shoot someone tonight, provide just their name"
        player = await self.wait_for_player(game, msg)

        # Handle what happens if their choice is right/wrong
        if player.is_citizen:
            self.kill(self)
            player.visit(self)
        else:
            player.kill(self)
        await self.channel.send("\N{THUMBS UP SIGN}")


class Jailor(Citizen):
    id = 3
    is_jailer: bool = True
    jails: int = 3
    jailed: Player = None
    defense_type = DefenseType.powerful
    description = (
        "Each night you can choose to jail one person, during that night they "
        "will be able to see the jail chat, allowing you to converse with them. They "
        "will also not be able to perform their normal role that night"
    )

    async def day_task(self, game: MafiaGame):
        if self.jails <= 0:
            return
        msg = "If you would like to jail someone tonight, provide just their name"
        player = await self.wait_for_player(game, msg)
        player.night_role_blocked = True
        player.protect(self)
        self.jailed = player

        self.jails -= 1
        await self.channel.send("\N{THUMBS UP SIGN}")

    async def night_task(self, game: MafiaGame):
        if self.jailed:
            await game.jail.set_permissions(self.jailed.member, read_messages=True)
            game.ctx.create_task(self.unjail(game))

    async def unjail(self, game: MafiaGame):
        member = self.jailed.member
        self.jailed = None
        await asyncio.sleep(game._config.night_length)
        await game.jail.set_permissions(member, read_messages=False)


class PI(Citizen):
    id = 4
    description = (
        "Every night you can provide "
        "2 people, and see if their alignment is the same"
    )

    async def night_task(self, game):
        # Get everyone alive
        choices = [p.member.name for p in game.players if not p.dead]
        msg = "Provide the first person to check their alignments"
        player1 = await self.wait_for_player(game, msg, choices=choices)
        choices.remove(player1.member.name)
        msg = "Provide the second person to check their alignments"
        player2 = await self.wait_for_player(game, msg, choices=choices)

        # Now compare the two people
        if (
            (player1.is_citizen and player2.is_citizen)
            or (player1.is_mafia and player2.is_mafia)
            or (player1.is_independent and player2.is_independent)
        ):
            await self.channel.send(
                f"{player1.member.mention} and {player2.member.mention} have the same alignment"
            )
        else:
            await self.channel.send(
                f"{player1.member.mention} and {player2.member.mention} do not have the same alignment"
            )


class Lookout(Citizen):
    id = 5
    watching: Player = None
    description = (
        "Your job is to watch carefully, every night you can watch one person "
        "and will see who has visited them"
    )

    async def night_task(self, game: MafiaGame):
        msg = "Provide the player you want to watch tonight, at the end of the night I will let you know who visited them"
        self.watching = await self.wait_for_player(game, msg)
        await self.channel.send("\N{THUMBS UP SIGN}")

    async def post_night_task(self, game: MafiaGame):
        if self.watching is None:
            return

        visitors = self.watching.visited_by

        if visitors:
            fmt = "\n".join(p.member.name for p in visitors)
            msg = f"{self.watching.member.name} was visited by:\n{fmt}"
            await self.channel.send(msg)
        else:
            await self.channel.send(
                f"{self.watching.member.name} was not visited by anyone"
            )

        self.watching = None


class Mafia(Player):
    id = 75
    is_mafia = True
    attack_type = AttackType.basic
    description = (
        "Your win condition is to have majority of townsfolk be mafia. "
        "During the night you and your mafia buddies must agree upon 1 person to kill that night"
    )

    def win_condition(self, game):
        if game.is_day:
            # If any citizen can kill during the night, then we cannot guarantee
            # a win
            if any(
                player.can_kill_mafia_at_night
                for player in game.players
                if not player.dead
            ):
                return False
            else:
                return game.total_mafia >= game.total_alive / 2
        else:
            return game.total_mafia > game.total_alive / 2


class Independent(Player):
    is_independent = True


class Survivor(Independent):
    id = 150
    vests: int = 4
    defense_type = DefenseType.basic
    description = (
        "You must survive, each night you have the choice to use a bulletproof "
        "vest which will save you from a basic attack. You only have 4 vests"
    )

    async def night_task(self, game: MafiaGame):
        if self.vests <= 0:
            return

        msg = await self.channel.send(
            "Click the reaction if you want to protect yourself tonight "
            f"(You have {self.vests} vests remaining"
        )
        await msg.add_reaction("\N{THUMBS UP SIGN}")

        def check(p):
            return (
                p.message_id == msg.id
                and p.user_id == self.member.id
                and str(p.emoji) == "\N{THUMBS UP SIGN}"
            )

        await game.ctx.bot.wait_for("reaction_add", check=check)
        self.vests -= 1
        self.protected_by = self


class Jester(Independent):
    id = 151
    limit = 1
    description = "Your win condition is getting lynched or killed by the innocent"

    def win_condition(self, game):
        return self.lynched or (
            self.dead and self.killed_by and not self.killed_by.is_mafia
        )


class Executioner(Independent):
    id = 152
    limit = 1
    target = None
    description = (
        "Your win condition is getting a certain player lynched. If they "
        "die without getting lynched, you become a Jester. Your goal is to then get "
        "lynched yourself"
    )

    def startup_channel_message(self, game: MafiaGame):
        self.target = random.choice([p for p in game.players if p.is_citizen])
        self.description += f". Your target is {self.target.member.mention}"
        return super().startup_channel_message(game)

    def win_condition(self, game: MafiaGame):
        return (
            # If target is lynched
            self.target.lynched
            # If target is dead by not lynching, and WE'RE lynched
            or (self.target.dead and not self.target.lynched and self.lynched)
            # If we were killed by someone who isn't mafia
            or (self.dead and self.killed_by and not self.killed_by.is_mafia)
        )


class Arsonist(Independent):
    id = 153
    attack_type = AttackType.unstoppable
    description = (
        "Your job is simple, douse everyone in fuel and ignite them. You "
        "win if everyone has been ignited and you are the last person left"
    )

    async def night_task(self, game: MafiaGame):
        doused = [p for p in game.players if p.doused and not p.dead]
        doused_msg = "\n".join(p.member.name for p in doused)
        undoused = [p.member.name for p in game.players if not p.doused and not p.dead]
        msg = f"Doused targets:\n\n{doused_msg}\nChoose a target to douse, if you choose yourself you will ignite all doused targets"

        player = await self.wait_for_player(
            game, msg, only_others=False, choices=undoused
        )

        # Ignite
        if player == self:
            for player in doused:
                player.kill(self)
        else:
            player.doused = True
            player.visit(self)

        await self.channel.send("\N{THUMBS UP SIGN}")

    def win_condition(self, game: MafiaGame) -> bool:
        return game.total_alive == 1 and not self.dead


__special_mafia__ = ()
__special_citizens__ = (Doctor, Sheriff, PI, Jailor, Lookout)
__special_independents__ = (Jester, Executioner, Arsonist, Survivor)

__special_roles__ = __special_mafia__ + __special_citizens__ + __special_independents__
__all__roles__ = __special_roles__ + (Citizen, Mafia)


def setup(bot):
    bot.__special_citizens__ = __special_citizens__
    bot.__special_mafia__ = __special_mafia__
    bot.__special_independents__ = __special_independents__
    bot.__special_roles__ = __special_roles__
    bot.__all__roles__ = __all__roles__
    # Need the default mafia and citizen role too
    bot.mafia_role = Mafia
    bot.citizen_role = Citizen


def teardown(bot):
    del bot.__special_citizens__
    del bot.__special_mafia__
    del bot.__special_roles__
    del bot.__special_independents__
    del bot.__all__roles__
    del bot.mafia_role
    del bot.citizen_role
