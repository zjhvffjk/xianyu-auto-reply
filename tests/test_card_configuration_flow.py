import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
sys.path.insert(0, '/app/backend-web')
from app.services.card_service import CardService
from common.services.card_matcher import CardMatcher


def result_ids(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


class CardConfigurationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_card_does_not_delete_existing_configuration(self):
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[result_ids(['item-1']), result_ids([])])
        session.commit = AsyncMock()
        with patch.object(CardMatcher, 'update_item_card_relations', new=AsyncMock()) as write:
            with self.assertRaises(ValueError):
                await CardService(session).update_item_card_relations('item-1', 7, [{'card_id': 11, 'source': 'own'}], owner_id=7)
            write.assert_not_awaited()
            session.commit.assert_not_awaited()

    async def test_foreign_item_cannot_be_reconfigured(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=result_ids([]))
        with patch.object(CardMatcher, 'update_item_card_relations', new=AsyncMock()) as write:
            with self.assertRaises(ValueError):
                await CardService(session).update_item_card_relations('foreign-item', 7, [], owner_id=7)
            write.assert_not_awaited()

    async def test_duplicate_selection_is_saved_once(self):
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[result_ids(['item-1']), result_ids([11])])
        session.commit = AsyncMock()
        card = {'card_id': 11, 'source': 'own'}
        with patch.object(CardMatcher, 'update_item_card_relations', new=AsyncMock(return_value={'added': 1, 'removed': 0})) as write:
            await CardService(session).update_item_card_relations('item-1', 7, [card, card], owner_id=7)
            self.assertEqual(len(write.call_args.kwargs['card_relations']), 1)

    async def test_clear_handles_legacy_field_and_keeps_user_scope(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=MagicMock(rowcount=1))
        session.flush = AsyncMock()
        await CardMatcher(session).update_item_card_relations('item-1', 7, [], owner_id=7)
        statements = [(str(call.args[0]), call.args[1]) for call in session.execute.call_args_list]
        self.assertTrue(any('UPDATE xy_cards' in sql and 'item_id = NULL' in sql for sql, _ in statements))
        for sql, params in statements:
            self.assertIn('user_id', sql)
            self.assertEqual(params['owner_id'], 7)

    async def test_storage_error_rolls_back_instead_of_committing_partial_configuration(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=result_ids(['item-1']))
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        with patch.object(CardMatcher, 'update_item_card_relations', new=AsyncMock(side_effect=RuntimeError('write failed'))):
            with self.assertRaises(RuntimeError):
                await CardService(session).update_item_card_relations('item-1', 7, [], owner_id=7)
        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()

    async def test_management_read_scopes_both_relations_and_legacy_cards(self):
        session = MagicMock()
        result = result_ids([])
        result.all.return_value = []
        session.execute = AsyncMock(return_value=result)
        await CardService(session).get_cards_by_item_id(7, 'item-1')
        for call in session.execute.call_args_list:
            compiled = call.args[0].compile()
            self.assertIn(7, compiled.params.values())
            # 管理配置必须保留已停用卡券的关联，不能按 enabled 过滤掉。
            self.assertNotIn('enabled =', str(compiled))


if __name__ == '__main__':
    unittest.main()
