"""Known GCC employers (config/filter_rules.py KNOWN_GCC_EMPLOYERS): a vacancy at a listed multinational is tagged GCC from the
company name, except for branch / retail / field-sales roles, and the list also supplies the overseas-headquarters evidence."""
from config import settings
from processing.classifier import classify, headquarters_of, known_gcc_employer


def test_listed_employer_is_gcc_without_the_word_gcc_in_the_posting():
    c = classify("JPMorganChase", "Product Management - Vice President", "Build products for global teams.", "Financial Services")
    assert c.potential_gcc and c.potential_bfsi
    assert "known GCC employer" in c.reason


def test_listed_non_bfsi_employer_is_gcc():
    c = classify("Walmart Global Tech India", "Software Engineer III", "Work on supply chain platforms.", "Retail")
    assert c.potential_gcc and not c.potential_bfsi


def test_branch_and_retail_roles_are_not_gcc_from_the_name_alone():
    c = classify("DBS Bank", "Officer, Branch Relationship Manager, Consumer Banking", "Serve branch customers.", "Banking")
    assert not c.potential_gcc and c.potential_bfsi
    assert not classify("HSBC", "AVP Premier Relationship Manager", "Wealth clients.", "Financial Services").potential_gcc


def test_groups_with_an_ordinary_indian_business_need_a_capability_title():
    assert classify("Siemens", "Software Engineer", "Build the platform.", "Industrial Automation").potential_gcc
    assert not classify("Siemens", "Plant Manager", "Run the plant floor.", "Manufacturing").eligible
    assert not classify("Walmart", "Store Associate", "Help customers.", "Retail").eligible


def test_unlisted_or_look_alike_names_do_not_match():
    assert known_gcc_employer("Continental Hospitals") is None
    assert known_gcc_employer("Visa Steel") is None
    assert known_gcc_employer("Apple Hospitality Services") is None
    assert known_gcc_employer("Standard Chartered Global Business Services") is not None


def test_listed_employer_counts_as_overseas_headquarters(monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_OVERSEAS_HQ", True)
    assert headquarters_of("Lloyds Technology Centre", "")[0] == "outside"
    c = classify("Lloyds Technology Centre", "Data Engineer", "Engineering for the group.", "Banking")
    assert c.potential_gcc and "United Kingdom" in c.reason


def test_indian_employers_still_fail_the_overseas_rule(monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_OVERSEAS_HQ", True)
    assert not classify("Axis Bank", "Credit Manager", "Mortgage credit.", "Banking").eligible
