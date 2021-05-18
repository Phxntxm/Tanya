from __future__ import annotations

import asyncio
import random
import typing
from enum import Enum

import discord
from discord.ext import commands

if typing.TYPE_CHECKING:
    from extensions.game import MafiaGame
    from extensions.roles import Role


class AttackType(Enum):
    basic = 1
    powerful = 2
    unstoppable = 3

    def __gt__(self, other: DefenseType):
        return self.value > other.value

    def __lt__(self, other: DefenseType):
        return self.value < other.value

    def __ge__(self, other: DefenseType):
        return self.value >= other.value

    def __le__(self, other: DefenseType):
        return self.value <= other.value


class DefenseType(Enum):
    basic = 1
    powerful = 2
    unstoppable = 3

    def __gt__(self, other: AttackType):
        return self.value > other.value

    def __lt__(self, other: AttackType):
        return self.value < other.value

    def __ge__(self, other: AttackType):
        return self.value >= other.value

    def __le__(self, other: AttackType):
        return self.value <= other.value


class Player:
    role: Role = None

    # This ID will be used for our hex config representation
    id: int = None
    description: str = ""
    short_description: str = ""

    channel: discord.TextChannel = None
    dead: bool = False

    # Players that affect this player
    killed_by: Player = None
    visited_by: typing.List[Player] = None
    protected_by: Player = None
    cleaned_by: Player = None
    disguised_as: Player = None
    executionor_target: Player = None
    # Different bools for specific roles needed for each player
    doused: bool = False
    lynched: bool = False
    night_role_blocked: bool = False
    jailed: bool = False

    def __init__(
        self, discord_member: discord.Member, ctx: commands.Context, role: Role
    ):
        self.member = discord_member
        self.ctx = ctx
        self.role = role

    def __str__(self) -> str:
        return str(self.role)

    @property
    def attack_type(self) -> AttackType:
        return self.role.attack_type

    @property
    def defense_type(self) -> DefenseType:
        return self.role.defense_type

    @property
    def limit(self) -> int:
        return self.role.limit

    @property
    def short_description(self) -> str:
        return self.role.short_description

    @property
    def description(self) -> str:
        return self.role.description

    @property
    def is_mafia(self) -> bool:
        mafia_role = self.ctx.bot.role_mapping.get("Mafia")
        return mafia_role and isinstance(self.role, mafia_role)

    @property
    def is_citizen(self) -> bool:
        citizen_role = self.ctx.bot.role_mapping.get("Citizen")
        return citizen_role and isinstance(self.role, citizen_role)

    @property
    def is_independent(self) -> bool:
        independent_role = self.ctx.bot.role_mapping.get("Independent")
        return independent_role and isinstance(self.role, independent_role)

    @property
    def is_godfather(self) -> bool:
        return self.role.is_godfather

    @property
    def is_jailor(self) -> bool:
        jailor_role = self.ctx.bot.role_mapping.get("Jailor")
        return jailor_role and isinstance(self.role, jailor_role)

    @property
    def can_kill_mafia_at_night(self) -> bool:
        return self.role.can_kill_mafia_at_night

    @property
    def win_is_multi(self) -> bool:
        return self.role.win_is_multi

    @property
    def startup_channel_message(self) -> str:
        return self.role.startup_channel_message

    def win_condition(self, game: MafiaGame) -> bool:
        return self.role.win_condition(game)

    def cleanup_attrs(self):
        self.visited_by = []
        self.killed_by = None
        self.protected_by = None
        self.night_role_blocked = False
        self.cleaned_by = None
        self.disguised_as = None
        self.jailed = False

    def set_channel(self, channel: discord.TextChannel):
        self.channel = channel
        self.role.channel = channel

    def protect(self, by: Player):
        self.protected_by = by
        self.visit(by)

    def kill(self, by: Player):
        self.killed_by = by
        self.visit(by)

    def clean(self, by: Player):
        self.cleaned_by = by
        self.visit(by)

    def disguise(self, target: Player, by: Player):
        self.disguised_as = target
        self.visit(by)

    def jail(self, by: Player):
        self.jailed = True
        self.protected_by = by
        self.visit(by)

    def visit(self, by: Player):
        self.visited_by.append(by)

    @classmethod
    async def convert(cls, ctx: commands.Context, arg: str) -> Player:
        for name, role in ctx.bot.role_mapping.items():
            if name not in ("Mafia", "Citizen") and name == arg:
                return cls(ctx.author, ctx, role())

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
        mapping = {count: player for count, player in enumerate(choices, start=1)}
        choices = "\n".join(f"{count}: {player}" for count, player in mapping.items())
        await self.channel.send(message + f". Choices are:\n{choices}")

        msg = await game.ctx.bot.wait_for(
            "message",
            check=game.ctx.bot.private_channel_check(
                game, self, mapping, not only_others
            ),
        )
        player = mapping[int(msg.content)]
        return game.ctx.bot.get_mafia_player(game, player)

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
        if msg := self.role.day_task(game):
            await self.channel.send(msg)

    async def night_task(self, game: MafiaGame):
        if msg := self.role.night_task(game):
            await self.channel.send(msg)

    async def post_night_task(self, game: MafiaGame):
        if msg := self.role.post_night_task(game):
            await self.channel.send(msg)


def setup(bot):
    bot.mafia_player = Player


def teardown(bot):
    del bot.mafia_player
