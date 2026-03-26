"""ImageAsset model — generated images from fal.ai prompts."""

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class ImageAsset(Base):
    __tablename__ = "image_assets"

    package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("post_packages.id"))

    # Prompt
    prompt_text: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Generation
    fal_model_used: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fal_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    image_s3_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Specs
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    aspect_ratio: Mapped[str | None] = mapped_column(String(10), nullable=True)
    generation_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    generation_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Review
    operator_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    operator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    post_package: Mapped["PostPackage"] = relationship(back_populates="image_assets")  # noqa: F821
