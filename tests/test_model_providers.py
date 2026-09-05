"""Provider configuration, wiring and SDK behavior without real API calls."""
from unittest.mock import MagicMock, patch

import pytest

from utils.config import AgentConfig, ModelConfig
from utils.model_factory import create_model
from utils.agent_manager import AgentManager


@pytest.mark.parametrize('provider,model', [('openai', 'gpt-4.1-mini'), ('anthropic', 'test-claude')])
def test_yaml_and_local_env(tmp_path, monkeypatch, provider, model):
    variable = 'OPENAI_API_KEY' if provider == 'openai' else 'ANTHROPIC_API_KEY'
    monkeypatch.delenv(variable, raising=False)
    path = tmp_path / 'config.yaml'
    path.write_text(f'admin_phone: "123456789"\nmodel:\n  provider: {provider}\n  model_id: {model}\n')
    (tmp_path / '.env').write_text(f'{variable}=synthetic-key\n')
    try:
        config = AgentConfig.from_file(str(path))
        assert config.model.provider == provider
        assert config.model.model_id == model
        with patch('strands.models.BedrockModel', side_effect=AssertionError('Unexpected AWS')):
            adapter = create_model(config.model)
        assert adapter.get_config()['model_id'] == model
        monkeypatch.setenv(variable, 'existing-environment-key')
        AgentConfig.from_file(str(path))
        import os
        assert os.environ[variable] == 'existing-environment-key'
    finally:
        monkeypatch.delenv(variable, raising=False)


@pytest.mark.parametrize('raw', [
    {'provider': 'other'}, {'provider': []}, {'provider': 'openai'},
    {'provider': 'anthropic', 'model_id': ''}, {'max_tokens': 0},
    {'max_tokens': True}, {'base_url': 'https://example.com'},
    {'provider': 'openai', 'model_id': 'test', 'base_url': 'ftp://example.com'},
    {'provider': 'openai', 'model_id': 'test', 'base_url': 'https://user:secret@example.com'},
    {'api_key': 'must-not-be-in-config'}, 'openai',
])
def test_invalid_model_settings(raw):
    with pytest.raises(ValueError):
        ModelConfig.from_dict(raw)


@pytest.mark.parametrize('provider,variable', [('openai', 'OPENAI_API_KEY'), ('anthropic', 'ANTHROPIC_API_KEY')])
def test_missing_key_is_actionable(monkeypatch, provider, variable):
    monkeypatch.delenv(variable, raising=False)
    with pytest.raises(ValueError, match=variable):
        create_model(ModelConfig(provider=provider, model_id='test'))


def test_legacy_config_stays_bedrock(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('admin_phone: "123456789"\n')
    config = AgentConfig.from_file(str(path))
    assert config.model.provider == 'bedrock'
    with patch('strands.models.BedrockModel') as constructor:
        create_model(config.model)
    assert 'model_id' not in constructor.call_args.kwargs


@pytest.mark.parametrize('provider,module,class_name,variable', [
    ('openai', 'strands.models.openai', 'OpenAIModel', 'OPENAI_API_KEY'),
    ('anthropic', 'strands.models.anthropic', 'AnthropicModel', 'ANTHROPIC_API_KEY'),
])
def test_custom_endpoint_forwarded(monkeypatch, provider, module, class_name, variable):
    monkeypatch.setenv(variable, 'synthetic-key')
    config = ModelConfig(provider=provider, model_id='test', base_url='https://example.com/v1')
    with patch(f'{module}.{class_name}') as constructor:
        create_model(config)
    assert constructor.call_args.kwargs['client_args']['base_url'] == config.base_url
    assert constructor.call_args.kwargs['client_args']['api_key'] == 'synthetic-key'


@pytest.mark.parametrize('bootstrap', [False, True])
def test_same_provider_factory_used_for_normal_and_bootstrap(bootstrap):
    config = ModelConfig(provider='openai', model_id='test')
    manager = AgentManager('unused', MagicMock(), MagicMock(), MagicMock(), model_config=config)
    manager.tool_manager.get_tools.return_value = []
    with patch('utils.agent_manager.create_model') as factory, \
         patch('utils.agent_manager.Agent') as agent, \
         patch('utils.agent_manager.FileSessionManager'), \
         patch('utils.agent_manager.make_reply_tool', return_value=MagicMock()):
        if bootstrap:
            manager.create_bootstrap('123456789', 'Hello')
        else:
            manager.get_or_create('123456789')
    factory.assert_called_once_with(config)
    assert agent.call_args.kwargs['model'] is factory.return_value


def test_missing_key_blocks_startup_before_whatsapp(monkeypatch):
    import main
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    config = AgentConfig(admin_phone='123456789', model=ModelConfig(provider='openai', model_id='test'))
    with patch.object(main.AgentConfig, 'from_file', return_value=config), \
         patch.object(main, 'WhatsAppClient') as whatsapp:
        with pytest.raises(ValueError, match='OPENAI_API_KEY'):
            main.main()
    whatsapp.assert_not_called()
