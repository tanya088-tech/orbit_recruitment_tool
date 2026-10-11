from processing.classifier import classify


def c(company="Acme", title="Analyst", description="", industries=None):
    return classify(company, title, description, industries)


def test_bfsi_from_linkedin_industry():
    r = c(industries="Financial Services")
    assert r.potential_bfsi and not r.potential_gcc
    assert "LinkedIn industry 'Financial Services'" in r.reason


def test_bfsi_from_company_and_title():
    assert c(company="Global Insurance Ltd").potential_bfsi
    assert c(title="Senior Credit Risk Analyst").potential_bfsi
    assert c(title="Wealth Management Associate").potential_bfsi


def test_bfsi_from_description_needs_three_distinct_terms():
    two = c(description="We serve banks and offer payments solutions.")
    assert not two.potential_bfsi
    three = c(description="We serve banks, run payments platforms and handle lending and insurance data.")
    assert three.potential_bfsi
    assert three.signals[0].strength == "weak"


def test_gcc_explicit_phrases():
    assert c(description="Join our Global Capability Centre in Pune.").potential_gcc
    assert c(description="We are the captive centre of a US group.").potential_gcc
    assert c(description="Part of our shared services organisation.").potential_gcc
    assert c(company="Acme GBS Global Business Services").potential_gcc


def test_bare_gcc_token_counts_only_outside_gulf_or_compiler_context():
    assert c(company="Acme Bank GCC").potential_gcc
    assert not c(description="Experience selling into UAE and GCC countries required.").potential_gcc
    assert not c(description="Strong C++ skills; GCC compiler and Clang toolchains.").potential_gcc


def test_captive_insurance_is_not_a_gcc_signal():
    assert not c(description="Manage our captive insurance programme.").potential_gcc


def test_center_wording_needs_multinational_cue_in_description():
    no_cue = c(description="You will work in our technology center on weekday shifts.")
    assert not no_cue.potential_gcc
    with_cue = c(description="You will work in our technology center, part of a multinational group.")
    assert with_cue.potential_gcc
    # but centre wording in the company name is enough on its own (weak signal)
    assert c(company="Acme Technology Centre India").potential_gcc
    assert c(company="Walmart Global Tech").potential_gcc


def test_unrelated_job_is_neither():
    r = c(company="Sunrise Pharma", title="Chemist", description="Lab work on tablets and syrups.", industries="Pharmaceutical Manufacturing")
    assert not r.potential_gcc and not r.potential_bfsi
    assert "no BFSI signals" in r.reason and "no GCC signals" in r.reason


def test_reason_never_claims_certainty():
    r = c(industries="Banking")
    assert "not a confirmed" in r.reason
