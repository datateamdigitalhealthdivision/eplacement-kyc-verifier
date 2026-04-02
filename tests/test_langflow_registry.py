from src.langflow_components import COMPONENT_CATALOG, component_catalog


def test_component_catalog_lists_expected_components() -> None:
    component_names = {spec["class_name"] for spec in COMPONENT_CATALOG}
    assert component_names == {
        "ApplicantLoaderComponent",
        "PDFFetchComponent",
        "OCRRouterComponent",
        "DocClassifierComponent",
        "EvidenceExtractorComponent",
        "RulesValidatorComponent",
        "ExportWriterComponent",
    }


def test_component_catalog_dict_view_matches_specs() -> None:
    catalog = component_catalog()
    assert len(catalog) == len(COMPONENT_CATALOG)
    assert catalog[0]["display_name"] == "Applicant Loader"
    assert catalog[-1]["class_name"] == "ExportWriterComponent"
    assert catalog is not COMPONENT_CATALOG
