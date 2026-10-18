from processing.description_sections import extract_sections
from processing.industry import CATEGORIES, OTHER, UNKNOWN, classify_industry
from processing.normalize import clean_company, clean_location, company_key


def test_industry_comes_only_from_the_source_label():
    cases = {
        "Financial Services": "Banking, Financial Services & Insurance (BFSI)", "Banking": "Banking, Financial Services & Insurance (BFSI)", "Insurance": "Banking, Financial Services & Insurance (BFSI)",
        "IT Services and IT Consulting": "IT & Software Services", "Software Development": "IT & Software Services",
        "Hospitals and Health Care": "Healthcare & Hospitals", "Retail Apparel and Fashion": "Retail & E-commerce",
        "Machinery Manufacturing": "Manufacturing & Industrial Engineering", "Business Consulting and Services": "Professional Services & Consulting",
        "Staffing and Recruiting": "Other", "Oil and Gas": "Oil, Gas & Energy", "Higher Education": "Education & EdTech",
    }
    for label, expected in cases.items():
        got = classify_industry(label)
        assert got.category == expected and got.label == label, label
        assert expected in CATEGORIES


def test_missing_label_is_unknown_and_unmapped_label_is_other_never_a_guess():
    for blank in (None, "", "   "):
        r = classify_industry(blank)
        assert r.category == UNKNOWN and r.label is None
    r = classify_industry("Underwater Basket Weaving")
    assert r.category == OTHER and r.label == "Underwater Basket Weaving"


def test_company_and_location_names_are_normalized_consistently():
    assert clean_company("  ACME   Bank ") == "ACME Bank"
    assert clean_company(None) is None
    keys = {company_key(x) for x in ("Acme Bank Pvt. Ltd.", "ACME BANK limited", "Acme Bank Private Limited", "Acme Bank Inc.")}
    assert keys == {"acme bank"}
    assert clean_location("Bangalore, Karnataka, India") == "Bengaluru, Karnataka, India"
    assert clean_location("Bengaluru,  Karnataka , India") == "Bengaluru, Karnataka, India"
    assert clean_location("Gurgaon, Haryana, India") == "Gurugram, Haryana, India"
    assert clean_location("Bombay, India") == "Mumbai, India" and clean_location("Madras, Tamil Nadu, India") == "Chennai, Tamil Nadu, India"
    assert clean_location("Pune, Pune, India") == "Pune, India"
    assert clean_location("Singapore") == "Singapore" and clean_location("") is None and clean_location(None) is None


DESC = """Demo Co builds made-up things for people who need things built across many markets worldwide.

Key Responsibilities:
- Build services
- Review code

Qualifications:
- Python
- SQL

Benefits:
- Free tea

You will need 5+ years of experience in engineering."""


def test_description_sections_are_copied_verbatim_and_never_invented():
    s = extract_sections(DESC)
    assert s.summary.startswith("Demo Co builds made-up things")
    assert s.responsibilities == ["Build services", "Review code"]
    assert "Python" in s.qualifications and "SQL" in s.qualifications
    assert s.experience == ["You will need 5+ years of experience in engineering."]
    for item in s.responsibilities + s.qualifications + s.experience:
        assert item in DESC                                          # nothing is rewritten or added


def test_description_sections_with_nothing_to_extract():
    for text in (None, "", "   ", "Short."):
        s = extract_sections(text)
        assert s.responsibilities == [] and s.qualifications == [] and s.experience == []
    assert extract_sections("No headings here, just one long paragraph about the company and its culture and values.").responsibilities == []


def test_paragraph_after_a_bullet_list_is_not_part_of_the_list():
    d = ("Demo Co builds things for people who need things built across many markets.\n\n"
         "Requirements:\n- Python\n- SQL\n\nYou will have 5+ years of experience in engineering.")
    s = extract_sections(d)
    assert s.qualifications == ["Python", "SQL"]
    assert s.experience == ["You will have 5+ years of experience in engineering."]
