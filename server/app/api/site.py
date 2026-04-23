import logging

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.responses import SiteConfigOut

router = APIRouter(prefix="/site-config", tags=["site"])

log = logging.getLogger(__name__)


@router.get("", response_model=SiteConfigOut)
async def get_site_config():
    feedback_enabled = bool(settings.feedback_form_url)
    analytics_enabled = bool(settings.posthog_public_key)
    log.info(
        "site config requested feedback_enabled=%s analytics_enabled=%s",
        feedback_enabled,
        analytics_enabled,
    )
    return SiteConfigOut(
        feedback_form_url=settings.feedback_form_url,
        posthog_public_key=settings.posthog_public_key,
        posthog_host=settings.posthog_host,
    )
