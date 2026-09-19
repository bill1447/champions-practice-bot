from champions_practice.opponent.preview import enumerate_preview_orders


def test_six_pokemon_has_90_bring_lead_choices() -> None:
    choices = enumerate_preview_orders(6)

    assert len(choices) == 90
    assert len(set(choices)) == 90


def test_preview_orders_select_four_unique_members() -> None:
    for order in enumerate_preview_orders(6):
        assert len(order) == 4
        assert len(set(order)) == 4
        assert all(1 <= index <= 6 for index in order)
