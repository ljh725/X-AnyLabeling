"""
Unit tests for inspector validation engine rules.

Run: pytest tests/test_inspector_validation.py -v
"""

import pytest
import sys
import os.path as osp

# Add project root to path
sys.path.insert(0, osp.dirname(osp.dirname(osp.abspath(__file__))))

# Direct imports to avoid PyQt6 dependency.
# Both modules are registered under a shared pseudo-package name so that
# the relative import inside validation_engine (`from .flat_index import`)
# resolves correctly when loaded by file path.
import importlib.util

inspector_dir = osp.join(
    osp.dirname(osp.dirname(osp.abspath(__file__))),
    "anylabeling",
    "views",
    "labeling",
    "widgets",
    "inspector",
)

_PKG = "inspector_test"

# Load flat_index module
spec = importlib.util.spec_from_file_location(
    f"{_PKG}.flat_index", osp.join(inspector_dir, "flat_index.py")
)
flat_index_mod = importlib.util.module_from_spec(spec)
sys.modules[f"{_PKG}.flat_index"] = flat_index_mod
spec.loader.exec_module(flat_index_mod)
FlatIndex = flat_index_mod.FlatIndex
FlattenedRecord = flat_index_mod.FlattenedRecord

# Load validation_engine module
spec2 = importlib.util.spec_from_file_location(
    f"{_PKG}.validation_engine",
    osp.join(inspector_dir, "validation_engine.py"),
)
validation_engine_mod = importlib.util.module_from_spec(spec2)
sys.modules[f"{_PKG}.validation_engine"] = validation_engine_mod
spec2.loader.exec_module(validation_engine_mod)

Issue = validation_engine_mod.Issue
LabelInAllowlist = validation_engine_mod.LabelInAllowlist
GroupIdValid = validation_engine_mod.GroupIdValid
PersonRectRequiresGroupId = validation_engine_mod.PersonRectRequiresGroupId
GroupLabelUniqueness = validation_engine_mod.GroupLabelUniqueness
GroupIdUniqueness = validation_engine_mod.GroupIdUniqueness
HeadFaceGroupIdUniqueness = validation_engine_mod.HeadFaceGroupIdUniqueness
LabelShapeTypeBinding = validation_engine_mod.LabelShapeTypeBinding
GroupIdKeypointIntegrity = validation_engine_mod.GroupIdKeypointIntegrity
RequiredFieldNotEmpty = validation_engine_mod.RequiredFieldNotEmpty
AttributeConsistency = validation_engine_mod.AttributeConsistency
ValidationReport = validation_engine_mod.ValidationReport


class TestLabelInAllowlist:
    """Test LabelInAllowlist rule edge cases."""

    def test_empty_label(self):
        """Empty string label should be reported as error."""
        rule = LabelInAllowlist({"person", "head"})
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="",
            shape_type="rectangle",
            group_id=0,
        )
        issue = rule.check(record, [], None)
        assert issue is not None
        assert "空标签" in issue.message

    def test_none_label(self):
        """None label should be handled (treated as empty)."""
        rule = LabelInAllowlist({"person", "head"})
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label=None,  # type: ignore
            shape_type="rectangle",
            group_id=0,
        )
        # This may crash or behave unexpectedly
        try:
            issue = rule.check(record, [], None)
            # If it doesn't crash, it should report an error
            assert issue is not None
        except (AttributeError, TypeError) as e:
            pytest.fail(f"Rule crashed with None label: {e}")

    def test_valid_label(self):
        """Valid label should pass without issue."""
        rule = LabelInAllowlist({"person", "head"})
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="person",
            shape_type="rectangle",
            group_id=0,
        )
        issue = rule.check(record, [], None)
        assert issue is None


