"""
Inspector Validation Engine Bug Check

Run: cd tests && python test_inspector_direct.py
"""

import sys
import os.path as osp

# Setup paths - add parent dir and inspector dir
project_root = osp.dirname(osp.dirname(osp.abspath(__file__)))
inspector_dir = osp.join(project_root, "anylabeling", "views", "labeling", "widgets", "inspector")
sys.path.insert(0, inspector_dir)

# Import directly from the files
import importlib.util

# Load flat_index
spec1 = importlib.util.spec_from_file_location("flat_index", osp.join(inspector_dir, "flat_index.py"))
flat_index = importlib.util.module_from_spec(spec1)
flat_index.__package__ = "inspector"
sys.modules["flat_index"] = flat_index
spec1.loader.exec_module(flat_index)

# Load validation_engine
spec2 = importlib.util.spec_from_file_location("validation_engine", osp.join(inspector_dir, "validation_engine.py"))
validation_engine = importlib.util.module_from_spec(spec2)
validation_engine.__package__ = "inspector"
sys.modules["validation_engine"] = validation_engine
spec2.loader.exec_module(validation_engine)

# Get classes
FlattenedRecord = flat_index.FlattenedRecord
FlatIndex = flat_index.FlatIndex

Issue = validation_engine.Issue
LabelInAllowlist = validation_engine.LabelInAllowlist
GroupIdValid = validation_engine.GroupIdValid
PersonRectRequiresGroupId = validation_engine.PersonRectRequiresGroupId
GroupLabelUniqueness = validation_engine.GroupLabelUniqueness
GroupIdUniqueness = validation_engine.GroupIdUniqueness
HeadFaceGroupIdUniqueness = validation_engine.HeadFaceGroupIdUniqueness
LabelShapeTypeBinding = validation_engine.LabelShapeTypeBinding
GroupIdKeypointIntegrity = validation_engine.GroupIdKeypointIntegrity
RequiredFieldNotEmpty = validation_engine.RequiredFieldNotEmpty
AttributeConsistency = validation_engine.AttributeConsistency
is_valid_group_id = validation_engine.is_valid_group_id


def test(name, condition, message=""):
    """Simple test helper."""
    if condition:
        print(f"  ✓ {name}")
        return True
    else:
        print(f"  ✗ {name}")
        if message:
            print(f"    → {message}")
        return False


