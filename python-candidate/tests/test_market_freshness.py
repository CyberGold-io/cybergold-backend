"""Downstream cache lifetime never restarts the market acquisition clock."""
import unittest

from cybergold_candidate.market import response_headers


class MarketFreshness(unittest.TestCase):
    def test_near_expiry_acquisition_and_expired_fresh_flag(self):
        payload = {'fetchedAt': '2026-10-04T00:00:00.000Z'}
        for feed, end in (('gold', '00:29:59'), ('fx', '00:04:59')):
            self.assertEqual(response_headers(feed, True, payload, f'2026-10-04T{end}.000Z')['cache-control'],
                             f's-maxage=1, stale-while-revalidate={1800 if feed == "gold" else 300}')
        self.assertEqual(response_headers('fx', True, payload, '2026-10-04T00:05:00.000Z'),
                         {'cache-control': 'no-store'})

    def test_fractional_age_is_rounded_down_and_stale_fallback_is_never_cached(self):
        payload = {'fetchedAt': '2026-10-04T00:00:00.000Z'}
        self.assertEqual(response_headers('fx', True, payload, '2026-10-04T00:04:58.500Z')['cache-control'],
                         's-maxage=1, stale-while-revalidate=300')
        self.assertEqual(response_headers('gold', False, payload, '2026-10-04T00:00:00.000Z'),
                         {'cache-control': 'no-store'})

    def test_existing_proleptic_timestamp_domain_is_not_narrowed(self):
        payload = {'fetchedAt': '0000-01-01T00:00:00.000Z'}
        self.assertEqual(response_headers('fx', True, payload, '2026-10-04T00:00:00.000Z'),
                         {'cache-control': 'no-store'})


if __name__ == '__main__':
    unittest.main()
