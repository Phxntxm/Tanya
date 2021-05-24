import importlib
from types import ModuleType

from discord.ext import commands


class Cog(commands.Cog):
    def reload(self, module: ModuleType):
        importlib.reload(module)
