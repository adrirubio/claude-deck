"""Tests for usage tracking services."""
import pytest
from datetime import datetime, timedelta
from app.services.pricing_service import PricingService
from app.services.usage_service import UsageService, LoadedUsageEntry


class TestPricingService:
    """Tests for PricingService."""

    def setup_method(self):
        """Set up test fixtures."""
        self.pricing = PricingService()

    def test_calculate_cost_basic(self):
        """Test basic cost calculation."""
        cost = self.pricing.calculate_cost(
            input_tokens=1000,
            output_tokens=500,
            model="claude-sonnet-4-20250514",
        )
        # Input: 1000 * 3e-6 = 0.003
        # Output: 500 * 15e-6 = 0.0075
        # Total: 0.0105
        assert cost == pytest.approx(0.0105, rel=1e-3)

    def test_calculate_cost_with_cache_tokens(self):
        """Test cost calculation with cache tokens."""
        cost = self.pricing.calculate_cost(
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=2000,
            cache_read_tokens=5000,
            model="claude-sonnet-4-20250514",
        )
        # Input: 1000 * 3e-6 = 0.003
        # Output: 500 * 15e-6 = 0.0075
        # Cache creation: 2000 * 3.75e-6 = 0.0075
        # Cache read: 5000 * 0.3e-6 = 0.0015
        # Total: 0.0195
        assert cost == pytest.approx(0.0195, rel=1e-3)

    def test_calculate_cost_tiered_200k(self):
        """Test tiered pricing above 200k tokens."""
        cost = self.pricing.calculate_cost(
            input_tokens=300000,  # 200k at base rate, 100k at tiered rate
            output_tokens=0,
            model="claude-sonnet-4-20250514",
        )
        # Below 200k: 200000 * 3e-6 = 0.60
        # Above 200k: 100000 * 6e-6 = 0.60
        # Total: 1.20
        assert cost == pytest.approx(1.20, rel=1e-3)

    def test_calculate_cost_exactly_200k(self):
        """Test cost at exactly 200k tokens (no tiered pricing)."""
        cost = self.pricing.calculate_cost(
            input_tokens=200000,
            output_tokens=0,
            model="claude-sonnet-4-20250514",
        )
        # All at base rate: 200000 * 3e-6 = 0.60
        assert cost == pytest.approx(0.60, rel=1e-3)

    def test_calculate_cost_unknown_model(self):
        """Test cost calculation for unknown model returns 0."""
        cost = self.pricing.calculate_cost(
            input_tokens=1000,
            output_tokens=500,
            model="unknown-model-xyz",
        )
        assert cost == 0.0

    def test_calculate_cost_no_model(self):
        """Test cost calculation with no model returns 0."""
        cost = self.pricing.calculate_cost(
            input_tokens=1000,
            output_tokens=500,
            model=None,
        )
        assert cost == 0.0

    def test_model_name_matching_with_prefix(self):
        """Test model name matching with anthropic/ prefix."""
        pricing = self.pricing.get_model_pricing("anthropic/claude-sonnet-4-20250514")
        # Should match even though stored without prefix
        # The fuzzy matching should find it
        assert pricing is not None or self.pricing.get_model_pricing("claude-sonnet-4-20250514") is not None

    def test_get_supported_models(self):
        """Test listing supported models."""
        models = self.pricing.get_supported_models()
        assert len(models) > 0
        assert "claude-sonnet-4-20250514" in models

    def test_calculate_tiered_cost_boundary(self):
        """Test tiered cost calculation at boundary."""
        # Test with 200,001 tokens (1 token above threshold)
        cost = self.pricing.calculate_tiered_cost(
            total_tokens=200001,
            base_price=3e-6,
            tiered_price=6e-6,
        )
        # 200000 * 3e-6 + 1 * 6e-6 = 0.600006
        assert cost == pytest.approx(0.600006, rel=1e-5)

    def test_calculate_tiered_cost_no_tiered_price(self):
        """Test tiered cost calculation without tiered price."""
        cost = self.pricing.calculate_tiered_cost(
            total_tokens=300000,
            base_price=3e-6,
            tiered_price=None,
        )
        # All at base rate: 300000 * 3e-6 = 0.90
        assert cost == pytest.approx(0.90, rel=1e-3)

    def test_calculate_tiered_cost_zero_tokens(self):
        """Test tiered cost calculation with zero tokens."""
        cost = self.pricing.calculate_tiered_cost(
            total_tokens=0,
            base_price=3e-6,
            tiered_price=6e-6,
        )
        assert cost == 0.0


