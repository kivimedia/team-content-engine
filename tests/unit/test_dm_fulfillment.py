"""Tests for DM fulfillment audit trail (PRD Section 24.4)."""

from tce.models.dm_fulfillment import DMFulfillmentLog


def test_model_exists():
    assert DMFulfillmentLog is not None


def test_model_tracks_promises():
    """Must track what was promised."""
    assert hasattr(DMFulfillmentLog, "cta_keyword")
    assert hasattr(DMFulfillmentLog, "promised_asset")
    assert hasattr(DMFulfillmentLog, "platform")


def test_model_tracks_delivery():
    """Must track what was sent."""
    assert hasattr(DMFulfillmentLog, "dm_sent")
    assert hasattr(DMFulfillmentLog, "dm_sent_at")
    assert hasattr(DMFulfillmentLog, "dm_content")
    assert hasattr(DMFulfillmentLog, "delivery_method")


def test_model_tracks_status():
    """Must track fulfillment status."""
    assert hasattr(DMFulfillmentLog, "status")
    assert hasattr(DMFulfillmentLog, "failure_reason")


def test_model_tracks_compliance():
    """PRD Section 40.4: consent and opt-out tracking."""
    assert hasattr(DMFulfillmentLog, "consent_given")
    assert hasattr(DMFulfillmentLog, "opted_out")
    assert hasattr(DMFulfillmentLog, "whatsapp_joined")
