from tools.useful_volume_census import CensusConfig, census_row, useful_volume_census


def test_useful_volume_census_emits_conservative_packet():
    packet = useful_volume_census(CensusConfig(depths=[2, 8], dimensions=[8, 32], sample_count=128, seed=1701))

    assert packet["schema_version"] == "forge.optimizer.useful_volume_census.v1"
    assert len(packet["rows"]) == 4
    assert packet["boundaries"]["simulated"] is True
    assert packet["boundaries"]["hardware_observed"] is False
    assert packet["boundaries"]["optimizer_release_claim"] is False


def test_useful_volume_census_ratios_are_valid():
    row = census_row(dimension=32, depth=8, sample_count=256, seed=1701)

    assert 0 <= row["useful_ratio"] <= 1
    assert 0 <= row["finite_ratio"] <= 1
    assert 0 <= row["boundary_ratio"] <= 1
    assert 0 <= row["center_ratio"] <= 1
    assert row["finite_count"] + row["invalid_count"] == row["sample_count"]
    assert row["effective_coordinate_count"] == row["dimension"] * row["terminal_count"]


def test_useful_volume_collapses_with_depth_for_fixed_dimension():
    packet = useful_volume_census(CensusConfig(depths=[2, 10], dimensions=[64], sample_count=512, seed=1701))
    rows = sorted(packet["rows"], key=lambda row: row["tree_depth"])

    assert rows[-1]["useful_ratio"] <= rows[0]["useful_ratio"]
    assert rows[-1]["boundary_ratio"] >= rows[0]["boundary_ratio"]
