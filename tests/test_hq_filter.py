"""Parent Company Headquarters is a dashboard filter (Outside India / India or not outside India), not a mandatory rule."""
from config import settings
from dashboard import export, views
from dashboard import viewmodel as vm
from processing.classifier import classify, headquarters_of
from tests.factories import NOW, make_record
from tests.test_viewmodel import rows_from

US = "Acme Bank is headquartered in New York, USA. We are hiring in Pune."
IN = "Our parent company is headquartered in Mumbai, India. We are hiring in Pune."


def _rows():
    return rows_from([make_record(1, "Abroad", "Acme Bank", description=US), make_record(2, "Domestic", "Acme Bank", description=IN),
                      make_record(3, "Unverified", "Acme Bank", description="Credit analyst role in Pune.")])


def test_headquarters_comes_from_evidence_and_unverified_is_unknown():
    assert headquarters_of("Acme Bank", US)[0] == "outside" and headquarters_of("Acme Bank", US)[1]
    assert headquarters_of("Acme Bank", IN)[0] == "india"
    assert headquarters_of("Acme Bank", "Credit analyst role in Pune.") == ("unknown", "", "")
    assert headquarters_of("Pune Global Bank", "Based in Pune, India")[0] != "outside"      # location / name alone never decides


def test_the_rule_is_off_by_default_so_gcc_bfsi_vacancies_are_no_longer_excluded_by_headquarters():
    assert settings.REQUIRE_OVERSEAS_HQ is False
    assert classify(company="Acme Bank", title="Credit Analyst", industries="Banking", description=IN).eligible


def test_filter_shows_the_chosen_vacancies_and_all_by_default():
    rows = _rows()
    names = lambda f: sorted(r.title for r in vm.apply_filters(rows, f, NOW))
    assert names(vm.Filters()) == ["Abroad", "Domestic", "Unverified"]
    assert names(vm.Filters(hq="outside")) == ["Abroad"]
    assert names(vm.Filters(hq="india")) == ["Domestic", "Unverified"]
    f = vm.Filters.from_query({"hq": ["outside"]})
    assert f.hq == "outside" and "hq=outside" in f.to_query() and f.active_count == 1
    assert vm.Filters.from_query({"hq": ["bogus"]}).hq == "all"


def test_filter_combines_with_industry_and_the_page_and_csv_show_it():
    rows = _rows()
    got = vm.apply_filters(rows, vm.Filters(hq="outside", industry="Banking, Financial Services & Insurance (BFSI)"), NOW)
    assert [r.title for r in got] == ["Abroad"]
    html = views._filters_form(vm.Filters(hq="india"), vm.filter_options(rows))
    assert "Parent Company Headquarters" in html and "Outside India" in html and "India / Not Outside India" in html
    assert '<option value="india" selected>' in html
    csv_text = export.build_csv(rows).decode("utf-8-sig")
    assert "Parent company headquarters" in csv_text and "Unknown" in csv_text
