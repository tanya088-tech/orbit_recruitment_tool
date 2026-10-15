from processing.classifier import classify


def c(company="Acme", title="Analyst", description="", industries=None, posted_by=None):
    return classify(company, title, description, industries, posted_by=posted_by)


def test_bfsi_from_employer_industry():
    r = c(industries="Financial Services")
    assert r.potential_bfsi and not r.potential_gcc
    assert "industry 'Financial Services'" in r.reason


BANK_TEXT = "We are a bank. Our retail banking, lending and payments teams serve customers. Insurance partners too."


def test_a_bfsi_word_in_the_company_name_is_never_enough_by_itself():
    for name in ("Global Insurance Ltd", "Shield Assurance", "First Finance", "Acme Bank", "National Bank of Nowhere"):
        assert not c(company=name).eligible, name
        assert not c(company=name, description="Great team.").eligible, name
        assert not c(company=name, industries="Software Development", description=BANK_TEXT).eligible, name


def test_a_bfsi_company_name_counts_only_with_description_evidence_when_no_industry_is_stated():
    assert c(company="Global Insurance Ltd", description=BANK_TEXT).potential_bfsi
    assert not c(company="Global Insurance Ltd", description="We serve banks.").eligible          # one phrase is not enough


def test_well_known_bfsi_employers_are_recognised_without_a_keyword_in_the_name_or_an_industry():
    for name in ("HDFC", "Goldman Sachs", "Barclays", "Kotak Mahindra"):
        assert c(company=name).potential_bfsi, name
    assert c(company="Zeta Holdings", industries="Financial Services").potential_bfsi        # industry evidence, no keyword in the name


def test_bfsi_specific_job_titles_count_only_for_non_hr_titles():
    assert not c(title="Senior Credit Risk Analyst").eligible                                         # title alone is not evidence
    assert c(title="Senior Credit Risk Analyst", description=BANK_TEXT).potential_bfsi
    assert c(title="Insurance Underwriter", description=BANK_TEXT).potential_bfsi
    assert not c(title="Recruiter - Credit Risk and KYC hiring").potential_bfsi
    assert not c(title="HR Manager - Wealth Management").potential_bfsi


def test_bfsi_title_is_not_enough_when_the_employer_is_in_another_industry():
    assert not c(title="Underwriter", industries="Software Development").potential_bfsi
    many = "Work with banks, payments, lending and insurance data."
    assert c(title="Underwriter", description=many, industries="Software Development").potential_bfsi


def test_description_mentions_alone_never_qualify():
    r = c(description="We serve banks, run payments platforms and handle lending and insurance data.")
    assert not r.potential_bfsi and not r.potential_gcc


def test_gcc_self_description():
    assert c(description="Join our Global Capability Centre in Pune.").potential_gcc
    assert c(description="We are the captive centre of a US group.").potential_gcc
    assert c(description="Part of our shared services centre in Chennai.").potential_gcc


def test_a_gcc_style_company_name_is_never_enough_by_itself():
    for name in ("Electrical GCC", "Acme GBS Global Business Services", "Acme Global Capability Centre India", "Walmart Global Tech"):
        assert not c(company=name).eligible, name
        assert not c(company=name, industries="IT Services & Consulting", description="Lead enterprise IT strategy.").eligible, name
        assert not c(company=name, industries="IT & Software").eligible, name
    assert c(company="Acme GBS Global Business Services", description="Part of a multinational group.").potential_gcc


def test_gcc_wording_about_someone_else_does_not_count():
    assert not c(description="Candidates with experience in a Global Capability Centre preferred.").potential_gcc
    assert not c(title="GCC Hiring Lead", description="Hire for various roles.").potential_gcc


def test_bare_gcc_token_is_not_the_gulf_or_the_compiler():
    assert not c(company="Acme Bank GCC").potential_gcc
    assert c(description="We are Acme's GCC in Pune; join our GCC engineering teams.").potential_gcc
    assert not c(description="Experience selling into UAE and GCC countries required.").potential_gcc
    assert not c(description="Strong C++ skills; GCC compiler and Clang toolchains.").potential_gcc


def test_captive_insurance_is_not_a_gcc_signal():
    assert not c(description="Manage our captive insurance programme.").potential_gcc


def test_centre_wording_needs_a_multinational_cue_in_description():
    assert not c(description="You will work in our technology center on weekday shifts.").potential_gcc
    assert c(description="You will work in our technology center, part of a multinational group.").potential_gcc
    assert not c(company="Acme Technology Centre India").eligible                       # the name alone is not enough
    assert c(company="Acme Technology Centre India", description="We are part of a multinational group.").potential_gcc
    assert c(company="Walmart Global Tech", description="We are part of a multinational group.").potential_gcc


