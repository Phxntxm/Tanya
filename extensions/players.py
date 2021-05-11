import asyncio
import discord


class Player:
    is_mafia: bool = False
    is_citizen: bool = False
    channel: discord.TextChannel = None
    # Dead is for someone who has been dead
    dead: bool = False
    # Killed is for someone who was just killed this night
    killed: bool = False
    unlocked: bool = True
    saved_for_tonight = False

    def __init__(self, discord_member: discord.Member):
        self.member = discord_member

    def __str__(self):
        return self.__class__.__name__

    def set_channel(self, channel: discord.TextChannel):
        self.channel = channel

    def save(self):
        self.saved_for_tonight = True

    def kill(self):
        self.killed = True

    def schedule_lock_channel(self, future=None):
        loop = asyncio.get_running_loop()
        loop.create_task(self.lock_channel())

    async def lock_channel(self):
        self.unlocked = False
        if self.channel:
            await self.channel.set_permissions(
                self.channel.guild.default_role,
                read_messages=False,
                send_messages=False,
            )

    async def unlock_channel(self):
        self.unlocked = True
        if self.channel:
            await self.channel.set_permissions(
                self.channel.guild.default_role, read_messages=False, send_messages=True
            )

    async def day_task(self, game):
        pass

    async def night_task(self, game):
        pass


class Citizen(Player):
    is_citizen = True


class Inspector(Citizen):
    pass


class Doctor(Citizen):
    async def night_task(self, game):
        # Get everyone alive that isn't ourselves
        choices = [p for p in game.players if p != self and not p.dead]
        # F strings dumb, so get the output for f string here
        choices_names = "\n".join([p.member.name for p in choices])
        await self.channel.send(
            "Please provide the name of one player you would like to save from being killed tonight. Choices are:"
            f"\n{choices_names}"
        )

        player = None

        def check(m):
            # Only care about messages from the author in their channel
            if m.channel != self.channel:
                return False
            elif m.author != self.member:
                return False
            # Set the player for use after
            nonlocal player
            player = discord.utils.get(game.players, member__name=m.content)
            # Doctor cannot save themselves
            if player == self:
                game.ctx.bot.loop.create_task(
                    self.channel.send("You cannot save yourself")
                )
            elif player is not None:
                return True

        await game.ctx.bot.wait_for("message", check=check)
        player.save()
        await self.channel.send("\N{THUMBS UP SIGN}")


class Mafia(Player):
    is_mafia = True


class MobBoss(Mafia):
    pass


__special_mafia__ = (
    # MobBoss,
)

__special_citizens__ = (
    # Inspector,
    Doctor,
)

__special_roles__ = __special_mafia__ + __special_citizens__


def setup(bot):
    bot.__special_citizens__ = __special_citizens__
    bot.__special_mafia__ = __special_mafia__
    bot.__special_roles__ = __special_roles__
    # Need the default mafia and citizen role too
    bot.mafia_role = Mafia
    bot.citizen_role = Citizen


def teardown(bot):
    del bot.__special_citizens__
    del bot.__special_mafia__
    del bot.__special_roles__
