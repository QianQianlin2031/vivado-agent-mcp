import pytest

from vivado_agent_mcp.vivado.protocol import (
    TclProtocolError,
    create_request,
    parse_response,
    tcl_quote,
    validate_tcl_name,
)


def test_request_uses_hex_payload_and_unique_marker() -> None:
    request = create_request('puts "hello"', request_id="abc123")

    assert 'puts "hello"' not in request.payload
    assert 'puts "<<<VAMCP:abc123:END>>>"' in request.payload
    assert request.end_marker == "<<<VAMCP:abc123:END>>>"


def test_parse_success_and_error() -> None:
    request = create_request("get_property NAME [current_project]", request_id="aa11")
    success = parse_response(request, "demo\n<<<VAMCP:aa11:RC=0>>>")
    failure = parse_response(request, "bad command\n<<<VAMCP:aa11:RC=1>>>")

    assert success.ok and success.output == "demo"
    assert not failure.ok and failure.error_message == "bad command"


def test_parse_rejects_missing_status_marker() -> None:
    request = create_request("version", request_id="beef")
    with pytest.raises(TclProtocolError):
        parse_response(request, "unframed output")


def test_tcl_escaping_and_identifier_validation() -> None:
    quoted = tcl_quote('C:/work/[demo]/$top/"file".xpr')
    assert quoted == '"C:/work/\\[demo\\]/\\$top/\\"file\\".xpr"'
    assert validate_tcl_name("impl_1") == "impl_1"
    with pytest.raises(ValueError):
        validate_tcl_name("impl_1; exit")