class TestGroupIdValid:
    """Test GroupIdValid rule edge cases."""

    def test_boolean_true_group_id(self):
        """Boolean True should be treated as invalid."""
        rule = GroupIdValid()
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="person",
            shape_type="rectangle",
            group_id=True,  # type: ignore
        )
        issue = rule.check(record, [], None)
        assert issue is not None, "Boolean True group_id should be invalid"

    def test_boolean_false_group_id(self):
        """Boolean False should be treated as invalid."""
        rule = GroupIdValid()
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="person",
            shape_type="rectangle",
            group_id=False,  # type: ignore
        )
        issue = rule.check(record, [], None)
        assert issue is not None, "Boolean False group_id should be invalid"

    def test_negative_group_id(self):
        """Negative integer should be invalid."""
        rule = GroupIdValid()
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="person",
            shape_type="rectangle",
            group_id=-1,
        )
        issue = rule.check(record, [], None)
        assert issue is not None, "Negative group_id should be invalid"

    def test_none_group_id(self):
        """None group_id should be allowed (no issue)."""
        rule = GroupIdValid()
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="person",
            shape_type="rectangle",
            group_id=None,
        )
        issue = rule.check(record, [], None)
        assert issue is None, "None group_id should be allowed"

    def test_valid_group_id(self):
        """Valid non-negative integer should pass."""
        rule = GroupIdValid()
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="person",
            shape_type="rectangle",
            group_id=5,
        )
        issue = rule.check(record, [], None)
        assert issue is None


class TestPersonRectRequiresGroupId:
    """Test PersonRectRequiresGroupId rule."""

    def test_none_group_id(self):
        """Person rectangle with None group_id should error."""
        rule = PersonRectRequiresGroupId()
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="person",
            shape_type="rectangle",
            group_id=None,
        )
        issue = rule.check(record, [], None)
        assert issue is not None

    def test_string_group_id(self):
        """Person rectangle with string group_id should error."""
        rule = PersonRectRequiresGroupId()
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="person",
            shape_type="rectangle",
            group_id="abc",  # type: ignore
        )
        issue = rule.check(record, [], None)
        assert issue is not None

    def test_negative_group_id(self):
        """Person rectangle with negative group_id should error."""
        rule = PersonRectRequiresGroupId()
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="person",
            shape_type="rectangle",
            group_id=-5,
        )
        issue = rule.check(record, [], None)
        assert issue is not None


class TestGroupLabelUniqueness:
    """Test GroupLabelUniqueness cross-file behavior."""

    def test_per_file_isolation(self):
        """Duplicates across different files should NOT be reported."""
        rule = GroupLabelUniqueness({"head", "face"})

        # Create a FlatIndex with two files having same group_id and label
        index = FlatIndex()
        index._records = [
            FlattenedRecord(
                file_path="/file1.json",
                image_path="img1.jpg",
                shape_index=0,
                label="head",
                shape_type="rectangle",
                group_id=1,
            ),
            FlattenedRecord(
                file_path="/file2.json",  # Different file
                image_path="img2.jpg",
                shape_index=0,
                label="head",
                shape_type="rectangle",
                group_id=1,  # Same group_id
            ),
        ]
        # Build internal indexes
        index._by_file = {
            "/file1.json": [index._records[0]],
            "/file2.json": [index._records[1]],
        }
        index._by_group = {
            1: index._records,
        }

        issues = rule.check_all(index)
        assert len(issues) == 0, "Cross-file duplicates should not be reported"

    def test_same_file_duplicate(self):
        """Duplicates within the same file should be reported."""
        rule = GroupLabelUniqueness({"head", "face"})

        index = FlatIndex()
        rec1 = FlattenedRecord(
            file_path="/file1.json",
            image_path="img1.jpg",
            shape_index=0,
            label="head",
            shape_type="rectangle",
            group_id=1,
        )
        rec2 = FlattenedRecord(
            file_path="/file1.json",  # Same file
            image_path="img1.jpg",
            shape_index=1,
            label="head",
            shape_type="rectangle",
            group_id=1,  # Same group_id
        )
        index._records = [rec1, rec2]
        index._by_file = {
            "/file1.json": [rec1, rec2],
        }
        index._by_group = {
            1: [rec1, rec2],
        }

        issues = rule.check_all(index)
        assert (
            len(issues) == 2
        ), "Same-file duplicates should be reported for both shapes"


