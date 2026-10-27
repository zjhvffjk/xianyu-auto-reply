import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, '/app/backend-web')
from app.services.description_polish_service import parse_polished_copy, polish_description, PolishResultError
from app.api.routes import ai_listing as routes
from common.services.ai_text_client import AiCallError
from common.services.ai_text_client import chat_completion


class PolishParsingTests(unittest.TestCase):
    def test_valid_result_and_code_fence(self):
        content = json.dumps({'title': ' 测试标题 ', 'description': ' 原价20元，邮费6元。\n售出不退。 '})
        self.assertEqual(parse_polished_copy('```json\n' + content + '\n```'), {'title': '测试标题', 'description': '原价20元，邮费6元。\n售出不退。'})

    def test_invalid_empty_and_overlength_body_are_not_used(self):
        cases = ['not-json', '[]', '{}']
        for title in [None, 5, '', ' ']:
            cases.append(json.dumps({'title': title, 'description': '正文'}))
        for description in [None, 5, '', ' ', '测' * 1501, '😀' * 751]:
            cases.append(json.dumps({'title': '标题', 'description': description}))
        for content in cases:
            with self.subTest(content=content[:30]), self.assertRaises(PolishResultError):
                parse_polished_copy(content)
        result = parse_polished_copy(json.dumps({'title': '测' * 30, 'description': '测' * 1500}))
        self.assertEqual(len(result['title']), 30)
        self.assertEqual(len(result['description']), 1500)

    def test_long_or_multiline_title_is_preserved_for_manual_preview_correction(self):
        for title in ['【标价包邮直出】IVE李瑞小卡 love dive 爱河ny2.0瑞', '测' * 31, '😀' * 16, '标题\n换行']:
            with self.subTest(title=title):
                result = parse_polished_copy(json.dumps({'title': title, 'description': '完整正文，不能因标题过长丢弃。'}))
                self.assertEqual(result['title'], title)
                self.assertEqual(result['description'], '完整正文，不能因标题过长丢弃。')


class PolishCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_ark_uses_official_non_thinking_parameter(self):
        for base_url, expected in [('https://ark.cn-beijing.volces.com/api/v3', 'thinking'), ('https://example.com/v1', 'enable_thinking')]:
            with self.subTest(base_url=base_url), patch('common.services.ai_text_client.request_json_with_retries', new=AsyncMock(return_value={'choices': [{'message': {'content': '成功'}}]})) as request:
                await chat_completion(base_url=base_url, api_key='fake-key', model='test', messages=[{'role': 'user', 'content': '测试'}])
                payload = request.call_args.args[3]
                self.assertEqual(payload[expected], {'type': 'disabled'} if expected == 'thinking' else False)
                self.assertNotIn('enable_thinking' if expected == 'thinking' else 'thinking', payload)

    async def test_reuses_config_but_not_listing_generation_template(self):
        config = SimpleNamespace(text_base_url='https://example.com/v1', text_api_key='fake-test-key', text_model='test-model', text_temperature=0, text_max_tokens=2048, prompt_template='生成50条虚构商品')
        source = '标价20元，邮费6元，不退换。'
        with patch('app.services.description_polish_service.chat_completion', new=AsyncMock(return_value=json.dumps({'title': '新标题', 'description': source}))) as client:
            result = await polish_description(config, '测试标题', source)
        self.assertEqual(result, {'title': '新标题', 'description': source})
        kwargs = client.call_args.kwargs
        self.assertEqual(kwargs['temperature'], 0)
        self.assertEqual(kwargs['model'], 'test-model')
        self.assertEqual(json.loads(kwargs['messages'][1]['content']), {'title': '测试标题', 'description': source, 'protected_clauses': ['邮费6元', '不退换']})
        self.assertNotIn(config.prompt_template, str(kwargs['messages']))

    async def test_transaction_terms_cannot_be_reinterpreted_or_removed(self):
        config = SimpleNamespace(text_base_url='https://example.com/v1', text_api_key='fake-test-key', text_model='test', text_temperature=0.4, text_max_tokens=2048)
        original = '拍下自动发码。不出货支持全额退款，虚拟卡密发货后不接受退换款。运费6元。'
        with patch('app.services.description_polish_service.chat_completion', new=AsyncMock(return_value=json.dumps({'title': '新标题', 'description': '兑换不到账支持退款，不接受退换款，包邮。'}))):
            with self.assertRaisesRegex(PolishResultError, '关键交易条件'):
                await polish_description(config, '测试', original)
        reordered = '运费6元。拍下自动发码。虚拟卡密发货后不接受退换款，不出货支持全额退款。'
        with patch('app.services.description_polish_service.chat_completion', new=AsyncMock(return_value=json.dumps({'title': '新标题', 'description': reordered}))):
            self.assertEqual(await polish_description(config, '测试', original), {'title': '新标题', 'description': reordered})

    async def test_other_users_config_is_rejected_without_model_call(self):
        service = MagicMock()
        service.get = AsyncMock(return_value=None)
        with patch.object(routes, 'AiListingConfigService', return_value=service), patch('app.services.description_polish_service.polish_description', new=AsyncMock()) as call:
            response = await routes.preview_polished_description(routes.DescriptionPolishRequest(config_id=9, description='原文'), SimpleNamespace(id=7), MagicMock())
        self.assertFalse(response.success)
        service.get.assert_awaited_once_with(9, 7)
        call.assert_not_awaited()

    async def test_title_only_transaction_condition_is_not_lost_when_moved_to_body(self):
        config = SimpleNamespace(text_base_url='https://example.com/v1', text_api_key='fake-test-key', text_model='test', text_temperature=0.4, text_max_tokens=2048)
        title = '测试商品，不支持退货'
        with patch('app.services.description_polish_service.chat_completion', new=AsyncMock(return_value=json.dumps({'title': '测试商品', 'description': '完整内容，不支持退货。'}))):
            result = await polish_description(config, title, '完整内容')
        self.assertIn('不支持退货', result['description'])
        with patch('app.services.description_polish_service.chat_completion', new=AsyncMock(return_value=json.dumps({'title': '测试商品', 'description': '完整内容。'}))):
            with self.assertRaises(PolishResultError):
                await polish_description(config, title, '完整内容')

    async def test_empty_input_does_not_load_config_or_call_model(self):
        with patch.object(routes, 'AiListingConfigService') as service:
            response = await routes.preview_polished_description(routes.DescriptionPolishRequest(config_id=9, description=' '), SimpleNamespace(id=7), MagicMock())
        self.assertFalse(response.success)
        service.assert_not_called()

    async def test_preview_does_not_save_material_or_commit(self):
        session = MagicMock()
        session.commit = AsyncMock()
        service = MagicMock(); service.get = AsyncMock(return_value=SimpleNamespace(id=9))
        with patch.object(routes, 'AiListingConfigService', return_value=service), patch('app.services.description_polish_service.polish_description', new=AsyncMock(return_value={'title': '新标题', 'description': '预览'})):
            response = await routes.preview_polished_description(routes.DescriptionPolishRequest(config_id=9, description='原文'), SimpleNamespace(id=7), session)
        self.assertTrue(response.success)
        self.assertEqual(response.data, {'title': '新标题', 'description': '预览'})
        session.add.assert_not_called()
        session.commit.assert_not_awaited()

    async def test_provider_error_does_not_expose_secret_or_raw_response(self):
        service = MagicMock(); service.get = AsyncMock(return_value=SimpleNamespace(id=9))
        with patch.object(routes, 'AiListingConfigService', return_value=service), patch('app.services.description_polish_service.polish_description', new=AsyncMock(side_effect=AiCallError('private-url-and-key'))):
            response = await routes.preview_polished_description(routes.DescriptionPolishRequest(config_id=9, description='原文'), SimpleNamespace(id=7), MagicMock())
        self.assertFalse(response.success)
        self.assertNotIn('private-url-and-key', response.message)

    async def test_timeout_keeps_original_and_request_limit_is_1500(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            routes.DescriptionPolishRequest(config_id=9, description='测' * 1501)
        service = MagicMock(); service.get = AsyncMock(return_value=SimpleNamespace(id=9))
        with patch.object(routes, 'AiListingConfigService', return_value=service), patch('app.services.description_polish_service.polish_description', new=AsyncMock(side_effect=TimeoutError)):
            response = await routes.preview_polished_description(routes.DescriptionPolishRequest(config_id=9, description='原文'), SimpleNamespace(id=7), MagicMock())
        self.assertFalse(response.success)
        self.assertIn('超时', response.message)


if __name__ == '__main__':
    unittest.main()
