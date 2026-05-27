from modes.ball import AutoBallMode
from modes.ball_cruise import AutoCruiseMode
from modes.ball_pet import AutoBallPetMode

MODE_REGISTRY = {
    "1": AutoBallMode,
    "2": AutoBallPetMode,
    "3": AutoCruiseMode,
}

__all__ = ["MODE_REGISTRY"]
