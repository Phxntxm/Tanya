from __future__ import annotations

import collections
import time
import typing

import discord


class Vote(discord.ui.View):
    def __init__(
        self,
        message: str,
        *,
        allowed: typing.List[discord.User | discord.Member] = [],
        timeout: typing.Optional[float] = None,
        yes_label: str = "yes",
        no_label: str = "no",
    ):
        super().__init__(timeout=timeout)
        self._message = message
        self.allowed = allowed
        self.votes: typing.Dict[int, str] = {}

        self._start_time: typing.Optional[float] = None
        self.yes.label = yes_label
        self.no.label = no_label

    @property
    def time_left(self) -> typing.Optional[float | str]:
        if self._start_time:
            _left = (self.timeout + self._start_time) - time.monotonic()
            return _left if _left > 0 else "No"
        return None

    @property
    def message(self) -> str:
        counter = collections.Counter(self.votes.values())
        if time_left := self.time_left:
            if isinstance(time_left, float):
                msg = f"{time_left:.2f} seconds left\n"
            else:
                msg = f"{time_left} seconds left\n"
        else:
            msg = ""
        msg += " to ".join(f"{value}: {count}" for value, count in counter.items())

        return f"{self._message}\n{msg}"

    async def start(self, channel: discord.abc.Messageable) -> collections.Counter[str]:
        self._start_time = time.monotonic()
        msg = await channel.send(self.message, view=self)

        await super().wait()

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        await msg.edit(view=self)
        return collections.Counter(self.votes.values())

    async def handle_click(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        if self.allowed and interaction.user in self.allowed:
            self.votes[interaction.user.id] = typing.cast(str, button.label)
            await interaction.response.edit_message(content=self.message, view=self)
        else:
            await interaction.response.send_message(
                "You are a spectator, you cannot vote",
                ephemeral=True,
            )

    @discord.ui.button(style=discord.ButtonStyle.green)
    async def yes(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.handle_click(button, interaction)

    @discord.ui.button(style=discord.ButtonStyle.red)
    async def no(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.handle_click(button, interaction)
