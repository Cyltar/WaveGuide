"""Offline HTTP tests for permanent authenticated account deletion."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

APPLICATION_PATH = Path(__file__).resolve().parent.parent / 'app.py'
AUTH_PATH = APPLICATION_PATH.parent / 'auth.py'


class AccountDeletionTests(unittest.TestCase):
    def setUp(self):
        """
        Run the real endpoint and token validator with an offline Supabase admin client.
        """
        auth_tree = ast.parse(AUTH_PATH.read_text())
        auth_tree.body = [node for node in auth_tree.body if not (
            isinstance(node, ast.ImportFrom) and node.module == 'app.supabase_client')]
        self.admin = Mock()
        self.admin.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(id='authenticated-user'))
        namespace = {'supabase': self.admin}
        exec(compile(auth_tree, str(AUTH_PATH), 'exec'), namespace)
        tree = ast.parse(APPLICATION_PATH.read_text())
        endpoint = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'delete_account')
        self.app = FastAPI()
        namespace.update(app=self.app, Depends=Depends, HTTPException=HTTPException, account_admin=self.admin)
        exec(compile(ast.Module(body=[endpoint], type_ignores=[]), str(APPLICATION_PATH), 'exec'), namespace)
        self.client = TestClient(self.app)

    def test_authenticated_deletion_uses_verified_id_and_hard_delete(self):
        """
        Delete only the verified identity, ignoring any caller-supplied alternative user ID.
        """
        response = self.client.request('DELETE', '/account?user_id=someone-else',
                                       headers={'Authorization': 'Bearer valid-token'}, json={'user_id': 'someone-else'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'deleted': True})
        self.admin.auth.get_user.assert_called_once_with('valid-token')
        self.admin.auth.admin.delete_user.assert_called_once_with('authenticated-user', should_soft_delete=False)
        self.admin.table.assert_not_called()
        self.admin.rpc.assert_not_called()

    def test_missing_malformed_and_invalid_auth_cannot_delete(self):
        """
        Reject absent, malformed and invalid credentials without reaching the admin API.
        """
        for headers in ({}, {'Authorization': 'Basic anything'}, {'Authorization': 'Bearer '}):
            self.assertEqual(self.client.delete('/account', headers=headers).status_code, 401)
        self.admin.auth.get_user.side_effect = RuntimeError('invalid token')
        self.assertEqual(self.client.delete('/account', headers={'Authorization': 'Bearer bad'}).status_code, 401)
        self.admin.auth.admin.delete_user.assert_not_called()

    def test_admin_failure_is_safe_and_does_not_report_success(self):
        """
        Hide internal admin errors and preserve the failure response for frontend recovery.
        """
        self.admin.auth.admin.delete_user.side_effect = RuntimeError('private admin error or service key')
        response = self.client.delete('/account', headers={'Authorization': 'Bearer valid-token'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail']['code'], 'ACCOUNT_DELETION_FAILED')
        self.assertNotIn('private', response.text)
        self.assertNotIn('deleted', response.json())
        self.admin.table.assert_not_called()


if __name__ == '__main__':
    unittest.main()
