"""Tests for WhatsApp integration (PRD Section 40)."""

from tce.services.whatsapp import WhatsAppFlow, WhatsAppService


def test_dm_flow_creation():
    service = WhatsAppService()
    flow = service.generate_dm_flow("guide", "Weekly AI Guide")
    assert flow.keyword == "guide"
    assert "guide" in flow.ack_message.lower()
    assert flow.consent_required is True


def test_dm_flow_to_dict():
    flow = WhatsAppFlow(
        keyword="test",
        ack_message="ack",
        delivery_message="deliver",
    )
    d = flow.to_dict()
    assert d["keyword"] == "test"
    assert "ack_message" in d
    assert "consent_required" in d


def test_opt_in_message():
    service = WhatsAppService()
    msg = service.generate_opt_in_message()
    assert "YES" in msg
    assert "join" in msg.lower()


def test_opt_out_message():
    service = WhatsAppService()
    msg = service.generate_opt_out_message()
    assert "STOP" in msg


def test_operator_checklist():
    service = WhatsAppService()
    checklist = service.get_operator_checklist("agents")
    assert len(checklist) >= 5
    assert any("agents" in item for item in checklist)


def test_validate_flow_valid():
    flow = WhatsAppFlow(
        keyword="test",
        ack_message="thanks",
        delivery_message="here you go",
        consent_required=True,
    )
    issues = WhatsAppService.validate_flow(flow)
    assert len(issues) == 0


def test_validate_flow_no_consent():
    flow = WhatsAppFlow(
        keyword="test",
        ack_message="thanks",
        delivery_message="here",
        consent_required=False,
    )
    issues = WhatsAppService.validate_flow(flow)
    assert any("consent" in i.lower() for i in issues)


def test_supported_message_types():
    assert len(WhatsAppService.SUPPORTED_MESSAGE_TYPES) == 4
    assert "group_invite_link" in WhatsAppService.SUPPORTED_MESSAGE_TYPES
