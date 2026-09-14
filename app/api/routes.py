"""路由聚合器：全部子 router 在此注册，main.py 只 include 这一个。

新增端点时：在 ``app/api/v1/`` 建路由文件并在此 include，不再改 main.py。
"""

from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.v1.agent import router as agent_router
from app.api.v1.combat import router as combat_router
from app.api.v1.commands import router as commands_router
from app.api.v1.companion import router as companion_router
from app.api.v1.console import router as console_router
from app.api.v1.speech import router as speech_router
from app.api.v1.tactical import router as tactical_router
from app.api.v1.voice import router as voice_router
from app.api.v1.world import router as world_router

router = APIRouter()
router.include_router(health_router)
router.include_router(commands_router)
router.include_router(companion_router)
router.include_router(voice_router)
router.include_router(speech_router)
router.include_router(tactical_router)
router.include_router(combat_router)
router.include_router(agent_router)
router.include_router(world_router)
router.include_router(console_router)
