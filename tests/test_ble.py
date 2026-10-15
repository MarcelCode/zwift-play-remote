from zwiftplay.ble import ControllerManager
from zwiftplay.events import ButtonDown, ButtonUp


def test_button_relayed_by_both_click_v2_halves_fires_once():
    # The left Click v2 relays the right one's buttons, so both report "a".
    events = []
    manager = ControllerManager(events.append)
    manager._update("right", frozenset({"a"}))
    manager._update("left", frozenset({"a"}))
    manager._update("right", frozenset())
    manager._update("left", frozenset())
    assert events == [ButtonDown("a"), ButtonUp("a")]


def test_buttons_on_different_controllers_are_independent():
    events = []
    manager = ControllerManager(events.append)
    manager._update("left", frozenset({"navigationUp"}))
    manager._update("right", frozenset({"a"}))
    manager._update("left", frozenset())
    assert events == [ButtonDown("navigationUp"), ButtonDown("a"), ButtonUp("navigationUp")]