def run_tests():
    """Run all inspector validation tests."""
    passed = 0
    failed = 0
    bugs_found = []
    
    print("=" * 70)
    print("INSPECTOR VALIDATION ENGINE BUG CHECK")
    print("=" * 70)
    
    # ── 1. LabelInAllowlist ───────────────────────────────────────────
    print("\n[1] LabelInAllowlist Edge Cases")
    
    rule = LabelInAllowlist({"person", "head"})
    
    # Test empty label
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="", shape_type="rectangle", group_id=0,
    )
    issue = rule.check(record, [], None)
    if test("Empty label detected", issue is not None and "空标签" in issue.message):
        passed += 1
    else:
        failed += 1
    
    # Test None label (POTENTIAL BUG)
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label=None, shape_type="rectangle", group_id=0,
    )
    try:
        issue = rule.check(record, [], None)
        if test("None label handled", issue is not None):
            passed += 1
        else:
            failed += 1
    except Exception as e:
        test("None label crash", False, f"CRASH: {type(e).__name__}: {e}")
        bugs_found.append(("LabelInAllowlist", "None label crashes rule", "critical"))
        failed += 1
    
    # Test valid label
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="person", shape_type="rectangle", group_id=0,
    )
    issue = rule.check(record, [], None)
    if test("Valid label passes", issue is None):
        passed += 1
    else:
        failed += 1
    
    # ── 2. GroupIdValid ───────────────────────────────────────────────
    print("\n[2] GroupIdValid Edge Cases")
    
    rule = GroupIdValid()
    
    # Test boolean True
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="person", shape_type="rectangle", group_id=True,
    )
    issue = rule.check(record, [], None)
    if test("Boolean True rejected", issue is not None):
        passed += 1
    else:
        failed += 1
        bugs_found.append(("GroupIdValid", "Boolean True treated as valid", "high"))
    
    # Test boolean False
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="person", shape_type="rectangle", group_id=False,
    )
    issue = rule.check(record, [], None)
    if test("Boolean False rejected", issue is not None):
        passed += 1
    else:
        failed += 1
        bugs_found.append(("GroupIdValid", "Boolean False treated as valid", "high"))
    
    # Test negative
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="person", shape_type="rectangle", group_id=-1,
    )
    issue = rule.check(record, [], None)
    if test("Negative group_id rejected", issue is not None):
        passed += 1
    else:
        failed += 1
    
    # Test None (should be allowed)
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="person", shape_type="rectangle", group_id=None,
    )
    issue = rule.check(record, [], None)
    if test("None group_id allowed", issue is None):
        passed += 1
    else:
        failed += 1
    
    # Test valid
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="person", shape_type="rectangle", group_id=5,
    )
    issue = rule.check(record, [], None)
    if test("Valid group_id passes", issue is None):
        passed += 1
    else:
        failed += 1
    
    # ── 3. PersonRectRequiresGroupId ──────────────────────────────────
    print("\n[3] PersonRectRequiresGroupId Edge Cases")
    
    rule = PersonRectRequiresGroupId()
    
    # Test None
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="person", shape_type="rectangle", group_id=None,
    )
    issue = rule.check(record, [], None)
    if test("None group_id error", issue is not None):
        passed += 1
    else:
        failed += 1
    
    # Test string
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="person", shape_type="rectangle", group_id="abc",
    )
    issue = rule.check(record, [], None)
    if test("String group_id error", issue is not None):
        passed += 1
    else:
        failed += 1
    
    # Test negative
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="person", shape_type="rectangle", group_id=-5,
    )
    issue = rule.check(record, [], None)
    if test("Negative group_id error", issue is not None):
        passed += 1
    else:
        failed += 1
    
    # ── 4. GroupLabelUniqueness ───────────────────────────────────────
    print("\n[4] GroupLabelUniqueness Cross-File Behavior")
    
    rule = GroupLabelUniqueness({"head", "face"})
    
    # Cross-file test (should NOT report)
    index = FlatIndex()
    rec1 = FlattenedRecord(
        file_path="/file1.json", image_path="img1.jpg",
        shape_index=0, label="head", shape_type="rectangle", group_id=1,
    )
    rec2 = FlattenedRecord(
        file_path="/file2.json", image_path="img2.jpg",
        shape_index=0, label="head", shape_type="rectangle", group_id=1,
    )
    index._records = [rec1, rec2]
    index._by_file = {"/file1.json": [rec1], "/file2.json": [rec2]}
    index._by_group = {1: [rec1, rec2]}
    
    issues = rule.check_all(index)
    if test("Cross-file duplicates ignored", len(issues) == 0):
        passed += 1
    else:
        failed += 1
        bugs_found.append(("GroupLabelUniqueness", f"Reports cross-file duplicates ({len(issues)} issues)", "high"))
    
    # Same-file test (should report)
    index2 = FlatIndex()
    rec1 = FlattenedRecord(
        file_path="/file1.json", image_path="img1.jpg",
        shape_index=0, label="head", shape_type="rectangle", group_id=1,
    )
    rec2 = FlattenedRecord(
        file_path="/file1.json", image_path="img1.jpg",
        shape_index=1, label="head", shape_type="rectangle", group_id=1,
    )
    index2._records = [rec1, rec2]
    index2._by_file = {"/file1.json": [rec1, rec2]}
    index2._by_group = {1: [rec1, rec2]}
    
    issues = rule.check_all(index2)
    if test("Same-file duplicates detected", len(issues) == 2):
        passed += 1
    else:
        failed += 1
        print(f"    → Expected 2 issues, got {len(issues)}")
    
    # ── 5. GroupIdUniqueness ──────────────────────────────────────────
    print("\n[5] GroupIdUniqueness Empty UNIQUE_TYPES")
    
    rule = GroupIdUniqueness()
    index = FlatIndex()
    rec1 = FlattenedRecord(
        file_path="/file1.json", image_path="img1.jpg",
        shape_index=0, label="person", shape_type="rectangle", group_id=1,
    )
    rec2 = FlattenedRecord(
        file_path="/file1.json", image_path="img1.jpg",
        shape_index=1, label="person", shape_type="rectangle", group_id=1,
    )
    index._records = [rec1, rec2]
    index._by_file = {"/file1.json": [rec1, rec2]}
    index._by_group = {1: [rec1, rec2]}
    
    issues = rule.check_all(index)
    if test("Empty UNIQUE_TYPES no issues", len(issues) == 0):
        passed += 1
    else:
        failed += 1
    
    # ── 6. HeadFaceGroupIdUniqueness ──────────────────────────────────
    print("\n[6] HeadFaceGroupIdUniqueness Invalid Group IDs")
    
    rule = HeadFaceGroupIdUniqueness()
    index = FlatIndex()
    rec1 = FlattenedRecord(
        file_path="/file1.json", image_path="img1.jpg",
        shape_index=0, label="head", shape_type="rectangle", group_id=None,
    )
    rec2 = FlattenedRecord(
        file_path="/file1.json", image_path="img1.jpg",
        shape_index=1, label="head", shape_type="rectangle", group_id=-1,
    )
    index._records = [rec1, rec2]
    index._by_file = {"/file1.json": [rec1, rec2]}
    
    try:
        issues = rule.check_all(index)
        if test("Invalid group_id filtered", len(issues) == 0):
            passed += 1
        else:
            failed += 1
    except Exception as e:
        test("Invalid group_id handling", False, f"CRASH: {type(e).__name__}: {e}")
        bugs_found.append(("HeadFaceGroupIdUniqueness", "Crashes with invalid group_id", "critical"))
        failed += 1
    
    # ── 7. LabelShapeTypeBinding ──────────────────────────────────────
    print("\n[7] LabelShapeTypeBinding Edge Cases")
    
    rule = LabelShapeTypeBinding(
        rectangle_labels={"person", "head"},
        point_labels={"nose", "eye"},
    )
    
    # Unbound label
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="unknown", shape_type="rectangle", group_id=0,
    )
    issue = rule.check(record, [], None)
    if test("Unbound label detected", issue is not None):
        passed += 1
    else:
        failed += 1
        bugs_found.append(("LabelShapeTypeBinding", "Unbound label not detected", "medium"))
    
    # Wrong type
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="person", shape_type="point", group_id=0,
    )
    issue = rule.check(record, [], None)
    if test("Wrong shape type detected", issue is not None):
        passed += 1
    else:
        failed += 1
    
    # ── 8. RequiredFieldNotEmpty ──────────────────────────────────────
    print("\n[8] RequiredFieldNotEmpty Edge Cases")
    
    rule = RequiredFieldNotEmpty()
    
    # Empty points
    record = FlattenedRecord(
        file_path="/test.json", image_path="test.jpg",
        shape_index=0, label="person", shape_type="rectangle", group_id=0,
        points_count=0,
    )
    issue = rule.check(record, [], None)
    if test("Empty points detected", issue is not None):
        passed += 1
    else:
        failed += 1
    
    # ── Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    
    if bugs_found:
        print(f"\n🐛 BUGS FOUND ({len(bugs_found)}):")
        for rule_name, desc, severity in bugs_found:
            print(f"  [{severity.upper()}] {rule_name}: {desc}")
    else:
        print("\n✓ No bugs found in tested scenarios")
    
    return failed == 0, bugs_found


if __name__ == "__main__":
    success, bugs = run_tests()
    sys.exit(0 if success else 1)
