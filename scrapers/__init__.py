"""Collector package with script/package import compatibility."""
import sys

from . import social_base as _social_base
sys.modules.setdefault("social_base", _social_base)
from . import platforms as _platforms
sys.modules.setdefault("platforms", _platforms)
from . import textutil as _textutil

sys.modules.setdefault("textutil", _textutil)
