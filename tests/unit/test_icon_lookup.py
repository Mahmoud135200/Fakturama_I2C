
import pytest

from fakturama_i2c.ui import fields


class FakeRect:
    def __init__(self, top: int):
        self.top = top
        self.left = 0
        self.right = 20
        self.bottom = top + 20


class FakeControl:
    """Minimal stand-in for a uiautomation control."""

    def __init__(self, control_type: str, name: str = "", top: int = 0, children=None, parent=None):
        self.ControlTypeName = control_type
        self.Name = name
        self.BoundingRectangle = FakeRect(top)
        self._children = children or []
        self._parent = parent
        for child in self._children:
            child._parent = self

    def GetChildren(self):
        return list(self._children)

    def GetParentControl(self):
        return self._parent

    def Exists(self, *_args):
        return True


def addresses_section(icon_tops):
    """A section pane holding the 'Addresses' label plus N icons."""
    label = FakeControl("TextControl", "Addresses")
    icons = [FakeControl("ImageControl", "", top) for top in icon_tops]
    return FakeControl("PaneControl", "", 0, [label] + icons), label, icons


@pytest.fixture
def patch_lookup(monkeypatch):
    """Make fields.icon_group resolve our fake label instead of querying UIA."""
    def install(label):
        def fake_text_control(**kwargs):
            return label if kwargs.get("Name") == "Addresses" else FakeControl("TextControl", "nope")
        monkeypatch.setattr(fields.auto, "TextControl", fake_text_control)
    return install


# ------------------------------------------------------------------ ordering

def test_icons_are_returned_top_to_bottom_regardless_of_tree_order(patch_lookup):
    """The upper icon must win even when the UIA tree lists them out of order."""
    label = FakeControl("TextControl", "Addresses")
    lower = FakeControl("ImageControl", "", 427)
    upper = FakeControl("ImageControl", "", 397)
    FakeControl("PaneControl", "", 0, [label, lower, upper])   # lower listed FIRST
    patch_lookup(label)

    icons = fields.icon_group(None, "Addresses", 2, timeout=1)
    assert icons[0] is upper
    assert icons[1] is lower


def test_existing_contact_icon_is_the_upper_one(patch_lookup):
    """Task 2.1: upper = select existing contact; lower = green '+' (new Debtor)."""
    pane, label, icons = addresses_section([397, 427])
    patch_lookup(label)

    chosen = fields.existing_contact_icon(None, timeout=1)
    assert chosen is icons[0]
    assert chosen.BoundingRectangle.top == 397


# -------------------------------------------------------------- strict count

def test_extra_icons_are_rejected_rather_than_silently_sliced(patch_lookup):
    """The regression this guards: a lenient `len(imgs) < count` accepted a
    changed layout and kept clicking position 0. If an icon were ever added
    ABOVE the existing-contact one, that would start creating a Debtor. An
    unexpected count must fail loudly instead."""
    pane, label, icons = addresses_section([370, 397, 427])   # one MORE than expected
    patch_lookup(label)

    with pytest.raises(Exception):
        fields.existing_contact_icon(None, timeout=1)


def test_too_few_icons_are_rejected(patch_lookup):
    pane, label, icons = addresses_section([397])
    patch_lookup(label)

    with pytest.raises(Exception):
        fields.existing_contact_icon(None, timeout=1)


def test_non_exact_mode_still_allows_extras(patch_lookup):
    """`Items` has four icons and only the first is used, so the lenient mode
    stays available for callers that genuinely want a prefix."""
    pane, label, icons = addresses_section([100, 130, 160, 190, 220])
    patch_lookup(label)

    got = fields.icon_group(None, "Addresses", 4, timeout=1, exact=False)
    assert len(got) == 4
    assert got[0].BoundingRectangle.top == 100


# ------------------------------------------------------------------ scoping

def test_only_icons_in_the_labels_own_parent_are_considered(patch_lookup):
    """Icons belonging to a different section must never leak in."""
    label = FakeControl("TextControl", "Addresses")
    mine = [FakeControl("ImageControl", "", 397), FakeControl("ImageControl", "", 427)]
    FakeControl("PaneControl", "", 0, [label] + mine)
    # A sibling section with its own icons, deliberately higher up the screen.
    FakeControl("PaneControl", "", 0, [FakeControl("TextControl", "Items"),
                                       FakeControl("ImageControl", "", 10)])
    patch_lookup(label)

    icons = fields.icon_group(None, "Addresses", 2, timeout=1)
    assert [i.BoundingRectangle.top for i in icons] == [397, 427]


def test_non_image_children_are_ignored(patch_lookup):
    label = FakeControl("TextControl", "Addresses")
    icons = [FakeControl("ImageControl", "", 397), FakeControl("ImageControl", "", 427)]
    FakeControl("PaneControl", "", 0, [label, FakeControl("EditControl", "noise", 380)] + icons)
    patch_lookup(label)

    assert len(fields.icon_group(None, "Addresses", 2, timeout=1)) == 2


def test_constants_document_the_mapping():
    """Named constants, not bare indexes, so the intent survives refactoring."""
    assert fields.ADDRESS_ICON_COUNT == 2
    assert fields.EXISTING_CONTACT_INDEX == 0
