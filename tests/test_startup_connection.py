"""Failed WhatsApp login must not start model work or leave a client running."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import main


def test_connected_client_can_proceed():
    client = SimpleNamespace(connection_error=None, is_connected=lambda: True)
    main._wait_for_whatsapp(client, timeout=1)


def test_outdated_client_fails_without_waiting():
    client = SimpleNamespace(connection_error='Client outdated', is_connected=lambda: False)
    with patch.object(main.time, 'sleep') as sleep:
        with pytest.raises(ConnectionError, match='outdated'):
            main._wait_for_whatsapp(client, timeout=60)
    sleep.assert_not_called()


def test_unconnected_client_times_out():
    client = SimpleNamespace(connection_error=None, is_connected=lambda: False)
    with patch.object(main.time, 'sleep'):
        with pytest.raises(ConnectionError, match='timeout'):
            main._wait_for_whatsapp(client, timeout=2)


def test_failed_login_stops_before_bootstrap_or_scheduler():
    config = MagicMock()
    config.log_level = 'INFO'
    client = MagicMock()
    client.connection_error = 'Client outdated'
    with patch.object(main.AgentConfig, 'from_file', return_value=config), \
         patch.object(main, 'validate_model_credentials'), \
         patch.object(main.logging, 'FileHandler'), \
         patch.object(main.logging, 'basicConfig'), \
         patch.object(main, 'WhatsAppClient', return_value=client), \
         patch.object(main, '_run_bootstrap') as bootstrap, \
         patch.object(main, 'HeartbeatLoop') as heartbeat:
        with pytest.raises(SystemExit) as error:
            main.main()
    assert error.value.code == 1
    client.disconnect.assert_called_once()
    bootstrap.assert_not_called()
    heartbeat.assert_not_called()