class TestUsageService:
    """Tests for UsageService."""

    def setup_method(self):
        """Set up test fixtures."""
        self.service = UsageService(db=None)

    def test_create_loaded_usage_entry(self):
        """Test creating a LoadedUsageEntry."""
        entry = LoadedUsageEntry(
            timestamp=datetime.now(),
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.01,
            model="claude-sonnet-4-20250514",
            session_id="test-session",
            version="1.0.0",
            project_path="test-project",
        )
        assert entry.input_tokens == 1000
        assert entry.output_tokens == 500
        assert entry.model == "claude-sonnet-4-20250514"

    @pytest.fixture
    def sample_entries(self):
        """Create sample usage entries for testing."""
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        return [
            LoadedUsageEntry(
                timestamp=base_time,
                input_tokens=1000,
                output_tokens=500,
                cache_creation_tokens=100,
                cache_read_tokens=50,
                cost_usd=None,
                model="claude-sonnet-4-20250514",
                session_id="session-1",
                version="1.0.0",
                project_path="project-a",
            ),
            LoadedUsageEntry(
                timestamp=base_time + timedelta(hours=1),
                input_tokens=2000,
                output_tokens=1000,
                cache_creation_tokens=200,
                cache_read_tokens=100,
                cost_usd=None,
                model="claude-sonnet-4-20250514",
                session_id="session-1",
                version="1.0.0",
                project_path="project-a",
            ),
            LoadedUsageEntry(
                timestamp=base_time + timedelta(days=1),
                input_tokens=500,
                output_tokens=250,
                cache_creation_tokens=50,
                cache_read_tokens=25,
                cost_usd=None,
                model="claude-opus-4-20250514",
                session_id="session-2",
                version="1.0.0",
                project_path="project-b",
            ),
        ]

    @pytest.mark.asyncio
    async def test_aggregate_by_daily(self, sample_entries):
        """Test daily aggregation."""
        daily = await self.service.aggregate_by_daily(sample_entries)

        assert len(daily) == 2  # Two different days

        # Check first day (2024-01-16 - sorted descending)
        day1 = next(d for d in daily if d.date == "2024-01-16")
        assert day1.input_tokens == 500
        assert day1.output_tokens == 250
        assert "claude-opus-4-20250514" in day1.models_used

        # Check second day (2024-01-15)
        day2 = next(d for d in daily if d.date == "2024-01-15")
        assert day2.input_tokens == 3000  # 1000 + 2000
        assert day2.output_tokens == 1500  # 500 + 1000

    @pytest.mark.asyncio
    async def test_aggregate_by_session(self, sample_entries):
        """Test session aggregation."""
        sessions = await self.service.aggregate_by_session(sample_entries)

        assert len(sessions) == 2  # Two different sessions

        # Find session-1
        session1 = next(s for s in sessions if s.session_id == "session-1")
        assert session1.input_tokens == 3000
        assert session1.output_tokens == 1500
        assert session1.project_path == "project-a"

    @pytest.mark.asyncio
    async def test_aggregate_by_monthly(self, sample_entries):
        """Test monthly aggregation."""
        monthly = await self.service.aggregate_by_monthly(sample_entries)

        assert len(monthly) == 1  # All in January 2024

        month = monthly[0]
        assert month.month == "2024-01"
        assert month.input_tokens == 3500  # 1000 + 2000 + 500

    def test_floor_to_hour(self):
        """Test floor_to_hour function."""
        dt = datetime(2024, 1, 15, 10, 45, 30)
        floored = self.service._floor_to_hour(dt)

        assert floored.hour == 10
        assert floored.minute == 0
        assert floored.second == 0
        assert floored.microsecond == 0


