"""Exercise real provider SDK streaming and tool round trips over mocked HTTP."""
import json
import logging

import httpx
import pytest
from strands import Agent, tool

from utils.config import ModelConfig
from utils.model_factory import create_model
from utils.tool_audit import ToolAudit


def openai_events(tool_call):
    def chunk(delta, finish=None):
        return {'id': 'chatcmpl-test', 'object': 'chat.completion.chunk', 'created': 1,
                'model': 'test', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
    delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'call_test', 'type': 'function',
              'function': {'name': 'record', 'arguments': '{"value":"hello"}'}}]} if tool_call else {'role': 'assistant', 'content': 'OK'}
    events = [chunk(delta), chunk({}, 'tool_calls' if tool_call else 'stop'),
              {'id': 'chatcmpl-test', 'object': 'chat.completion.chunk', 'created': 1,
               'model': 'test', 'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}]
    return ''.join('data: '+json.dumps(event)+'\n\n' for event in events)+'data: [DONE]\n\n'


def anthropic_events(tool_call):
    block = {'type': 'tool_use', 'id': 'call_test', 'name': 'record', 'input': {}} if tool_call else {'type': 'text', 'text': ''}
    delta = {'type': 'input_json_delta', 'partial_json': '{"value":"hello"}'} if tool_call else {'type': 'text_delta', 'text': 'OK'}
    events = [
        {'type': 'message_start', 'message': {'id': 'msg_test', 'type': 'message', 'role': 'assistant',
          'model': 'test', 'content': [], 'stop_reason': None, 'stop_sequence': None,
          'usage': {'input_tokens': 10, 'output_tokens': 0}}},
        {'type': 'content_block_start', 'index': 0, 'content_block': block},
        {'type': 'content_block_delta', 'index': 0, 'delta': delta},
        {'type': 'content_block_stop', 'index': 0},
        {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use' if tool_call else 'end_turn',
          'stop_sequence': None}, 'usage': {'output_tokens': 5}},
        {'type': 'message_stop'},
    ]
    return ''.join('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n' for event in events)


@pytest.mark.parametrize('provider', ['openai', 'anthropic'])
def test_real_sdk_streams_tool_call_and_receives_result(monkeypatch, provider, caplog):
    caplog.set_level(logging.INFO, logger="utils.tool_audit")
    requests = []
    recorded = []

    @tool
    def record(value: str) -> str:
        """Record a value locally for this test."""
        recorded.append(value)
        return 'recorded'

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert len(requests) <= 2, 'Unexpected additional model invocation'
        assert body['model'] == 'test-model' and body['stream'] is True
        if provider == 'openai':
            assert request.url.path == '/v1/chat/completions'
            assert request.headers['authorization'] == 'Bearer synthetic-key'
            content = openai_events(len(requests) == 1)
        else:
            assert request.url.path == '/v1/messages'
            assert request.headers['x-api-key'] == 'synthetic-key'
            content = anthropic_events(len(requests) == 1)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=content)

    transport = httpx.MockTransport(handler)
    if provider == 'openai':
        import openai
        original = openai.AsyncOpenAI
        monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-key')
        monkeypatch.setattr(openai, 'AsyncOpenAI', lambda **kwargs: original(
            **kwargs, http_client=httpx.AsyncClient(transport=transport)))
    else:
        import anthropic
        original = anthropic.AsyncAnthropic
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-key')
        monkeypatch.setattr(anthropic, 'AsyncAnthropic', lambda **kwargs: original(
            **kwargs, http_client=httpx.AsyncClient(transport=transport)))
    base_url = 'https://demo.invalid/v1' if provider == 'openai' else 'https://demo.invalid'
    model = create_model(ModelConfig(provider=provider, model_id='test-model', base_url=base_url))
    agent = Agent(model=model, tools=[record], callback_handler=None, hooks=[ToolAudit()])
    assert str(agent('Record hello, then say OK.')).strip() == 'OK'
    assert recorded == ['hello']
    assert len(requests) == 2
    # The tool's real output must be sent back to the model on the second request.
    assert 'recorded' in json.dumps(requests[1]['messages'])

    assert "tool=record, origin=native, status=success" in caplog.text
