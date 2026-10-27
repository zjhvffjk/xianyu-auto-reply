"""账号身份展示与缓存的行为测试，不使用真实账号凭据。"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from common.utils.account_name import resolve_member_name, resolve_nickname
from common.services.xianyu_user_profile import needs_refresh, store_profile


class AccountIdentityTests(unittest.TestCase):
    def test_member_name_decodes_cookie_and_does_not_guess_from_nickname(self):
        self.assertEqual(resolve_member_name('tracknick=%E5%BA%97%E4%B8%BB; unb=123'), '店主')
        self.assertEqual(resolve_member_name('tracknick=x***8', '昵称'), '')
        self.assertEqual(resolve_member_name('', '昵称'), '')

    def test_nickname_rejects_masked_value_and_duplicate(self):
        self.assertEqual(resolve_nickname('小店', 'xy_member'), '小店')
        self.assertEqual(resolve_nickname('x***8', 'xy_member'), '')
        self.assertEqual(resolve_nickname('xy_member', 'xy_member'), '')

    def test_failed_refresh_preserves_profile_and_other_account_settings(self):
        original = {'ai_reply_settings': {'enabled': True}, 'profile': {
            'nickname': '我的店', 'avatar': 'avatar.png', 'refreshed_at': 1}}
        account = SimpleNamespace(metadata_json=original)
        with patch('common.services.xianyu_user_profile.time.time', return_value=10000):
            store_profile(account, None)
        self.assertEqual(account.metadata_json['profile']['nickname'], '我的店')
        self.assertEqual(account.metadata_json['ai_reply_settings'], {'enabled': True})
        self.assertNotIn('failed_at', original['profile'])
        self.assertFalse(needs_refresh(account, now=10001))


if __name__ == '__main__':
    unittest.main()
