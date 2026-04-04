from datetime import datetime
import json

import pandas as pd

from learning.optimizer import ParameterOptimizer
from recommendation.engine import RecommendationEngine
from recommendation.symbol_profile import profile_for_symbol
from strategy.trend_rsi import TrendRSIStrategy


class _Settings:
    def __init__(self, raw):
        self.raw = raw

    def get(self, dotted_path, default=None):
        value = self.raw
        for part in dotted_path.split('.'):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value


class _FakeOptimizer:
    def optimize(self, *args, **kwargs):
        return None


def test_per_symbol_profile_loading() -> None:
    settings = _Settings(
        {
            'recommendation': {
                'min_confidence': 0.6,
                'min_risk_reward': 1.5,
                'symbol_profiles': {
                    'DEFAULT': {'spread_threshold': 25, 'preferred_sessions': ['london']},
                    'XAUUSD': {'name': 'xauusd_macro', 'spread_threshold': 35, 'preferred_sessions': ['new_york']},
                },
            }
        }
    )
    profile = profile_for_symbol('XAUUSD', settings)
    assert profile.name == 'xauusd_macro'
    assert profile.spread_threshold == 35
    assert profile.preferred_sessions == ['new_york']
    assert profile.to_display_dict()['name'] == 'xauusd_macro'


def test_session_filter_blocks_when_policy_block() -> None:
    profile = type('P', (), {'preferred_sessions': ['london'], 'session_outside_policy': 'block', 'session_confidence_multiplier': 0.8})()
    blocked, multiplier, reason = RecommendationEngine._assess_session(profile, 'asian')
    assert blocked is True
    assert multiplier == 0.0
    assert 'outside preferred sessions' in reason


def test_spread_filter_behavior() -> None:
    engine = RecommendationEngine(
        mt5_client=type('M', (), {'get_spread': lambda self, symbol: 28.0})(),
        news_provider=object(),
        news_filter=object(),
        strategies=[],
        settings={},
        optimizer=_FakeOptimizer(),
    )
    profile = type('P', (), {'spread_threshold': 30.0, 'spread_elevated_ratio': 0.75})()
    state, value, reason = engine._assess_spread('GBPJPY', profile)
    assert state == 'elevated'
    assert value == 28.0
    assert reason is None


def test_optimizer_registry_keeps_symbol_separation(tmp_path) -> None:
    rows = 280
    prices = [1.0 + i * 0.0003 for i in range(rows)]
    candles = pd.DataFrame({'open': prices, 'high': [p + 0.0004 for p in prices], 'low': [p - 0.0004 for p in prices], 'close': prices, 'volume': [100] * rows})

    optimizer = ParameterOptimizer(lookahead_bars=5, min_history_bars=100, step=20, report_dir=tmp_path)
    strategy = TrendRSIStrategy()
    optimizer.optimize(strategy, candles, {'ema_fast': [8], 'ema_slow': [30], 'rsi_buy_threshold': [50], 'rsi_sell_threshold': [45]}, symbol='EURUSD', timeframe='M5', fixed_params={'rsi_period': 14})
    optimizer.optimize(strategy, candles, {'ema_fast': [12], 'ema_slow': [40], 'rsi_buy_threshold': [55], 'rsi_sell_threshold': [45]}, symbol='XAUUSD', timeframe='M5', fixed_params={'rsi_period': 14})

    payload = json.loads((tmp_path / 'best_params_by_symbol_timeframe.json').read_text(encoding='utf-8'))
    assert 'EURUSD' in payload
    assert 'XAUUSD' in payload
    assert payload['EURUSD']['M5']['trend_rsi']['best_params'] != payload['XAUUSD']['M5']['trend_rsi']['best_params']


def test_symbol_specific_news_mapping() -> None:
    settings = _Settings({'news': {'symbols_map': {'GBPJPY': ['GBP', 'JPY']}}})
    profile = type('P', (), {'news_sensitivity': {'currencies': ['USD', 'MACRO']}})()
    engine = RecommendationEngine(mt5_client=object(), news_provider=object(), news_filter=object(), strategies=[], settings=settings, optimizer=_FakeOptimizer())
    mapped = profile.news_sensitivity.get('currencies', [])
    assert mapped == ['USD', 'MACRO']


def test_symbol_specific_news_block_windows_override_defaults() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0)
    event = type('Evt', (), {'title': 'CPI', 'currency': 'CAD', 'impact': 'high', 'event_time': now.replace(minute=20)})()
    settings = _Settings({'news': {'symbols_map': {'USDCAD': ['USD', 'CAD']}}})
    profile = type(
        'P',
        (),
        {
            'news_sensitivity': {
                'currencies': ['USD', 'CAD'],
                'block_before_min': 30,
                'reduce_before_min': 60,
                'currency_windows': {'CAD': {'block_before_min': 50}},
            }
        },
    )()
    engine = RecommendationEngine(
        mt5_client=type('M', (), {'now': lambda self: now})(),
        news_provider=type('N', (), {'fetch_events': lambda self, _s, _e: [event]})(),
        news_filter=type('F', (), {'evaluate': lambda self, _n, _ev, _sym: type('D', (), {'decision': 'allow', 'reason': 'clear', 'confidence_multiplier': 1.0})()})(),
        strategies=[],
        settings=settings,
        optimizer=_FakeOptimizer(),
    )
    blocked, status, reason, multiplier, next_event = engine._news_gate('USDCAD', profile)
    assert blocked is True
    assert status == 'blocked'
    assert 'High-impact news' in reason
    assert multiplier == 0.0
    assert next_event is not None


def test_optimizer_writes_symbol_leaderboard_file(tmp_path) -> None:
    rows = 280
    prices = [1.0 + i * 0.0003 for i in range(rows)]
    candles = pd.DataFrame({'open': prices, 'high': [p + 0.0004 for p in prices], 'low': [p - 0.0004 for p in prices], 'close': prices, 'volume': [100] * rows})

    optimizer = ParameterOptimizer(lookahead_bars=5, min_history_bars=100, step=20, report_dir=tmp_path)
    strategy = TrendRSIStrategy()
    optimizer.optimize(strategy, candles, {'ema_fast': [8], 'ema_slow': [30], 'rsi_buy_threshold': [50], 'rsi_sell_threshold': [45]}, symbol='EURUSD', timeframe='M5', fixed_params={'rsi_period': 14})

    leaderboard = json.loads((tmp_path / 'symbol_optimizer_leaderboard.json').read_text(encoding='utf-8'))
    assert leaderboard[0]['symbol'] == 'EURUSD'
    assert leaderboard[0]['timeframe'] == 'M5'
    assert leaderboard[0]['strategy_name'] == 'trend_rsi'