def test_unrelated_job_is_neither():
    r = c(company="Sunrise Pharma", title="Chemist", description="Lab work on tablets and syrups.", industries="Pharmaceutical Manufacturing")
    assert not r.potential_gcc and not r.potential_bfsi
    assert r.reason.startswith("Not eligible")


def test_recruitment_employers_and_agency_postings_never_qualify():
    assert c(company="Apex Staffing", industries="Banking").excluded_because
    assert not c(company="Apex Talent Solutions", industries="Staffing and Recruiting, Banking").eligible
    assert not c(company="Quick Hire", description="Hiring for our client, a leading bank. Join our Global Capability Centre.").eligible
    assert not c(company="Confidential", industries="Banking", posted_by="Genius Consultants Recruiters").eligible


def test_unnamed_employer_is_not_eligible_without_employer_evidence():
    assert not c(company="Confidential", title="Operations Analyst", description="We are a Global Capability Centre of a US group.").eligible


def test_reason_never_claims_certainty():
    r = c(industries="Banking")
    assert "not a verified company record" in r.reason


# -- company-page address rule (LinkedIn) and placeholder employer names ----------------------------------------------
OAK_DESC = "We have lent over $21 billion and support savers. Candidates need experience in regulated financial services."
GARBLED = "Utilities, Accommodation and Food Services, and Administrative and Support Services"


def p(company="OakNorth", url="https://uk.linkedin.com/company/oaknorth-bank", industries=GARBLED, desc=OAK_DESC,
      title="Senior Vice President - Business Assurance", posted_by=None):
    return classify(company, title, desc, industries, posted_by=posted_by, company_url=url)


def test_bank_page_address_with_garbled_industry_and_bfsi_wording_is_bfsi():
    r = p()
    assert r.potential_bfsi and not r.potential_gcc
    assert "LinkedIn page 'oaknorth-bank'" in r.reason


def test_page_address_rule_needs_bfsi_wording_in_the_description():
    assert not p(desc="Great team, great culture.").eligible


def test_page_address_rule_is_blocked_for_tech_consulting_education_staffing_internet_industries():
    for ind in ("Software Development", "IT Services and IT Consulting", "Business Consulting and Services", "Education",
                "Technology, Information and Internet", "Training"):
        assert not p(industries=ind).eligible, ind


def test_staffing_firms_stay_excluded_even_with_a_bfsi_page_address():
    assert not p(company="Apex Staffing", url="https://www.linkedin.com/company/apex-bank-staffing").eligible
    assert not p(industries="Staffing and Recruiting").eligible
    assert not p(company="Bankers Recruitment Consultants", url="https://www.linkedin.com/company/bankers-recruitment").eligible
    assert not p(desc="Hiring for our client, a leading bank. " + OAK_DESC).eligible


def test_page_address_without_a_bfsi_word_or_without_a_page_changes_nothing():
    assert not p(url="https://www.linkedin.com/company/virtusa", industries="Hospitals and Health Care").eligible
    assert not p(url=None).eligible
    assert not p(url="https://www.linkedin.com/jobs/view/123").eligible


def test_page_address_rule_never_lets_an_hr_or_generic_title_qualify_on_its_own():
    assert not p(title="HR Recruiter", desc="Hire staff.", industries="Hospitals and Health Care").eligible


def test_blank_industry_with_bank_page_address_is_still_decided_by_the_name_and_other_rules_only():
    assert not classify("Acme", "Analyst", OAK_DESC, None, company_url="https://www.linkedin.com/company/acme-bank").eligible


def test_blank_industry_does_not_exclude_a_clear_employer():
    assert classify("Goldman Sachs", "Analyst", "x", None).potential_bfsi
    assert classify("Zeta Corp", "Analyst", "We are a Global Capability Centre of a US group. Join our team.", None).potential_gcc
    assert not classify("Nova Corp", "Business Analyst", "We serve banks", None).eligible


def test_placeholder_company_names_are_never_eligible_even_with_a_bfsi_industry():
    for name in ("MNC", "Leading MNC", "leading mnc", "Reputed MNC"):
        r = c(company=name, title="Banking Chat Process", industries="Banking")
        assert not r.eligible and "not named" in r.reason, name
    assert c(company="MNC Bank Ltd", industries="Banking").potential_bfsi          # a real name that merely contains the letters