class TestGroupIdUniqueness:
    """Test GroupIdUniqueness with empty UNIQUE_TYPES."""

    def test_empty_unique_types(self):
        """With empty UNIQUE_TYPES, no issues should be reported."""
        rule = GroupIdUniqueness()
        # UNIQUE_TYPES is empty by default

        index = FlatIndex()
        rec1 = FlattenedRecord(
            file_path="/file1.json",
            image_path="img1.jpg",
            shape_index=0,
            label="person",
            shape_type="rectangle",
            group_id=1,
        )
        rec2 = FlattenedRecord(
            file_path="/file1.json",
            image_path="img1.jpg",
            shape_index=1,
            label="person",
            shape_type="rectangle",
            group_id=1,
        )
        index._records = [rec1, rec2]
        index._by_file = {"/file1.json": [rec1, rec2]}
        index._by_group = {1: [rec1, rec2]}

        issues = rule.check_all(index)
        assert (
            len(issues) == 0
        ), "Empty UNIQUE_TYPES should not report any issues"


class TestHeadFaceGroupIdUniqueness:
    """Test HeadFaceGroupIdUniqueness with invalid group_ids."""

    def test_invalid_group_id_filtered(self):
        """Records with invalid group_id should be skipped, not crash."""
        rule = HeadFaceGroupIdUniqueness()

        index = FlatIndex()
        rec1 = FlattenedRecord(
            file_path="/file1.json",
            image_path="img1.jpg",
            shape_index=0,
            label="head",
            shape_type="rectangle",
            group_id=None,  # Invalid
        )
        rec2 = FlattenedRecord(
            file_path="/file1.json",
            image_path="img1.jpg",
            shape_index=1,
            label="head",
            shape_type="rectangle",
            group_id=-1,  # Invalid
        )
        index._records = [rec1, rec2]
        index._by_file = {"/file1.json": [rec1, rec2]}

        # Should not crash
        issues = rule.check_all(index)
        assert (
            len(issues) == 0
        ), "Invalid group_id records should be filtered out"


class TestLabelShapeTypeBinding:
    """Test LabelShapeTypeBinding rule."""

    def test_unbound_label(self):
        """Label not in rectangle_labels or point_labels should error."""
        rule = LabelShapeTypeBinding(
            rectangle_labels={"person", "head"},
            point_labels={"nose", "eye"},
        )
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="unknown_label",
            shape_type="rectangle",
            group_id=0,
        )
        issue = rule.check(record, [], None)
        assert issue is not None, "Unbound label should be reported"
        assert "unbound" in issue.message.lower() or "未绑定" in issue.message

    def test_rectangle_with_wrong_type(self):
        """Rectangle label used with point type should error."""
        rule = LabelShapeTypeBinding(
            rectangle_labels={"person", "head"},
            point_labels={"nose", "eye"},
        )
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="person",  # Rectangle label
            shape_type="point",  # Wrong type
            group_id=0,
        )
        issue = rule.check(record, [], None)
        assert issue is not None, "Wrong shape type should be reported"


class TestRequiredFieldNotEmpty:
    """Test RequiredFieldNotEmpty rule."""

    def test_empty_points(self):
        """Empty points list should be reported."""
        rule = RequiredFieldNotEmpty()
        record = FlattenedRecord(
            file_path="/test.json",
            image_path="test.jpg",
            shape_index=0,
            label="person",
            shape_type="rectangle",
            group_id=0,
            points_count=0,  # Empty points
        )
        issue = rule.check(record, [], None)
        assert issue is not None, "Empty points should be reported"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
