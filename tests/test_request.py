"""Unit tests for GoFigr.request(), the typed-ish HTTP helper external
packages (compute supervisor, internal tooling) use to issue API calls
without registering endpoints in the public client.

These tests mock _request() to isolate the dataclass <-> JSON marshalling
and method dispatch -- no live API, no token plumbing."""
import dataclasses
import unittest
from http import HTTPStatus
from unittest.mock import MagicMock

from requests import Session

from gofigr import GoFigr


@dataclasses.dataclass
class _Status:
    jupyter_up: bool
    cpu_pct: float
    mem_pct: float


@dataclasses.dataclass
class _Ack:
    received_at: str


def _make_gf():
    """GoFigr client with auth bypassed, _request mocked, API key set
    so _request's pre-auth check passes."""
    gf = GoFigr(url="http://localhost", authenticate=False, api_key='k')
    gf._request = MagicMock()
    return gf


def _mock_response(*, status=HTTPStatus.OK, json_data=None, content=b'{}'):
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    resp.json.return_value = json_data
    return resp


class MethodDispatchTest(unittest.TestCase):
    """request() takes a method string and dispatches to the right
    Session.<verb> callable through _request."""

    def test_get_maps_to_session_get(self):
        gf = _make_gf()
        gf._request.return_value = _mock_response(json_data={'ok': True})

        gf.request('GET', 'info/')

        method_callable = gf._request.call_args.args[0]
        self.assertIs(method_callable, Session.get)

    def test_post_maps_to_session_post(self):
        gf = _make_gf()
        gf._request.return_value = _mock_response(json_data={'ok': True})

        gf.request('POST', 'foo/', body={})

        self.assertIs(gf._request.call_args.args[0], Session.post)

    def test_lowercase_method_accepted(self):
        gf = _make_gf()
        gf._request.return_value = _mock_response(json_data={})

        gf.request('post', 'foo/', body={})

        self.assertIs(gf._request.call_args.args[0], Session.post)

    def test_unknown_method_raises(self):
        gf = _make_gf()

        with self.assertRaises(ValueError) as ctx:
            gf.request('TRACE', 'foo/')

        self.assertIn('TRACE', str(ctx.exception))
        gf._request.assert_not_called()


class BodyMarshallingTest(unittest.TestCase):
    def test_dataclass_body_is_asdict_ed(self):
        gf = _make_gf()
        gf._request.return_value = _mock_response(json_data={'received_at': 't'})

        gf.request(
            'POST', 'hb/',
            body=_Status(jupyter_up=True, cpu_pct=12.5, mem_pct=33.0),
        )

        kwargs = gf._request.call_args.kwargs
        self.assertEqual(
            kwargs['json'],
            {'jupyter_up': True, 'cpu_pct': 12.5, 'mem_pct': 33.0},
        )

    def test_dict_body_passes_through_unchanged(self):
        gf = _make_gf()
        gf._request.return_value = _mock_response(json_data={})

        gf.request('POST', 'foo/', body={'x': 1, 'y': [2, 3]})

        self.assertEqual(gf._request.call_args.kwargs['json'], {'x': 1, 'y': [2, 3]})

    def test_get_does_not_send_body(self):
        """request body on GET is ignored (HTTP semantics; some servers
        reject it). Make sure we don't accidentally forward it."""
        gf = _make_gf()
        gf._request.return_value = _mock_response(json_data={})

        gf.request('GET', 'foo/', body={'should': 'not appear'})

        self.assertNotIn('json', gf._request.call_args.kwargs)

    def test_params_passed_through(self):
        gf = _make_gf()
        gf._request.return_value = _mock_response(json_data={})

        gf.request('GET', 'foo/', params={'q': 'hello'})

        self.assertEqual(gf._request.call_args.kwargs['params'], {'q': 'hello'})


class ResponseParsingTest(unittest.TestCase):
    def test_response_type_dataclass_is_instantiated(self):
        gf = _make_gf()
        gf._request.return_value = _mock_response(
            json_data={'received_at': '2026-05-13T14:00:00Z'},
        )

        ack = gf.request('POST', 'hb/', body={}, response_type=_Ack)

        self.assertIsInstance(ack, _Ack)
        self.assertEqual(ack.received_at, '2026-05-13T14:00:00Z')

    def test_no_response_type_returns_raw_dict(self):
        gf = _make_gf()
        gf._request.return_value = _mock_response(json_data={'a': 1, 'b': [2, 3]})

        result = gf.request('GET', 'foo/')

        self.assertEqual(result, {'a': 1, 'b': [2, 3]})

    def test_204_returns_none_even_with_response_type(self):
        """A 204 No Content typical of DELETE has no body to parse;
        request() returns None regardless of response_type."""
        gf = _make_gf()
        gf._request.return_value = _mock_response(
            status=HTTPStatus.NO_CONTENT, content=b'', json_data=None,
        )

        result = gf.request('DELETE', 'foo/123/', response_type=_Ack)

        self.assertIsNone(result)

    def test_empty_body_returns_none(self):
        """Some 200s legitimately come back empty (e.g. side-effect-only
        endpoints). Avoid calling .json() on empty content."""
        gf = _make_gf()
        gf._request.return_value = _mock_response(content=b'', json_data=None)

        self.assertIsNone(gf.request('POST', 'foo/', body={}))


class ExpectedStatusDefaultsTest(unittest.TestCase):
    def test_delete_defaults_to_204(self):
        gf = _make_gf()
        gf._request.return_value = _mock_response(
            status=HTTPStatus.NO_CONTENT, content=b'',
        )

        gf.request('DELETE', 'foo/123/')

        expected = gf._request.call_args.kwargs['expected_status']
        self.assertIn(HTTPStatus.NO_CONTENT, expected)

    def test_non_delete_defaults_to_200(self):
        gf = _make_gf()
        gf._request.return_value = _mock_response(json_data={})

        gf.request('POST', 'foo/', body={})

        expected = gf._request.call_args.kwargs['expected_status']
        self.assertIn(HTTPStatus.OK, expected)

    def test_explicit_expected_status_overrides_default(self):
        """For e.g. a 202 ACCEPTED endpoint."""
        gf = _make_gf()
        gf._request.return_value = _mock_response(
            status=HTTPStatus.ACCEPTED, json_data={},
        )

        gf.request('POST', 'foo/', body={}, expected_status=HTTPStatus.ACCEPTED)

        expected = gf._request.call_args.kwargs['expected_status']
        self.assertEqual(expected, HTTPStatus.ACCEPTED)


if __name__ == '__main__':
    unittest.main()