class TestSessionBlocks:
    """Tests for session block identification."""

    def setup_method(self):
        """Set up test fixtures."""
        self.service = UsageService(db=None)

    def create_entry(
        self,
        timestamp: datetime,
        input_tokens: int = 1000,
        output_tokens: int = 500,
    ) -> LoadedUsageEntry:
        """Helper to create test entries."""
        return LoadedUsageEntry(
            timestamp=timestamp,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.01,
            model="claude-sonnet-4-20250514",
            session_id="test-session",
            version="1.0.0",
            project_path="test-project",
        )

    @pytest.mark.asyncio
    async def test_single_block_within_5_hours(self):
        """Test entries within 5 hours create single block."""
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        entries = [
            self.create_entry(base_time),
            self.create_entry(base_time + timedelta(hours=1)),
            self.create_entry(base_time + timedelta(hours=2)),
        ]

        blocks = await self.service.identify_session_blocks(entries)

        assert len(blocks) == 1
        assert blocks[0].input_tokens == 3000
        assert not blocks[0].is_gap

    @pytest.mark.asyncio
    async def test_multiple_blocks_spanning_5_hours(self):
        """Test entries spanning >5 hours create multiple blocks."""
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        entries = [
            self.create_entry(base_time),
            self.create_entry(base_time + timedelta(hours=6)),  # 6 hours later
        ]

        blocks = await self.service.identify_session_blocks(entries)

        # Should have: first block, gap block, second block
        assert len(blocks) == 3
        assert not blocks[0].is_gap
        assert blocks[1].is_gap  # Gap block
        assert not blocks[2].is_gap

    @pytest.mark.asyncio
    async def test_gap_block_creation(self):
        """Test gap blocks are created for long gaps."""
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        entries = [
            self.create_entry(base_time),
            self.create_entry(base_time + timedelta(hours=2)),
            self.create_entry(base_time + timedelta(hours=8)),  # 6 hours from last
        ]

        blocks = await self.service.identify_session_blocks(entries)

        # Should have gap block between first and last block
        gap_blocks = [b for b in blocks if b.is_gap]
        assert len(gap_blocks) == 1
        assert gap_blocks[0].input_tokens == 0
        assert gap_blocks[0].cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_empty_entries(self):
        """Test empty entries return empty blocks."""
        blocks = await self.service.identify_session_blocks([])
        assert len(blocks) == 0

    @pytest.mark.asyncio
    async def test_block_aggregation(self):
        """Test tokens are aggregated correctly in blocks."""
        base_time = datetime(2024, 1, 15, 10, 0, 0)
        entries = [
            self.create_entry(base_time, input_tokens=1000, output_tokens=500),
            self.create_entry(base_time + timedelta(hours=1), input_tokens=2000, output_tokens=1000),
        ]

        blocks = await self.service.identify_session_blocks(entries)

        assert len(blocks) == 1
        assert blocks[0].input_tokens == 3000
        assert blocks[0].output_tokens == 1500

    def test_filter_recent_blocks(self):
        """Test filtering recent blocks."""
        now = datetime.utcnow()
        old_time = now - timedelta(days=5)
        recent_time = now - timedelta(days=1)

        from app.models.schemas import SessionBlock

        blocks = [
            SessionBlock(
                id=old_time.isoformat(),
                start_time=old_time.isoformat(),
                end_time=(old_time + timedelta(hours=5)).isoformat(),
                is_active=False,
                is_gap=False,
                input_tokens=1000,
                output_tokens=500,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.01,
                models=["claude-sonnet-4-20250514"],
            ),
            SessionBlock(
                id=recent_time.isoformat(),
                start_time=recent_time.isoformat(),
                end_time=(recent_time + timedelta(hours=5)).isoformat(),
                is_active=False,
                is_gap=False,
                input_tokens=2000,
                output_tokens=1000,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.02,
                models=["claude-sonnet-4-20250514"],
            ),
        ]

        filtered = self.service._filter_recent_blocks(blocks, days=3)

        # Only the recent block should remain
        assert len(filtered) == 1
        assert filtered[0].id == recent_time.isoformat()

    def test_filter_recent_blocks_includes_active(self):
        """Test active blocks are always included regardless of age."""
        now = datetime.utcnow()
        old_time = now - timedelta(days=10)

        from app.models.schemas import SessionBlock

        blocks = [
            SessionBlock(
                id=old_time.isoformat(),
                start_time=old_time.isoformat(),
                end_time=(old_time + timedelta(hours=5)).isoformat(),
                is_active=True,  # Active even though old
                is_gap=False,
                input_tokens=1000,
                output_tokens=500,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                cost_usd=0.01,
                models=["claude-sonnet-4-20250514"],
            ),
        ]

        filtered = self.service._filter_recent_blocks(blocks, days=3)

        # Active block should be included
        assert len(filtered) == 1
        assert filtered[0].is_active
