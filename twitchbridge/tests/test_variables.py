import asyncio
import copy
from datetime import datetime, timezone
import socket
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_stream_tools as stream_tests
POLICY = stream_tests.POLICY
from test_events import RENDER, VALIDATE, KINDS

V = POLICY["ExtraVariablesMixin"]._extra_variables.__globals__


class VariablePolicyTests(unittest.TestCase):
    def test_countdown_supports_user_format_and_iso(self):
        target = V["countdown_target"](["dec", "25", "2025", "12:00:00", "AM", "EST"])
        self.assertEqual(target.isoformat(), "2025-12-25T00:00:00-05:00")
        iso = V["countdown_target"](["2025-12-25", "00:00:00", "EST"])
        self.assertEqual(target, iso)

    def test_calendar_months_weeks_days_hours_and_past(self):
        start = datetime(2026, 1, 31, tzinfo=timezone.utc)
        end = datetime(2026, 3, 9, 5, tzinfo=timezone.utc)
        self.assertEqual(V["calendar_duration"](start, end), "1 month, 1 week, 2 days, 5 hours")
        self.assertEqual(V["calendar_duration"](end, start), "0 months, 0 weeks, 0 days, 0 hours")

    def test_month_end_and_leap_year(self):
        self.assertEqual(V["calendar_duration"](datetime(2024, 1, 31, tzinfo=timezone.utc),
            datetime(2024, 2, 29, tzinfo=timezone.utc)), "1 month, 0 weeks, 0 days, 0 hours")

    def test_invalid_expressions_are_rejected(self):
        for text in ('choose', 'choose "broken', 'random 100 1', 'random 1 x',
                     'randomreply 10 "A" 9 "B"', 'randomreply 0 "A"', 'randomreply 10',
                     'countdown 2026-02-30 00:00:00 UTC', 'time Not/AZone', 'followage someone'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                V["parse_variable"](text)

    def test_public_url_rejects_private_and_credentialed_destinations(self):
        for url in ('http://example.com', 'https://127.0.0.1', 'https://[::1]', 'https://10.0.0.1',
                    'https://169.254.169.254', 'https://localhost', 'https://server.local',
                    'https://user:pass@example.com', 'https://example.com:444', 'https://example.com/#x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                V["public_url"](url)
        self.assertEqual(V["public_url"]('https://example.com/quote?token=abc&no_id=1'),
                         'https://example.com/quote?token=abc&no_id=1')

    def test_weather_codes_cover_requested_conditions(self):
        for code, text in [(0, 'clear skies'), (61, 'rain'), (95, 'stormy'), (71, 'snow')]:
            self.assertEqual(V["weather_description"](code), text)

    def test_long_reply_lists_fit_template_limit_without_changing_output_limit(self):
        from test_bridge import policy
        template = '{choose ' + ' '.join('"Reply number ' + str(i) + '"' for i in range(50)) + '}'
        self.assertGreater(len(template), 500)
        self.assertEqual(policy.template_text(template), template)
        with self.assertRaises(ValueError):
            policy.template_text('x' * 4001)
        with self.assertRaises(ValueError):
            policy.chat_text('x' * 501)

    def test_every_event_accepts_extended_variables_and_preserves_literal_output(self):
        raw = '{urlfetch https://example.com/quote?token=abc&no_id=1}'
        for kind in KINDS:
            self.assertEqual(VALIDATE(kind, raw), raw)
            self.assertEqual(RENDER(kind, raw + ' {user}', {'user_name': 'Viewer'}, 'channel',
                                   extended={raw: '{user}'}), '{user} Viewer')


class ExtendedVariablesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        stream_tests.StreamToolsTests.setUp(self)

    async def render(self, text, **kwargs):
        return await self.cog._render_shared(1, text, **kwargs)

    async def test_choose_supports_many_quoted_replies(self):
        with patch.object(V["random"], 'choice', return_value='Reply B') as choose:
            self.assertEqual(await self.render('{choose "Reply A" "Reply B" "Reply C"}'), 'Reply B')
            self.assertEqual(choose.call_args.args[0], ['Reply A', 'Reply B', 'Reply C'])

    async def test_weighted_responses_use_inclusive_cumulative_thresholds(self):
        for roll, reply in [(1, 'A'), (10, 'A'), (11, 'B'), (80, 'B'), (81, 'C'), (100, 'C')]:
            with patch.object(V['random'], 'randint', return_value=roll):
                self.assertEqual(await self.render('{randomreply 10 "A" 80 "B" 100 "C"}'), reply)

    async def test_random_number_repeated_expression_is_one_roll(self):
        with patch.object(V['random'], 'randint', return_value=42) as roll:
            self.assertEqual(await self.render('{random 1 100} {random 1 100}'), '42 42')
            roll.assert_called_once_with(1, 100)

    async def test_fetched_text_is_not_interpreted_or_incremented(self):
        self.cog._public_text = AsyncMock(return_value='{counter:deaths} {user}\nA fact')
        text = await self.render('{urlfetch https://example.com/facts} {user}', user='Viewer')
        self.assertEqual(text, '{counter:deaths} {user} A fact Viewer')
        self.assertEqual(self.cfg['response_counters'], {})

    async def test_failed_fetch_has_readable_fallback_without_url_or_token(self):
        self.cog._public_text = AsyncMock(side_effect=ValueError('token=secret'))
        self.assertEqual(await self.render('{urlfetch https://example.com/?token=secret}'), 'URL fetch unavailable')

    async def test_invalid_expression_does_not_increment_counter(self):
        with self.assertRaises(ValueError):
            await self.render('{counter:deaths} {random 100 1}')
        self.assertEqual(self.cfg['response_counters'], {})

    async def test_followage_uses_authorized_broadcaster_and_chatter(self):
        self.cog._role_token = AsyncMock(return_value=('client', {'access_token': 'token'}))
        self.cog._request = AsyncMock(return_value=(200, {'data': [{'followed_at': '2020-01-01T00:00:00Z'}]}))
        text = await self.render('{followage}', twitch_id='viewer')
        self.assertIn('months', text)
        self.cog._role_token.assert_awaited_once_with(1, {'moderator:read:followers'})
        self.assertEqual(self.cog._request.call_args.kwargs['params'], {'broadcaster_id': 'stream', 'user_id': 'viewer'})

    async def test_followage_unlinked_nonfollower_and_missing_auth_are_distinct(self):
        self.assertEqual(await self.render('{followage}'), 'Link your Twitch account to see follow duration')
        self.cog._role_token = AsyncMock(return_value=('client', {'access_token': 'token'}))
        self.cog._request = AsyncMock(return_value=(200, {'data': []}))
        self.assertEqual(await self.render('{followage}', twitch_id='viewer'), 'Not following this channel')
        self.cog._role_token.side_effect = POLICY['BridgeError']('Authorization needed')
        self.assertEqual(await self.render('{followage}', twitch_id='viewer'), 'Follow information unavailable')

    async def test_weather_resolves_location_conditions_temperature_and_caches(self):
        self.cog.bot = types.SimpleNamespace(get_shared_api_tokens=AsyncMock(return_value={}))
        self.cog._public_text = AsyncMock(side_effect=[
            '{"results":[{"name":"Helsinki","latitude":60.17,"longitude":24.94}]}',
            '{"current":{"weather_code":61,"temperature_2m":7.5}}'])
        text = await self.render('{weather Helsinki/Finland}')
        self.assertEqual(text, 'Helsinki: rain, 7.5°C (Open-Meteo)')
        self.assertIn('Helsinki%2C+Finland', self.cog._public_text.call_args_list[0].args[0])
        self.assertEqual(await self.render('{weather Helsinki/Finland}'), text)
        self.assertEqual(self.cog._public_text.await_count, 2)

    async def test_timezone_is_location_aware_and_countdown_past_is_zero(self):
        text = await self.render('{time Europe/Helsinki}')
        self.assertRegex(text, r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} (EET|EEST)')
        self.assertEqual(await self.render('{countdown dec 25 2025 12:00:00 AM EST}'),
                         '0 months, 0 weeks, 0 days, 0 hours')

    async def test_resolver_rejects_private_address_in_mixed_dns_answers(self):
        loop = asyncio.get_running_loop()
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443)),
                   (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        with patch.object(loop, 'getaddrinfo', AsyncMock(return_value=answers)):
            with self.assertRaises(OSError):
                await V['PublicResolver']().resolve('example.com', 443)

    async def test_too_many_different_expressions_are_rejected_before_fetch(self):
        self.cog._public_text = AsyncMock()
        with self.assertRaises(ValueError):
            await self.render(' '.join('{urlfetch https://example.com/' + str(n) + '}' for n in range(9)))
        self.cog._public_text.assert_not_awaited()


class AsyncContext:
    def __init__(self, value):
        self.value = value
    async def __aenter__(self):
        return self.value
    async def __aexit__(self, *args):
        pass


class PublicHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, chunks, status=200, content_type='text/plain'):
        from unittest.mock import Mock
        async def stream(size):
            for chunk in chunks:
                yield chunk
        response = types.SimpleNamespace(status=status, content_type=content_type,
            content=types.SimpleNamespace(iter_chunked=stream))
        self.get = Mock(return_value=AsyncContext(response))
        session = types.SimpleNamespace(get=self.get)
        self.session_factory = Mock(return_value=AsyncContext(session))
        self.connector = Mock()
        with patch.object(V['aiohttp'], 'ClientSession', self.session_factory, create=True), \
             patch.object(V['aiohttp'], 'TCPConnector', self.connector, create=True), \
             patch.object(V['aiohttp'], 'ClientTimeout', Mock(), create=True), \
             patch.object(V['aiohttp'], 'DummyCookieJar', Mock(), create=True):
            return await V['public_get']('https://example.com/facts')

    async def test_fetch_uses_no_credentials_redirects_cookies_or_proxies(self):
        self.assertEqual(await self.fetch([b'Fact ', b'number one']), 'Fact number one')
        self.assertFalse(self.get.call_args.kwargs['allow_redirects'])
        self.assertNotIn('Authorization', self.get.call_args.kwargs['headers'])
        self.assertFalse(self.session_factory.call_args.kwargs['trust_env'])
        self.assertIsInstance(self.connector.call_args.kwargs['resolver'], V['PublicResolver'])

    async def test_fetch_rejects_redirect_and_html(self):
        for status, content_type in [(302, 'text/plain'), (200, 'text/html')]:
            with self.assertRaises(ValueError):
                await self.fetch([b'unexpected'], status=status, content_type=content_type)

    async def test_fetch_enforces_streamed_body_limit(self):
        with self.assertRaises(ValueError):
            await self.fetch([b'x' * 4096] * 17)
